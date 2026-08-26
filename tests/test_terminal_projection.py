# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Crash-matrix row 5, for real this time (issues #416 / #421, RMR-CR-001/006).

The external deep review (2026-08-26) showed the previous row-5 test never
injected the crash it named: a process dying after terminal settlement but
before the review-queue outcome and the execution_result chain record left
an absorbing terminal row with no downstream projection and no repair path.

These tests inject that crash and pin the repair: the projection payload
commits WITH the settlement, the idempotent projector rebuilds the queue
outcome and the chain record from it, the chain write is keyed on the
outbox id so it can land at most once, and repeated sweeps converge.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.enforcement.outbox import OutboxState  # noqa: E402

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "proj-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "projection-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    monkeypatch.delenv("REMORA_ASYNC_DISPATCH", raising=False)
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role",
                        lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    return TestClient(api_mod.app, raise_server_exceptions=False)


def _mod():
    import servers.execution_api as exec_mod

    return exec_mod


def _events(tenant: str = "acme") -> list[str]:
    return [e.payload.get("event") for e in _mod()._CHAIN.entries(tenant)]


def _approved_item(client) -> str:
    r = client.post("/v1/execution/assess", json=CALL)
    assert r.status_code == 200, r.text
    item_id = r.json()["review_item_id"]
    assert client.post(
        "/v1/execution/approve", json={"item_id": item_id}
    ).status_code == 200
    return item_id


# ── store-level contract: both adapters, all new primitives ────────────────


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    from remora.enforcement.outbox import (ExecutionOutbox,
                                           SQLiteExecutionOutbox)
    if request.param == "memory":
        return ExecutionOutbox()
    return SQLiteExecutionOutbox(str(tmp_path / "outbox.db"))


def _intent(store):
    return store.record_intent(
        proposal_id="11111111-2222-3333-4444-555555555555",
        tenant_id="acme", item_id="item-1", tool_name="store_artifact",
        tool_call_hash="a" * 64, grant_jti="jti-1", attempt_no=1,
    )


def test_settle_persists_the_projection_payload(store) -> None:
    row = _intent(store)
    store.claim(row.outbox_id, worker_id="w-1")
    settled = store.settle(row.outbox_id, OutboxState.SUCCEEDED,
                           projection_json='{"outcome": "SUCCEEDED"}')
    assert settled.projection_json == '{"outcome": "SUCCEEDED"}'
    assert settled.projected_at is None


def test_unprojected_terminal_lists_exactly_the_owed_rows(store) -> None:
    a, b = _intent(store), store.record_intent(
        proposal_id="21111111-2222-3333-4444-555555555555",
        tenant_id="acme", item_id="item-2", tool_name="store_artifact",
        tool_call_hash="b" * 64, grant_jti="jti-2", attempt_no=1,
    )
    store.claim(a.outbox_id, worker_id="w")
    store.settle(a.outbox_id, OutboxState.SUCCEEDED, projection_json="{}")
    # b stays pending: not terminal, never listed.
    owed = store.unprojected_terminal("acme")
    assert [r.outbox_id for r in owed] == [a.outbox_id]
    marked = store.mark_projected(a.outbox_id)
    assert marked.projected_at is not None
    assert store.unprojected_terminal("acme") == []
    assert b.state is OutboxState.DISPATCH_PENDING


def test_sqlite_migrates_a_pre_416_database(tmp_path) -> None:
    """A database created before the projection columns gains them on
    construction, and old rows read back with None in the new fields."""
    import sqlite3

    from remora.enforcement.outbox import SQLiteExecutionOutbox

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE execution_outbox ("
        "outbox_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, "
        "tenant_id TEXT NOT NULL, item_id TEXT NOT NULL, "
        "idempotency_key TEXT NOT NULL, tool_name TEXT NOT NULL, "
        "tool_call_hash TEXT NOT NULL, grant_jti TEXT NOT NULL, "
        "state TEXT NOT NULL, attempt_no INTEGER NOT NULL, "
        "created_at TEXT NOT NULL, worker_id TEXT, claimed_at TEXT, "
        "settled_at TEXT, detail TEXT, "
        "UNIQUE (tenant_id, idempotency_key));"
        "INSERT INTO execution_outbox VALUES ('ob-legacy','p','acme','i',"
        "'k','t','h','j','SUCCEEDED',1,'2026-08-01T00:00:00+00:00',"
        "NULL,NULL,'2026-08-01T00:01:00+00:00',NULL);")
    conn.commit()
    conn.close()

    store = SQLiteExecutionOutbox(str(db))
    row = store.get("ob-legacy")
    assert row.tool_call_json is None
    assert row.projection_json is None
    assert row.projected_at is None
    # And the store is fully writable post-migration.
    fresh = _intent(store)
    assert fresh.state is OutboxState.DISPATCH_PENDING


