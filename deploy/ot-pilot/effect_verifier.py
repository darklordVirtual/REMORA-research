# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The OT pilot's effect verifier: reads the plant back after every write (AACP G).

A separate container and control domain. It holds three things and nothing
else:

* ``OT_PLANT_READ_TOKEN``: read-only at the plant. It can read objects and the
  journal and cannot change the state it reports on;
* ``OT_VERIFIER_SIGNING_SEED``: an Ed25519 seed for ``REMORA/EFFECT-RECEIPT/v1``,
  whose public key the API registers as control domain
  ``ot-pilot-plant-observer`` with credential scope ``read_only``;
* ``OT_TOKEN_VERIFIER``: REMORA role ``effect_verifier`` (read, verify_effect).

It finds every executed dispatch itself (``GET /v1/execution/dispatches``),
not from the agent or the executor. For each write it takes the plant's
journal entry for that dispatch (the arguments the plant received and the
object's revision before the write), reads the object back, signs a receipt
and posts it to ``/proposals/{id}/effect-receipt``. REMORA then computes the
verdict from the signed ToolSpec postcondition and the approved arguments;
the verifier's own reading is never the verdict.

Outcomes the verifier cannot turn into a receipt are reported, not dropped:
an executed write with no plant record, and a plant write that names no
executed dispatch, are listed at ``GET /report`` together with the latest
journal reconciliation (``reconcile.py``).

    python effect_verifier.py   # env as above, plus OT_API_URL and OT_PLANT_URL
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plant_model import TOOL_TARGETS  # noqa: E402
from reconcile import WRITE_TOOLS, reconcile  # noqa: E402

TENANT = "ot-pilot"
#: Verdicts after which the dispatch needs no further receipt.
TERMINAL = frozenset({"EFFECT_VERIFIED", "EFFECT_MISMATCH", "EFFECT_UNSUPPORTED"})
#: An UNOBSERVABLE verdict is "not known yet"; the verifier tries again this
#: many times before it leaves the dispatch unobservable.
MAX_ATTEMPTS = 3


class Http:
    """Minimal JSON client with a bearer token."""

    def __init__(self, base: str, token: str, timeout: float = 5.0) -> None:
        self.base, self.token, self.timeout = base.rstrip("/"), token, timeout

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            f"{self.base}{path}", data=data, method=method,
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"null")
            except ValueError:
                return exc.code, None


