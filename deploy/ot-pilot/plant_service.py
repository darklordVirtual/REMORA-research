# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The OT pilot's plant as its own service and trust domain (AACP E and G).

Until 2026-11-06 the simulated plant ran inside the API process, so anything
that could run code beside REMORA could change it, and the only read-back of
an effect was the dictionary the write went to. Here the plant is a separate
process with two credentials of its own:

* ``OT_PLANT_WRITE_TOKEN``: held by the REMORA executor (the API container)
  only. It may write and read.
* ``OT_PLANT_READ_TOKEN``: held by the effect verifier only. It may read
  objects and the journal and can change nothing, so what the verifier
  reports is not something it could have produced (REMORA derives the
  verifier's vantage from that credential scope).

Every request it answers, except the unauthenticated ``/health``, is
journaled with the credential it presented: writes, reads and refusals,
including the ones refused for having no credential. ``GET /journal`` serves the journal, and
``GET /digest`` the live and replayed state digests, which is how a run shows
that no state change escaped the journal.

Standard library only (``http.server``). No REMORA code is imported, so the
container holding the plant holds none of REMORA's keys or modules.

    OT_PLANT_WRITE_TOKEN=... OT_PLANT_READ_TOKEN=... python plant_service.py
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plant_model import Plant, PlantRefused  # noqa: E402

__all__ = ["PlantHandler", "build_server", "main"]

_MAX_BODY = 64 * 1024


def _credentials() -> dict[str, str]:
    """Token -> role. Both tokens are required, distinct and long."""
    write = os.environ.get("OT_PLANT_WRITE_TOKEN", "")
    read = os.environ.get("OT_PLANT_READ_TOKEN", "")
    if len(write) < 32 or len(read) < 32 or hmac.compare_digest(write, read):
        raise SystemExit("plant refuses to start: OT_PLANT_WRITE_TOKEN and "
                         "OT_PLANT_READ_TOKEN must be distinct and at least 32 characters")
    return {write: "writer", read: "reader"}


def credential_id(token: str) -> str:
    """A name for one credential that does not reveal it: the journal records
    which write credential made a write, and the verifier compares it."""
    return "cred-" + hashlib.sha256(b"ot-plant-credential-id\x00"
                                    + token.encode("utf-8")).hexdigest()[:16]


def _faults() -> dict[str, Any]:
    raw = os.environ.get("OT_PLANT_FAULTS", "").strip()
    return json.loads(raw) if raw else {}


class PlantHandler(BaseHTTPRequestHandler):
    plant: Plant
    tokens: dict[str, str]
    server_version = "ot-plant/1"

    def log_message(self, fmt: str, *args: Any) -> None:  # the journal is the log
        return

    # ── helpers ───────────────────────────────────────────────────────────

    def _role(self) -> str:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return "none"
        presented = header[len("Bearer "):].strip()
        for token, role in self.tokens.items():
            if hmac.compare_digest(presented, token):
                self._credential_id = credential_id(token)
                return role
        return "invalid"

    def _send(self, status: int, body: Any) -> None:
        data = json.dumps(body, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _refuse(self, status: int, reason: str, role: str) -> None:
        self.plant.note_request(self.command, urlparse(self.path).path, credential=role,
                                source=self.client_address[0], status=status, reason=reason)
        self._send(status, {"error": reason})

    def _answer(self, role: str, status: int, body: Any) -> None:
        """Send a read's answer and journal it, served or refused."""
        self.plant.note_request(
            self.command, urlparse(self.path).path, credential=role,
            source=self.client_address[0], status=status,
            reason="" if status == 200 else str((body or {}).get("error", "")),
            outcome="read" if status == 200 else "refused")
        self._send(status, body)

    def _readable(self, role: str) -> bool:
        if role in ("writer", "reader"):
            return True
        self._refuse(401 if role in ("none", "invalid") else 403,
                     "a read needs the plant read or write credential", role)
        return False

    # ── routes ────────────────────────────────────────────────────────────

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        url = urlparse(self.path)
        parts = [unquote(p) for p in url.path.split("/") if p]
        if parts == ["health"]:
            # Unauthenticated and not journaled: liveness for the orchestrator.
            # Active faults are reported, so a faulty plant cannot pass as an
            # honest one.
            return self._send(200, {"ok": True, "started_at": self.plant.started_at,
                                    "faults": {k: list(v) for k, v in self.plant.faults.items()}})
        role = self._role()
        if not self._readable(role):
            return None
        query = parse_qs(url.query)
        try:
            if len(parts) == 3 and parts[0] == "objects":
                raw = (query.get("revision") or [None])[0]
                revision = int(raw) if raw is not None else None
                return self._answer(role, 200,
                                    self.plant.read_object(parts[1], parts[2], revision))
            if len(parts) == 2 and parts[0] == "sensors":
                return self._answer(role, 200, self.plant.read_sensor(parts[1]))
            if len(parts) == 3 and parts[0] == "observe":
                return self._answer(role, 200,
                                    {"value": self.plant.observe(parts[1], parts[2])})
            if parts == ["journal"]:
                since = int((query.get("since") or ["0"])[0])
                body = {"entries": self.plant.journal_since(max(since, 0)),
                        "started_at": self.plant.started_at}
                return self._answer(role, 200, body)
            if parts == ["digest"]:
                return self._answer(role, 200, {"live": self.plant.digest(),
                                                "replayed": self.plant.replay_digest()})
        except PlantRefused as exc:
            return self._answer(role, exc.status, {"error": exc.reason})
        except (KeyError, ValueError) as exc:
            return self._answer(role, 404, {"error": str(exc)})
        return self._refuse(404, "no such route", role)

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        role = self._role()
        if len(parts) != 2 or parts[0] != "tools":
            return self._refuse(404, "no such route", role)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > _MAX_BODY:
            return self._refuse(413, "body too large", role)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            arguments = body.get("arguments")
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be an object")
        except (ValueError, AttributeError) as exc:
            return self._refuse(400, f"malformed body: {exc}", role)
        try:
            result = self.plant.apply(parts[1], arguments, credential=role,
                                      dispatch_ref=str(body.get("dispatch_ref") or ""),
                                      source=self.client_address[0],
                                      credential_id=getattr(self, "_credential_id", ""))
        except PlantRefused as exc:
            return self._send(exc.status, {"error": exc.reason})
        return self._send(200, result)

    def do_PUT(self) -> None:  # noqa: N802
        self._refuse(405, "method not allowed", self._role())

    do_DELETE = do_PATCH = do_PUT  # noqa: N815


def build_server(host: str, port: int, plant: Plant,
                 tokens: dict[str, str]) -> ThreadingHTTPServer:
    handler = type("BoundPlantHandler", (PlantHandler,), {"plant": plant, "tokens": tokens})
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    tokens = _credentials()
    plant = Plant(faults=_faults())
    port = int(os.environ.get("OT_PLANT_PORT", "9100"))
    server = build_server("0.0.0.0", port, plant, tokens)  # noqa: S104 - container network
    print(f"ot-plant listening on :{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
