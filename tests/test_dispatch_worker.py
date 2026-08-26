# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Issue #82: the async dispatch boundary and the standalone worker.

With REMORA_ASYNC_DISPATCH the API answers 202 after durable
authorization — queue EXECUTE outcome + dispatch-intent row in one
transaction, no grant minted, no PEP consumed, no side effect — and the
worker performs the dispatch half via
``servers.execution_api.dispatch_pending_intents`` with record shapes
identical to the synchronous path. This suite pins the boundary from both
sides: what the 202 response promises, what the worker does with the row,
and what neither may ever do (dispatch a mutated payload, touch a row
without material, retry a settled outcome).
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.enforcement.outbox import OutboxState  # noqa: E402

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "worker-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "dispatch-worker-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    monkeypatch.setenv("REMORA_ASYNC_DISPATCH", "1")
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


def _exec_mod():
    import servers.execution_api as exec_mod

    return exec_mod


def _chain_events(tenant: str = "acme") -> list[str]:
    chain = _exec_mod()._CHAIN
    return [e.payload.get("event") for e in chain.entries(tenant)]


def _authorized_pending(client) -> tuple[str, object]:
    r = client.post("/v1/execution/assess", json=CALL)
    assert r.status_code == 200, r.text
    item_id = r.json()["review_item_id"]
    assert client.post(
        "/v1/execution/approve", json={"item_id": item_id}
    ).status_code == 200
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["dispatch"] == "pending"
    rows = _exec_mod()._outbox().rows_for_proposal("acme", body["proposal_id"])
    assert len(rows) == 1
    return body["proposal_id"], rows[0]


def test_async_execute_answers_202_after_durable_authorization(client) -> None:
    """The 202 contract: EXECUTE outcome + intent row exist, the payload is
    persisted for the worker, and NOTHING execution-side has happened — no
    grant, no execution_authorized entry, no side effect."""
    _proposal, row = _authorized_pending(client)
    assert row.state is OutboxState.DISPATCH_PENDING
    assert row.tool_call_json, "the worker needs the exact call material"
    events = _chain_events()
    assert "execution_authorized" not in events
    assert "execution_result" not in events


def test_the_worker_dispatches_with_the_synchronous_record_shapes(client) -> None:
    proposal_id, row = _authorized_pending(client)
    exec_mod = _exec_mod()
    results = exec_mod.dispatch_pending_intents("acme", worker_id="w-1")
    assert len(results) == 1
    te = results[0]["tool_execution"]
    assert te["executed"] is True, te

    settled = exec_mod._outbox().rows_for_proposal("acme", proposal_id)[0]
    assert settled.state is OutboxState.SUCCEEDED
    assert settled.worker_id == "w-1"

    events = _chain_events()
    assert "execution_authorized" in events
    assert "execution_result" in events
    # The grant is minted and consumed at the moment of honouring.
    authorized = [e.payload for e in exec_mod._CHAIN.entries("acme")
                  if e.payload.get("event") == "execution_authorized"][0]
    assert authorized["grant_jti"]
    assert authorized["pep_allowed"] is True


def test_a_second_sweep_finds_nothing_to_do(client) -> None:
    _authorized_pending(client)
    exec_mod = _exec_mod()
    assert len(exec_mod.dispatch_pending_intents("acme", worker_id="w-1")) == 1
    assert exec_mod.dispatch_pending_intents("acme", worker_id="w-2") == []


def test_a_mutated_payload_is_refused_never_dispatched(client) -> None:
    """The worker re-hashes the persisted payload against the binding the
    authorization recorded; a row whose material no longer matches settles
    REFUSED without any dispatch."""
    proposal_id, row = _authorized_pending(client)
    exec_mod = _exec_mod()
    # Corrupt the persisted material (simulating storage tamper).
    import dataclasses
    tampered = dataclasses.replace(
        row, tool_call_json='{"tool_name": "store_artifact", '
                            '"arguments": {"artifact_id": "EVIL"}, '
                            '"target_environment": "prod", '
                            '"schema_valid": true}')
    outbox = exec_mod._outbox()
    outbox._rows[row.outbox_id] = tampered  # in-process store, direct swap
    results = exec_mod.dispatch_pending_intents("acme", worker_id="w-1")
    assert len(results) == 1
    assert results[0]["tool_execution"]["executed"] is False
    assert results[0]["tool_execution"]["refusal_reason"] == "payload_hash_mismatch"
    settled = outbox.rows_for_proposal("acme", proposal_id)[0]
    assert settled.state is OutboxState.REFUSED


def test_unparseable_material_is_refused_not_crashed_on(client) -> None:
    """A row whose payload no longer parses settles REFUSED — the worker
    loop must survive it and must never dispatch on a guess."""
    proposal_id, row = _authorized_pending(client)
    exec_mod = _exec_mod()
    import dataclasses
    broken = dataclasses.replace(row, tool_call_json="{not json")
    exec_mod._outbox()._rows[row.outbox_id] = broken
    results = exec_mod.dispatch_pending_intents("acme", worker_id="w-1")
    assert len(results) == 1
    assert results[0]["tool_execution"]["refusal_reason"] == "payload_invalid"
    assert exec_mod._outbox().rows_for_proposal(
        "acme", proposal_id)[0].state is OutboxState.REFUSED


def test_rows_without_material_are_left_to_the_reconciler(client) -> None:
    proposal_id, row = _authorized_pending(client)
    exec_mod = _exec_mod()
    import dataclasses
    stripped = dataclasses.replace(row, tool_call_json=None)
    exec_mod._outbox()._rows[row.outbox_id] = stripped
    assert exec_mod.dispatch_pending_intents("acme", worker_id="w-1") == []
    assert exec_mod._outbox().rows_for_proposal(
        "acme", proposal_id)[0].state is OutboxState.DISPATCH_PENDING


def test_the_synchronous_default_is_unchanged(client, monkeypatch) -> None:
    monkeypatch.delenv("REMORA_ASYNC_DISPATCH", raising=False)
    r = client.post("/v1/execution/assess", json=CALL)
    item_id = r.json()["review_item_id"]
    client.post("/v1/execution/approve", json={"item_id": item_id})
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "dispatch" not in body
    assert body["tool_execution"]["executed"] is True
    row = _exec_mod()._outbox().rows_for_proposal("acme", body["proposal_id"])[0]
    assert row.is_terminal