def test_mark_projected_refuses_a_non_terminal_row(store) -> None:
    """Projection follows settlement, never precedes it."""
    row = _intent(store)
    with pytest.raises(ValueError, match="terminal"):
        store.mark_projected(row.outbox_id)


def test_projector_marks_legacy_rows_without_inventing_records(store) -> None:
    """A pre-#416 terminal row has no payload: the projector marks it
    projected with nothing replayed — fabricating records would be worse
    than the gap."""
    from types import SimpleNamespace

    from remora.execution.service import project_terminal_intent

    row = _intent(store)
    store.claim(row.outbox_id, worker_id="w")
    store.settle(row.outbox_id, OutboxState.SUCCEEDED)  # no payload
    appended: list = []
    chain = SimpleNamespace(append_once=lambda *a, **k: appended.append(a))
    result = project_terminal_intent(
        store.get(row.outbox_id), tenant="acme",
        transaction=lambda t: (_ for _ in ()).throw(AssertionError("no queue")),
        chain=chain, outbox=lambda: store,
    )
    assert result == {"outbox_id": row.outbox_id, "replayed": False,
                      "reason": "no_projection_payload"}
    assert appended == []
    assert store.get(row.outbox_id).projected_at is not None


def test_projector_converges_when_the_queue_item_is_gone(store) -> None:
    """The queue replay raising KeyError (item gone / already terminal)
    must not stop the chain record from landing."""
    import json as _json
    from types import SimpleNamespace

    from remora.execution.service import project_terminal_intent

    row = _intent(store)
    store.claim(row.outbox_id, worker_id="w")
    store.settle(row.outbox_id, OutboxState.REFUSED, projection_json=_json.dumps({
        "proposal_id": "p", "item_id": "gone", "actor": "a",
        "tool_call_hash": "h", "grant_jti": "", "outcome": "REFUSED",
        "tool_executed": False, "state_unknown": False,
        "refusal_reason": "payload_invalid", "intent_sequence_no": None,
        "result_sha256": "d" * 64, "result_size_bytes": 12,
        "result_truncated": False,
    }))

    class _Q:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def record_execution_outcome(self, *a, **k):
            raise KeyError("gone")

    appended: list = []
    chain = SimpleNamespace(
        append_once=lambda t, key, payload: appended.append((key, payload)) or
        SimpleNamespace(sequence_no=1, entry_hash="e"))
    result = project_terminal_intent(
        store.get(row.outbox_id), tenant="acme",
        transaction=lambda t: _Q(), chain=chain, outbox=lambda: store,
    )
    assert result["queue_outcome_written"] is False
    assert result["chain_record_written"] is True
    key, payload = appended[0]
    assert key == f"execution-result:{row.outbox_id}"
    assert payload["tool_refusal_reason"] == "payload_invalid"
    assert payload["projection_replayed"] is True
    # Result-envelope identity survives the replay.
    assert payload["result_sha256"] == "d" * 64
    assert payload["result_size_bytes"] == 12
    assert payload["result_truncated"] is False


class _CrashAfterSettle(RuntimeError):
    pass


@pytest.fixture()
def crash_after_settle(client, monkeypatch):
    """The injected crash: settlement commits (WITH its projection payload),
    then the process dies before any downstream write."""
    exec_mod = _mod()
    outbox = exec_mod._outbox()
    real_settle = outbox.settle

    def dying_settle(*args, **kwargs):
        real_settle(*args, **kwargs)
        raise _CrashAfterSettle("process died right after settlement")

    monkeypatch.setattr(outbox, "settle", dying_settle)
    return client


