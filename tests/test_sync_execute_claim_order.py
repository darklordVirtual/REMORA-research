"""The synchronous /execute path claims the intent BEFORE it consumes a grant.

Issue #417 fixed this ordering for the async worker (dispatch_pending_intent)
but left execute_approved_item consuming the grant and appending
``execution_authorized`` ahead of the exclusive outbox claim. A lost claim then
left a consumed grant and an authorization event in the chain for a dispatch
that never happened. The loser must walk away having consumed and asserted
nothing, exactly as the worker path does.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "sync-claim-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "sync-claim-order-key")
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
    return TestClient(api_mod.app)


def _approved_item(client) -> str:
    r = client.post("/v1/execution/assess", json=CALL)
    assert r.status_code == 200, r.text
    item_id = r.json()["review_item_id"]
    assert client.post(
        "/v1/execution/approve", json={"item_id": item_id}
    ).status_code == 200
    return item_id


def test_a_lost_claim_consumes_no_grant_and_authorizes_nothing(
        client, monkeypatch) -> None:
    import servers.execution_api as exec_mod

    item_id = _approved_item(client)

    consumed: list[str] = []
    real_check = exec_mod._GATE.check

    def spying_check(token, *args, consume=False, **kwargs):
        if consume:
            consumed.append(token.jti)
        return real_check(token, *args, consume=consume, **kwargs)

    monkeypatch.setattr(exec_mod._GATE, "check", spying_check)
    # Another worker holds the intent: every claim this request makes loses.
    monkeypatch.setattr(exec_mod._outbox(), "claim",
                        lambda outbox_id, *, worker_id, now=None: None)

    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tool_execution"]["executed"] is False
    assert body["tool_execution"]["refusal_reason"] == "outbox_claim_lost"

    assert consumed == [], "the loser must not burn a grant"
    events = [e.payload for e in exec_mod._CHAIN.entries("acme")]
    assert not [e for e in events if e.get("event") == "execution_authorized"], (
        "no authorization event for a dispatch this request never performs")
    lost = [e for e in events if e.get("event") == "execution_result"]
    assert len(lost) == 1
    assert lost[0]["tool_refusal_reason"] == "outbox_claim_lost"
    assert lost[0]["grant_jti"] == ""
    assert lost[0]["intent_sequence_no"] is None


def test_the_winner_still_consumes_once_and_dispatches(client, monkeypatch) -> None:
    import servers.execution_api as exec_mod

    item_id = _approved_item(client)
    consumed: list[str] = []
    real_check = exec_mod._GATE.check

    def spying_check(token, *args, consume=False, **kwargs):
        if consume:
            consumed.append(token.jti)
        return real_check(token, *args, consume=consume, **kwargs)

    monkeypatch.setattr(exec_mod._GATE, "check", spying_check)

    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 200, r.text
    assert r.json()["tool_execution"]["executed"] is True
    assert len(consumed) == 1 and consumed[0]
    events = [e.payload.get("event") for e in exec_mod._CHAIN.entries("acme")]
    assert events.count("execution_authorized") == 1
    assert events.count("execution_result") == 1
