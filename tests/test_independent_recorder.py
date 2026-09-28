# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The reference recorder runs in another process and cannot be edited from this one.

Quality program Q7.6. Every test here talks to a recorder started as a
separate interpreter, through the only interface the agent side has. The
three properties of the acceptance criterion are pinned:

1. the recorder is a separate process with append-only storage;
2. the agent process has no way to delete an earlier event through the
   interface it holds, and a deletion made behind the recorder's back is
   detected against the receipt;
3. a high-risk dispatch refuses when a mandatory recorder is down, before
   the nonce is spent.
"""
from __future__ import annotations

import contextlib
import socket
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from remora.audit.recorder import (
    RecorderClient,
    RecorderReceipt,
    RecorderStore,
    RecorderUnavailable,
)
from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = "b1"
ARGS = {"id": "WO-1"}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "recorder-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def recorder(tmp_path):
    """A recorder in its own interpreter. Yields (client, db_path, process)."""
    db = tmp_path / "recorder.db"
    process = subprocess.Popen(
        [sys.executable, "-m", "remora.audit.recorder", "--db", str(db),
         "--listen", "127.0.0.1:0"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    line = process.stdout.readline()
    assert line.startswith("READY "), process.stderr.read()
    try:
        yield RecorderClient(line.split()[1]), db, process
    finally:
        process.terminate()
        process.communicate(timeout=10)


def _free_port_address() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"127.0.0.1:{sock.getsockname()[1]}"


class TestSeparateAppendOnlyProcess:
    def test_appends_return_chained_receipts(self, recorder):
        client, _, process = recorder
        first = client.append("dispatch", {"n": 1})
        second = client.append("dispatch", {"n": 2})
        assert (first.seq, second.seq) == (0, 1)
        assert client.head() == second
        assert process.pid != __import__("os").getpid()

    @pytest.mark.parametrize("op", ["delete", "update", "truncate", "reset", None])
    def test_the_protocol_has_no_way_to_remove_an_event(self, recorder, op):
        client, _, _ = recorder
        client.append("dispatch", {"n": 1})
        with pytest.raises(RecorderUnavailable, match="refused"):
            client._call({"op": op, "seq": 0})
        assert client.head().seq == 0

    def test_the_client_offers_no_destructive_method(self):
        public = {name for name in dir(RecorderClient) if not name.startswith("_")}
        assert public == {"append", "head", "confirm"}

    def test_the_store_refuses_update_and_delete_statements(self, recorder):
        client, db, _ = recorder
        client.append("dispatch", {"n": 1})
        with contextlib.closing(sqlite3.connect(db)) as conn, conn:
            for statement in ("DELETE FROM recorder_events",
                              "UPDATE recorder_events SET event = '{}'"):
                with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                    conn.execute(statement)

    def test_a_receipt_confirms_an_unchanged_event(self, recorder):
        client, _, _ = recorder
        receipt = client.append("dispatch", {"n": 1})
        assert client.confirm(receipt) is True

    def test_a_deletion_behind_the_recorders_back_is_detected(self, recorder):
        """Dropping the triggers needs write access to the file. The receipt
        the dispatcher holds still exposes what was removed."""
        client, db, _ = recorder
        kept = client.append("dispatch", {"n": 1})
        removed = client.append("dispatch", {"n": 2})
        client.append("dispatch", {"n": 3})
        with contextlib.closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("DROP TRIGGER recorder_no_delete")
            conn.execute("DELETE FROM recorder_events WHERE seq = ?", (removed.seq,))
        assert client.confirm(removed) is False
        assert client.confirm(kept) is False, "a broken chain confirms nothing"
        assert RecorderStore(str(db)).verify()

    def test_a_forged_receipt_is_not_confirmed(self, recorder):
        client, _, _ = recorder
        receipt = client.append("dispatch", {"n": 1})
        assert client.confirm(RecorderReceipt(receipt.seq, "0" * 64)) is False


def _lease(tool: str) -> ExecutionLease:
    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-1", tool_name=tool,
        arguments=ARGS, target_environment="prod", policy_bundle_hash=BUNDLE,
        issued_at=datetime.now(UTC).isoformat())


def _dispatcher(client) -> tuple[GovernedToolDispatcher, list]:
    calls: list = []
    dispatcher = GovernedToolDispatcher(BUNDLE)
    for tool in ("wo_delete", "wo_read"):
        dispatcher.register(tool, lambda args, t=tool: calls.append(t) or "ok")
    dispatcher.bind_recorder(client, mandatory_for=lambda tool: tool == "wo_delete")
    return dispatcher, calls


def _run(dispatcher, lease):
    return dispatcher.dispatch(lease, lease.tool_name, ARGS, tenant_id="acme",
                               target_environment="prod", actor_identity="agent-1")


class TestFailClosedDispatch:
    def test_a_mandatory_tool_records_intent_and_outcome(self, recorder):
        client, db, _ = recorder
        dispatcher, calls = _dispatcher(client)
        result = _run(dispatcher, _lease("wo_delete"))
        assert result.executed and calls == ["wo_delete"]
        assert result.recorder_seq == 0
        with contextlib.closing(sqlite3.connect(db)) as conn, conn:
            phases = [row[0] for row in conn.execute(
                "SELECT json_extract(event, '$.phase') FROM recorder_events ORDER BY seq")]
        assert phases == ["intent", "outcome"]

    def test_a_mandatory_tool_refuses_when_the_recorder_is_down(self):
        dispatcher, calls = _dispatcher(RecorderClient(_free_port_address(), timeout=0.5))
        result = _run(dispatcher, _lease("wo_delete"))
        assert (result.executed, result.refusal_reason) == (False, "recorder_unavailable")
        assert calls == []

    def test_the_refusal_leaves_the_nonce_unspent(self, recorder):
        client, _, _ = recorder
        lease = _lease("wo_delete")
        down, _ = _dispatcher(RecorderClient(_free_port_address(), timeout=0.5))
        assert _run(down, lease).refusal_reason == "recorder_unavailable"
        up, calls = _dispatcher(client)
        up._ledger = down._ledger  # same process ledger: the nonce must still be unspent
        assert _run(up, lease).executed and calls == ["wo_delete"]

    def test_a_tool_the_deployment_did_not_name_is_not_blocked(self):
        dispatcher, calls = _dispatcher(RecorderClient(_free_port_address(), timeout=0.5))
        assert _run(dispatcher, _lease("wo_read")).executed and calls == ["wo_read"]

    def test_a_tool_that_raises_is_recorded_as_state_unknown(self, recorder):
        client, db, _ = recorder
        dispatcher = GovernedToolDispatcher(BUNDLE)

        def explode(args):
            raise RuntimeError("downstream")

        dispatcher.register("wo_delete", explode)
        dispatcher.bind_recorder(client, mandatory_for=lambda tool: True)
        with pytest.raises(RuntimeError):
            _run(dispatcher, _lease("wo_delete"))
        with contextlib.closing(sqlite3.connect(db)) as conn, conn:
            outcome = conn.execute(
                "SELECT json_extract(event, '$.outcome') FROM recorder_events "
                "WHERE json_extract(event, '$.phase') = 'outcome'").fetchone()[0]
        assert outcome == "state_unknown"


class TestTheStoreItself:
    def test_an_in_memory_store_is_refused(self):
        with pytest.raises(ValueError, match="in-memory"):
            RecorderStore(":memory:")

    def test_verify_is_clean_on_an_untouched_chain(self, tmp_path):
        store = RecorderStore(str(tmp_path / "r.db"))
        for n in range(5):
            store.append("s", {"n": n})
        assert store.verify() == []


class TestTheProtocolInProcess:
    """The same handler and server the subprocess runs, measured in-process."""

    @pytest.fixture()
    def server(self, tmp_path):
        import threading

        from remora.audit import recorder as module

        tcp = module._TCPServer(("127.0.0.1", 0), module._Handler)
        tcp.store = module.RecorderStore(str(tmp_path / "p.db"))
        thread = threading.Thread(target=tcp.serve_forever, daemon=True)
        thread.start()
        try:
            yield RecorderClient(f"127.0.0.1:{tcp.server_address[1]}"), tcp
        finally:
            tcp.shutdown()
            tcp.server_close()

    def test_round_trip(self, server):
        client, _ = server
        assert client.head() is None
        receipt = client.append("s", {"n": 1})
        assert client.head() == receipt and client.confirm(receipt)

    @pytest.mark.parametrize("request_line", [
        b"[1, 2]\n", b'{"op": "append", "stream": 3, "event": {}}\n',
        b'{"op": "confirm"}\n', b"not json\n"])
    def test_malformed_requests_are_answered_not_crashed(self, server, request_line):
        client, _ = server
        with socket.create_connection(client._address, timeout=2) as sock:
            sock.sendall(request_line)
            with sock.makefile("rb") as reader:
                response = reader.readline()
        assert b'"ok": false' in response
        assert client.append("s", {"still": "alive"}).seq == 0

    def test_an_oversized_request_is_refused(self, server):
        client, _ = server
        from remora.audit import recorder as module

        with socket.create_connection(client._address, timeout=2) as sock:
            sock.sendall(b'{"op": "head", "pad": "' + b"x" * (module._MAX_LINE + 10) + b'"}\n')
            with sock.makefile("rb") as reader:
                assert b"too large" in reader.readline()

    def test_a_malformed_address_is_rejected(self):
        with pytest.raises(ValueError):
            RecorderClient("no-port")

    def test_a_peer_that_is_not_a_recorder_is_unavailable(self):
        import threading

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        def answer():
            conn, _ = listener.accept()
            conn.recv(1024)
            conn.sendall(b"garbage\n")
            conn.close()

        threading.Thread(target=answer, daemon=True).start()
        try:
            with pytest.raises(RecorderUnavailable, match="no valid response"):
                RecorderClient(f"127.0.0.1:{listener.getsockname()[1]}").head()
        finally:
            listener.close()

    def test_an_event_needs_a_stream(self, tmp_path):
        with pytest.raises(ValueError):
            RecorderStore(str(tmp_path / "s.db")).append("", {})

    def test_verify_reports_a_rewritten_event(self, tmp_path):
        db = tmp_path / "v.db"
        store = RecorderStore(str(db))
        store.append("s", {"n": 1})
        with contextlib.closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("DROP TRIGGER recorder_no_update")
            conn.execute("UPDATE recorder_events SET event = '{\"n\":2}'")
        assert store.verify() == ["hash_mismatch_at:0"]