def test_the_crash_leaves_a_terminal_unprojected_row(crash_after_settle) -> None:
    client = crash_after_settle
    item_id = _approved_item(client)
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 500

    exec_mod = _mod()
    (row,) = exec_mod._outbox().unprojected_terminal("acme")
    assert row.state is OutboxState.SUCCEEDED
    assert row.projection_json, "the payload must have committed WITH settlement"
    assert "execution_result" not in _events()


def test_the_projector_rebuilds_queue_outcome_and_chain_record(
    crash_after_settle, monkeypatch
) -> None:
    client = crash_after_settle
    item_id = _approved_item(client)
    assert client.post("/v1/execution/execute",
                       json={"item_id": item_id, "tool_call": CALL}
                       ).status_code == 500
    exec_mod = _mod()
    monkeypatch.undo()  # let the projector's own writes succeed

    results = exec_mod.project_terminal_intents("acme")
    assert len(results) == 1
    assert results[0]["replayed"] is True
    assert results[0]["chain_record_written"] is True

    events = _events()
    assert "execution_result" in events
    replayed = [e.payload for e in exec_mod._CHAIN.entries("acme")
                if e.payload.get("event") == "execution_result"][0]
    assert replayed["projection_replayed"] is True
    assert replayed["grant_jti"], "the projected record carries the grant"
    assert exec_mod._outbox().unprojected_terminal("acme") == []


def test_repeated_projection_sweeps_converge(crash_after_settle, monkeypatch) -> None:
    """Idempotence: after the first repair, further sweeps do nothing, and
    exactly one execution_result exists no matter how many run."""
    client = crash_after_settle
    item_id = _approved_item(client)
    client.post("/v1/execution/execute",
                json={"item_id": item_id, "tool_call": CALL})
    exec_mod = _mod()
    monkeypatch.undo()

    assert len(exec_mod.project_terminal_intents("acme")) == 1
    assert exec_mod.project_terminal_intents("acme") == []
    assert exec_mod.project_terminal_intents("acme") == []
    assert _events().count("execution_result") == 1


def test_the_healthy_path_needs_no_projector(client) -> None:
    """Without a crash the in-line writes finish and mark the row projected;
    the sweep finds nothing, and the in-line chain write already claimed
    the idempotency key the projector would use."""
    item_id = _approved_item(client)
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 200
    assert "audit" in r.json()
    exec_mod = _mod()
    assert exec_mod._outbox().unprojected_terminal("acme") == []
    assert exec_mod.project_terminal_intents("acme") == []
    assert _events().count("execution_result") == 1


def test_reconcile_sweep_runs_the_projector(crash_after_settle, monkeypatch) -> None:
    """The lazy request-path sweep repairs row 5 too — an operator does not
    need to know a separate projector exists."""
    client = crash_after_settle
    item_id = _approved_item(client)
    client.post("/v1/execution/execute",
                json={"item_id": item_id, "tool_call": CALL})
    exec_mod = _mod()
    monkeypatch.undo()

    exec_mod.reconcile_stale_dispatches(
        "acme", now=datetime.now(UTC) + timedelta(days=1))
    assert "execution_result" in _events()
    assert exec_mod._outbox().unprojected_terminal("acme") == []


def test_refused_worker_payload_also_terminalises_the_review_item(
    client, monkeypatch
) -> None:
    """Issue #421 (RMR-CR-006): outbox REFUSED must never coexist with a
    review item stuck AUTHORIZED."""
    monkeypatch.setenv("REMORA_ASYNC_DISPATCH", "1")
    item_id = _approved_item(client)
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 202
    exec_mod = _mod()
    import dataclasses
    (row,) = exec_mod._outbox().pending("acme")
    exec_mod._outbox()._rows[row.outbox_id] = dataclasses.replace(
        row, tool_call_json="{not json")

    results = exec_mod.dispatch_pending_intents("acme", worker_id="w-1")
    assert results[0]["tool_execution"]["refusal_reason"] == "payload_invalid"
    settled = exec_mod._outbox().rows_for_proposal(
        "acme", results[0]["proposal_id"])[0]
    assert settled.state is OutboxState.REFUSED
    assert settled.projected_at is not None
    # The review item carries the same terminal outcome.
    queue = exec_mod._QUEUES["acme"]
    item = queue.item(item_id)
    assert "REFUSED" in str(getattr(item, "status", "")).upper() or \
        "REFUSED" in str(getattr(item, "state", "")).upper()