class Verifier:
    """One pass at a time over REMORA's dispatches. Thread-safe report."""

    def __init__(self, api: Http, plant: Http, signing_key: Any,
                 clock: Any = None) -> None:
        self.api, self.plant, self.key = api, plant, signing_key
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self.attempts: dict[str, int] = {}
        self.results: dict[str, dict[str, Any]] = {}
        self.anomalies: dict[str, dict[str, Any]] = {}
        self.last_reconciliation: dict[str, Any] | None = None
        self.errors: list[str] = []

    # ── inputs ────────────────────────────────────────────────────────────

    def dispatches(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        after = 0
        while True:
            status, body = self.api.call(
                "GET", f"/v1/execution/dispatches?after_sequence={after}&limit=500")
            if status != 200 or not isinstance(body, dict):
                raise RuntimeError(f"dispatch listing answered {status}")
            page = body.get("dispatches") or []
            rows.extend(page)
            if not page:
                return rows
            after = int(body["next_after_sequence"])

    def journal(self) -> list[dict[str, Any]]:
        status, body = self.plant.call("GET", "/journal")
        if status != 200:
            raise RuntimeError(f"plant journal answered {status}")
        return list(body["entries"])

    # ── one dispatch ──────────────────────────────────────────────────────

    def receipt_for(self, row: dict[str, Any], entry: dict[str, Any]) -> tuple[Any, Any, dict]:
        from remora.governance.effect_receipt_signing import EffectReceipt, sign_receipt

        arg, kind, _ = TOOL_TARGETS[row["tool_name"]]
        ident = str(entry["arguments"].get(arg))
        status, obj = self.plant.call(
            "GET", f"/objects/{kind}/{urllib.request.quote(ident, safe='')}")
        observed = obj if status == 200 and isinstance(obj, dict) else None
        receipt = EffectReceipt(
            proposal_id=row["proposal_id"], grant_jti=row["grant_jti"],
            tool_call_hash=row["tool_call_hash"], tenant=TENANT,
            observed=observed, observed_at=self._clock().isoformat(),
            source_revision=str(observed["revision"]) if observed else "",
            pre_state_revision=str(entry.get("rev_before", "")),
        )
        return receipt, sign_receipt(receipt, self.key), dict(entry["arguments"])

    def verify(self, row: dict[str, Any], journal: list[dict[str, Any]]) -> None:
        pid = row["proposal_id"]
        applied = [e for e in journal if e.get("outcome") == "applied"
                   and e.get("dispatch_ref") == pid]
        if len(applied) != 1:
            with self._lock:
                self.anomalies[pid] = {
                    "proposal_id": pid, "tool_name": row["tool_name"],
                    "reason": ("dispatch_without_plant_record" if not applied
                               else "dispatch_named_twice_at_plant"),
                    "applied_entries": len(applied)}
            return
        receipt, signature, arguments = self.receipt_for(row, applied[0])
        status, body = self.api.call(
            "POST", f"/v1/execution/proposals/{pid}/effect-receipt",
            {"receipt": receipt.to_dict(), "signature": signature.to_dict(),
             "arguments": arguments})
        with self._lock:
            self.attempts[pid] = self.attempts.get(pid, 0) + 1
            self.results[pid] = {
                "proposal_id": pid, "tool_name": row["tool_name"], "http": status,
                "status": (body or {}).get("status") if isinstance(body, dict) else None,
                "reason_code": (body or {}).get("reason_code") if isinstance(body, dict) else None,
                "vantage": (body or {}).get("vantage") if isinstance(body, dict) else None,
                "detail": (body or {}).get("detail") if isinstance(body, dict) else None,
                "observed": receipt.to_dict()["observed"],
                "source_revision": receipt.source_revision,
                "pre_state_revision": receipt.pre_state_revision,
                "attempts": self.attempts[pid],
            }

    def due(self, row: dict[str, Any]) -> bool:
        if not row.get("executed") or row.get("tool_name") not in WRITE_TOOLS:
            return False
        status = row.get("effect_status")
        if status in TERMINAL:
            return False
        return self.attempts.get(row["proposal_id"], 0) < MAX_ATTEMPTS

    def run_once(self) -> dict[str, Any]:
        rows = self.dispatches()
        journal = self.journal()
        for row in rows:
            if self.due(row):
                try:
                    self.verify(row, journal)
                except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                    with self._lock:
                        self.errors.append(f"{row.get('proposal_id')}: {exc}")
        status, digest = self.plant.call("GET", "/digest")
        rec = reconcile(journal, rows, live_digest=(digest or {}).get("live", ""),
                        replayed_digest=(digest or {}).get("replayed", "-"))
        with self._lock:
            self.last_reconciliation = rec
        return rec

    def report(self) -> dict[str, Any]:
        with self._lock:
            return {"results": sorted(self.results.values(), key=lambda r: r["proposal_id"]),
                    "anomalies": sorted(self.anomalies.values(),
                                        key=lambda r: r["proposal_id"]),
                    "reconciliation": self.last_reconciliation,
                    "errors": list(self.errors[-50:]),
                    "verifier_kid": self.key.kid}


def _serve_report(verifier: Verifier, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            body = (verifier.report() if self.path.startswith("/report")
                    else {"ok": True} if self.path == "/health" else None)
            data = json.dumps(body).encode("utf-8")
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()  # noqa: S104


def main() -> None:
    from remora.crypto import SigningKey
    from remora.governance.effect_receipt_signing import RECEIPT_DOMAIN

    key = SigningKey.from_text(os.environ["OT_VERIFIER_SIGNING_SEED"], {RECEIPT_DOMAIN})
    verifier = Verifier(
        Http(os.environ.get("OT_API_URL", "http://api:8000"), os.environ["OT_TOKEN_VERIFIER"]),
        Http(os.environ.get("OT_PLANT_URL", "http://plant:9100"),
             os.environ["OT_PLANT_READ_TOKEN"]),
        key)
    threading.Thread(target=_serve_report,
                     args=(verifier, int(os.environ.get("OT_VERIFIER_PORT", "9200"))),
                     daemon=True).start()
    interval = float(os.environ.get("OT_VERIFIER_INTERVAL_S", "1.0"))
    print(f"ot-effect-verifier {key.kid} polling every {interval}s", flush=True)
    while True:
        try:
            verifier.run_once()
        except Exception as exc:  # noqa: BLE001 - the loop must survive an outage
            with verifier._lock:
                verifier.errors.append(f"pass: {exc}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
