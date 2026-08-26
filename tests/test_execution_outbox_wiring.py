# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""FT-02 slice 4: /v1/execution/execute drives the outbox.

The store, its enlistment path and both durable adapters landed in
slices 1-3. This suite pins the wiring: the dispatch intent is recorded
in the SAME transaction that authorizes the call, claimed before the
tool runs, and settled with what actually happened — so a crash between
authorize and outcome leaves a durable row a reconciler can resolve
instead of an unrecorded side effect.

Scope: the synchronous v1 path (maintainer decision 2026-08-05 — execute
stays synchronous with the outbox behind it, and remains the default).
The async boundary and the standalone dispatch worker (issue #82,
REMORA_ASYNC_DISPATCH) are tested in tests/test_dispatch_worker.py.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.enforcement.outbox import OutboxState  # noqa: E402

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "wired-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "outbox-wiring-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
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
    return TestClient(api_mod.app)


def _outbox():
    import servers.execution_api as exec_mod

    return exec_mod._outbox()


def _approved_item(client) -> str:
    r = client.post("/v1/execution/assess", json=CALL)
    assert r.status_code == 200, r.text
    item_id = r.json()["review_item_id"]
    assert item_id, "prod write must route to review in this profile"
    assert client.post(
        "/v1/execution/approve", json={"item_id": item_id}
    ).status_code == 200
    return item_id


def test_execute_records_and_settles_a_dispatch_intent(client) -> None:
    item_id = _approved_item(client)
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 200, r.text
    body = r.json()

    rows = _outbox().rows_for_proposal("acme", body["proposal_id"])
    assert len(rows) == 1, "exactly one dispatch intent per executed proposal"
    row = rows[0]
    assert row.is_terminal, "the synchronous path must not leave a row in flight"
    assert row.proposal_id == body["proposal_id"]
    assert row.item_id == item_id
    assert row.tool_name == "store_artifact"
    assert row.worker_id, "a settled row names who dispatched it"
    executed = (body.get("tool_execution") or {}).get("executed")
    assert (row.state is OutboxState.SUCCEEDED) == bool(executed), (
        "the row's terminal state must agree with what actually happened"
    )


def test_assess_alone_records_no_dispatch_intent(client) -> None:
    """Intent is authorization-scoped: assessing something is not intending
    to dispatch it."""
    r = client.post("/v1/execution/assess", json=CALL)
    assert r.status_code == 200
    assert _outbox().pending("acme") == []


def test_binding_refusal_records_no_dispatch_intent(client) -> None:
    """A re-gate refusal happens before authorization commits — nothing was
    ever intended, so nothing may be recorded as intended."""
    item_id = _approved_item(client)
    mutated = dict(CALL, arguments={"artifact_id": "wired-1",
                                    "content": {"n": 999}})
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": mutated})
    assert r.status_code == 200
    assert r.json()["outcome"] != "execute"
    assert _outbox().pending("acme") == []
    assert _outbox().rows_for_proposal("acme", r.json()["proposal_id"]) == []


def test_repeated_execute_does_not_create_a_second_intent(client) -> None:
    """The one-time grant refuses the replay; the outbox must not grow a
    second intent for the same attempt either."""
    item_id = _approved_item(client)
    first = client.post("/v1/execution/execute",
                        json={"item_id": item_id, "tool_call": CALL})
    assert first.status_code == 200
    proposal_id = first.json()["proposal_id"]
    client.post("/v1/execution/execute",
                json={"item_id": item_id, "tool_call": CALL})
    assert len(_outbox().rows_for_proposal("acme", proposal_id)) == 1


def test_durable_outbox_is_used_when_configured(monkeypatch, tmp_path) -> None:
    """With REMORA_CHAIN_DB set, dispatch intent lands in the durable store
    — the in-process reference is a development fallback, never the
    production record."""
    import servers.execution_api as exec_mod

    from remora.enforcement.outbox import SQLiteExecutionOutbox

    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))
    exec_mod._reset_outbox()
    assert isinstance(exec_mod._outbox(), SQLiteExecutionOutbox)
    exec_mod._reset_outbox()


def test_full_flow_against_a_durable_backend(monkeypatch, tmp_path) -> None:
    """Regression: the whole execute flow must complete with a durable
    outbox configured.

    Building a durable adapter runs DDL on its own connection; doing that
    lazily inside the open authorize transaction deadlocked against
    SQLite's BEGIN EXCLUSIVE write lock until the driver timeout. The
    suite otherwise runs in-process, where no lock exists — so only a test
    that actually configures REMORA_CHAIN_DB can catch it.
    """
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "outbox-durable-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
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
    try:
        durable_client = TestClient(api_mod.app)
        item_id = _approved_item(durable_client)
        r = durable_client.post("/v1/execution/execute",
                                json={"item_id": item_id, "tool_call": CALL})
        assert r.status_code == 200, r.text
        rows = exec_mod._outbox().rows_for_proposal("acme", r.json()["proposal_id"])
        assert len(rows) == 1 and rows[0].is_terminal
    finally:
        monkeypatch.delenv("REMORA_CHAIN_DB", raising=False)
        exec_mod._reset_outbox()
