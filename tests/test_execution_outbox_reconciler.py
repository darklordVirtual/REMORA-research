# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""FT-02 slice 5: stale dispatch intents are reconciled, not left in flight.

A row stuck in ``DISPATCHING`` means a worker claimed it and never
reported back — the side effect may or may not have happened. Leaving it
there forever is the failure this closes: the row is settled as
``UNKNOWN`` (never retried, because retrying a call that may already have
taken effect is the one forbidden move) and the reconciliation is
appended to the tenant audit chain, so an undeterminable outcome is
visible rather than silent.

Mechanism: the same lazy-sweep discipline REM-032 uses for review-queue
TTL — every execution-path interaction sweeps first. That is deliberately
NOT a claim that a daemon runs; a deployment wanting wall-clock
reconciliation on an idle tenant still needs to call it on a schedule,
which is what ``reconcile_stale_dispatches`` is for.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.enforcement.outbox import OutboxState  # noqa: E402

READ_CALL = {"tool_name": "read_telemetry", "arguments": {"asset": "P-1"}}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "reconciler-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    monkeypatch.delenv("REMORA_OUTBOX_STALE_SECONDS", raising=False)
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    return TestClient(api_mod.app)


def _mod():
    import servers.execution_api as exec_mod

    return exec_mod


def _stranded_row(claimed_at: datetime, proposal_id: str | None = None):
    """An intent whose worker claimed it and never came back.

    The proposal id is unique per call: ``record_intent`` is idempotent by
    (proposal, call hash, attempt), so a fixed id would hand back an
    already-settled row from a previous test whenever the outbox is a
    durable store shared across the session.
    """
    outbox = _mod()._outbox()
    row = outbox.record_intent(
        proposal_id=proposal_id or f"p-stranded-{uuid.uuid4().hex[:8]}",
        tenant_id="acme", item_id="i-1",
        tool_name="store_artifact", tool_call_hash="c" * 64, grant_jti="j",
    )
    outbox.claim(row.outbox_id, worker_id="dead-worker", now=claimed_at)
    return row


def test_stale_dispatch_is_reconciled_to_unknown(client) -> None:
    row = _stranded_row(datetime.now(UTC) - timedelta(hours=1))
    assert client.post("/v1/execution/assess", json=READ_CALL).status_code == 200
    settled = _mod()._outbox().get(row.outbox_id)
    assert settled.state is OutboxState.UNKNOWN
    assert settled.is_terminal


def test_reconciliation_is_recorded_in_the_audit_chain(client) -> None:
    """An undeterminable outcome must be visible, not silently absorbed."""
    row = _stranded_row(datetime.now(UTC) - timedelta(hours=1),
                        proposal_id="p-audit-visible")
    client.post("/v1/execution/assess", json=READ_CALL)
    events = [e.payload for e in _mod()._CHAIN.entries("acme")]
    reconciled = [e for e in events if e.get("event") == "dispatch_unknown"]
    assert len(reconciled) == 1
    assert reconciled[0]["proposal_id"] == "p-audit-visible"
    assert reconciled[0]["outbox_id"] == row.outbox_id


def test_fresh_dispatch_is_left_alone(client) -> None:
    row = _stranded_row(datetime.now(UTC))
    client.post("/v1/execution/assess", json=READ_CALL)
    assert _mod()._outbox().get(row.outbox_id).state is OutboxState.DISPATCHING


def test_reconciled_row_never_returns_to_pending(client) -> None:
    """UNKNOWN is terminal: the reconciler must never hand the call back
    for another attempt."""
    _stranded_row(datetime.now(UTC) - timedelta(hours=1))
    client.post("/v1/execution/assess", json=READ_CALL)
    assert _mod()._outbox().pending("acme") == []


def test_threshold_is_configurable(client, monkeypatch) -> None:
    monkeypatch.setenv("REMORA_OUTBOX_STALE_SECONDS", "5")
    row = _stranded_row(datetime.now(UTC) - timedelta(seconds=30))
    client.post("/v1/execution/assess", json=READ_CALL)
    assert _mod()._outbox().get(row.outbox_id).state is OutboxState.UNKNOWN


def test_sweep_is_idempotent(client) -> None:
    """A second sweep must not append a second reconciliation event for a
    row already settled."""
    _stranded_row(datetime.now(UTC) - timedelta(hours=1))
    client.post("/v1/execution/assess", json=READ_CALL)
    client.post("/v1/execution/assess", json=READ_CALL)
    events = [e.payload for e in _mod()._CHAIN.entries("acme")]
    assert len([e for e in events if e.get("event") == "dispatch_unknown"]) == 1


def test_reconcile_is_callable_directly_for_scheduled_runs(client) -> None:
    """Lazy sweep covers active tenants; an idle tenant needs a scheduled
    call, so the operation must be reachable on its own."""
    row = _stranded_row(datetime.now(UTC) - timedelta(hours=1))
    settled = _mod().reconcile_stale_dispatches("acme")
    assert [r.outbox_id for r in settled] == [row.outbox_id]
    assert _mod()._outbox().get(row.outbox_id).state is OutboxState.UNKNOWN
