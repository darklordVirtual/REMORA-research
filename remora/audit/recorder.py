# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A reference recorder that runs outside the agent's process (quality program Q7.6).

Every REMORA audit chain is tamper-evident once written, and every one of
them is written by the process that executes the action. Qin, Schmotz,
Prinzhorn et al. (2026), *LLM Agents Can Easily Tamper With Their Own
Traces* (arXiv:2609.30266, SHELF-030), report that agents in most local
harnesses they tested deleted their own traces when asked or when it paid,
without tripping guardrails, and recommend capture outside the agent's
control. A chain the agent's process can rewrite is evidence only for as
long as the agent chooses to leave it alone.

This module is the reference form of that capture:

a separate process
    ``python -m remora.audit.recorder --db PATH --listen ADDRESS`` owns the
    store. The agent side holds only :class:`RecorderClient`, which speaks a
    line-delimited JSON protocol: one append and two read-only operations.
    There is no delete, update or truncate operation to call.
append-only storage
    SQLite with a hash chain over every event, and triggers that abort any
    ``UPDATE`` or ``DELETE`` on the event table, so even a statement sent to
    the file directly is refused unless the triggers are dropped first.
receipts
    every append returns ``(seq, entry_hash)``. A holder of a receipt can ask
    the recorder to prove the event is still there unchanged
    (:meth:`RecorderClient.confirm`); a deleted or rewritten event fails.
fail closed
    ``GovernedToolDispatcher.bind_recorder`` makes recording mandatory for the
    tools a deployment names: the intent is appended *before* the nonce is
    consumed, and an unreachable recorder refuses the call as
    ``recorder_unavailable``. Nothing runs that was not recorded first.

Scope, stated plainly: this is a reference implementation of the protocol
and the fail-closed rule. Separation is only as strong as the deployment
makes it: run the recorder as another OS user, on another host, or behind a
socket whose file permissions the agent does not hold. REMORA does not
configure that. The durable, independently operated sink is an owner
decision and overlaps REM-025.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import socket
import socketserver
import sqlite3
import sys
import threading
from dataclasses import dataclass
from typing import Any

from remora.errors import RemoraError

__all__ = [
    "RecorderClient",
    "RecorderReceipt",
    "RecorderStore",
    "RecorderUnavailable",
    "serve",
]

_GENESIS = "0" * 64
#: One request or response per line; bounded so a hostile peer cannot make
#: the recorder buffer without limit.
_MAX_LINE = 256 * 1024

_DDL = (
    "CREATE TABLE IF NOT EXISTS recorder_events ("
    "seq INTEGER PRIMARY KEY, stream TEXT NOT NULL, event TEXT NOT NULL, "
    "previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL)",
    "CREATE TRIGGER IF NOT EXISTS recorder_no_update BEFORE UPDATE ON recorder_events "
    "BEGIN SELECT RAISE(ABORT, 'recorder events are append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS recorder_no_delete BEFORE DELETE ON recorder_events "
    "BEGIN SELECT RAISE(ABORT, 'recorder events are append-only'); END",
)


class RecorderUnavailable(RemoraError, RuntimeError):
    """The recorder could not be reached or did not confirm the append."""

    code = "recorder_unavailable"
    category = "audit"


@dataclass(frozen=True)
class RecorderReceipt:
    seq: int
    entry_hash: str


def _entry_hash(previous_hash: str, seq: int, stream: str, event_json: str) -> str:
    material = json.dumps([previous_hash, seq, stream, event_json], separators=(",", ":"))
    return hashlib.sha256(material.encode()).hexdigest()


class RecorderStore:
    """The recorder's own storage. Only the recorder process opens it."""

    def __init__(self, db_path: str) -> None:
        if not db_path or ":memory:" in db_path:
            raise ValueError("the recorder needs a file; an in-memory store records nothing")
        self._db_path = db_path
        self._lock = threading.Lock()
        with self._connect() as conn:
            for statement in _DDL:
                conn.execute(statement)

    @contextlib.contextmanager
    def _connect(self) -> Any:
        """One connection per operation, committed on success and always closed.

        ``with sqlite3.connect(...)`` alone commits but never closes, which
        leaks a handle per call in a long-running recorder.
        """
        conn = sqlite3.connect(self._db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def append(self, stream: str, event: dict[str, Any]) -> RecorderReceipt:
        if not stream:
            raise ValueError("an event needs a stream")
        event_json = json.dumps(event, sort_keys=True, separators=(",", ":"), default=str)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT seq, entry_hash FROM recorder_events ORDER BY seq DESC LIMIT 1").fetchone()
            seq, previous = (row[0] + 1, row[1]) if row else (0, _GENESIS)
            entry_hash = _entry_hash(previous, seq, stream, event_json)
            conn.execute(
                "INSERT INTO recorder_events (seq, stream, event, previous_hash, entry_hash) "
                "VALUES (?, ?, ?, ?, ?)", (seq, stream, event_json, previous, entry_hash))
        return RecorderReceipt(seq, entry_hash)

    def head(self) -> RecorderReceipt | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT seq, entry_hash FROM recorder_events ORDER BY seq DESC LIMIT 1").fetchone()
        return RecorderReceipt(row[0], row[1]) if row else None

    def verify(self) -> list[str]:
        """Recompute the chain; every break is reported."""
        problems: list[str] = []
        previous = _GENESIS
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, stream, event, previous_hash, entry_hash "
                "FROM recorder_events ORDER BY seq").fetchall()
        for expected_seq, (seq, stream, event_json, prev, entry_hash) in enumerate(rows):
            if seq != expected_seq:
                problems.append(f"sequence_gap_at:{expected_seq}")
            if prev != previous:
                problems.append(f"chain_break_at:{seq}")
            if _entry_hash(prev, seq, stream, event_json) != entry_hash:
                problems.append(f"hash_mismatch_at:{seq}")
            previous = entry_hash
        return problems

    def confirm(self, receipt: RecorderReceipt) -> bool:
        """The event behind ``receipt`` is still there, unchanged, in an intact chain."""
        with self._connect() as conn:
            row = conn.execute("SELECT entry_hash FROM recorder_events WHERE seq = ?",
                               (receipt.seq,)).fetchone()
        return row is not None and row[0] == receipt.entry_hash and not self.verify()


