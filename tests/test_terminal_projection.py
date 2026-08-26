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