def _handle(store: RecorderStore, request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        return {"ok": False, "error": "request must be an object"}
    op = request.get("op")
    if op == "append":
        event = request.get("event")
        stream = request.get("stream")
        if not isinstance(event, dict) or not isinstance(stream, str):
            return {"ok": False, "error": "append needs a stream and an event object"}
        receipt = store.append(stream, event)
        return {"ok": True, "seq": receipt.seq, "entry_hash": receipt.entry_hash}
    if op == "head":
        head = store.head()
        return {"ok": True, "seq": head.seq if head else None,
                "entry_hash": head.entry_hash if head else None}
    if op == "confirm":
        try:
            receipt = RecorderReceipt(int(request["seq"]), str(request["entry_hash"]))
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "error": "confirm needs seq and entry_hash"}
        return {"ok": True, "confirmed": store.confirm(receipt)}
    # Deliberately no delete, update, truncate or reset: an operation that
    # does not exist cannot be called by whoever holds the client.
    return {"ok": False, "error": f"unsupported operation {op!r}"}


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        store: RecorderStore = self.server.store  # type: ignore[attr-defined]
        while True:
            # Bounded read: never buffer more than one limit's worth of a line.
            raw = self.rfile.readline(_MAX_LINE + 1)
            if not raw:
                return
            if len(raw) > _MAX_LINE:
                # The rest of the line is unread and unframed: answer once and
                # drop the connection rather than reading it.
                refusal = {"ok": False, "error": "request too large"}
                self.wfile.write((json.dumps(refusal) + "\n").encode())
                return
            try:
                response: dict[str, Any] = _handle(store, json.loads(raw))
            except (ValueError, sqlite3.Error) as exc:
                response = {"ok": False, "error": type(exc).__name__}
            self.wfile.write((json.dumps(response) + "\n").encode())


class _TCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(db_path: str, host: str = "127.0.0.1", port: int = 0,
          ready: Any = None) -> None:
    """Run the recorder until interrupted. Prints ``READY host:port``."""
    server = _TCPServer((host, port), _Handler)
    server.store = RecorderStore(db_path)  # type: ignore[attr-defined]
    bound_host, bound_port = str(server.server_address[0]), int(server.server_address[1])
    print(f"READY {bound_host}:{bound_port}", flush=True, file=ready or sys.stdout)
    try:
        server.serve_forever()
    finally:
        server.server_close()


class RecorderClient:
    """The agent side. Append, read the head, confirm a receipt. Nothing else."""

    def __init__(self, address: str, *, timeout: float = 2.0) -> None:
        host, _, port = address.rpartition(":")
        if not host or not port.isdigit():
            raise ValueError("recorder address must be host:port")
        self._address = (host, int(port))
        self._timeout = timeout

    def _call(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            with socket.create_connection(self._address, timeout=self._timeout) as sock:
                sock.sendall((json.dumps(request) + "\n").encode())
                with sock.makefile("rb") as reader:
                    line = reader.readline(_MAX_LINE + 1)
        except OSError as exc:
            raise RecorderUnavailable(f"recorder unreachable: {exc}") from exc
        try:
            response = json.loads(line)
        except ValueError as exc:
            raise RecorderUnavailable("recorder sent no valid response") from exc
        if not isinstance(response, dict) or not response.get("ok"):
            raise RecorderUnavailable(f"recorder refused: {response!r}")
        return response

    def append(self, stream: str, event: dict[str, Any]) -> RecorderReceipt:
        response = self._call({"op": "append", "stream": stream, "event": event})
        return RecorderReceipt(int(response["seq"]), str(response["entry_hash"]))

    def head(self) -> RecorderReceipt | None:
        response = self._call({"op": "head"})
        if response.get("seq") is None:
            return None
        return RecorderReceipt(int(response["seq"]), str(response["entry_hash"]))

    def confirm(self, receipt: RecorderReceipt) -> bool:
        return bool(self._call({"op": "confirm", "seq": receipt.seq,
                                "entry_hash": receipt.entry_hash})["confirmed"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="REMORA reference recorder (Q7.6)")
    parser.add_argument("--db", required=True, help="SQLite file the recorder owns")
    parser.add_argument("--listen", default="127.0.0.1:0", help="host:port; port 0 picks one")
    args = parser.parse_args(argv)
    host, _, port = args.listen.rpartition(":")
    serve(args.db, host or "127.0.0.1", int(port or 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
