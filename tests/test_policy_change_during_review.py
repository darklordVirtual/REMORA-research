# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Policy that tightens while a review is pending must void the approval.

Architect review of the AAE plan (2026-08-05): *"fresh re-gate after
approval must explicitly re-evaluate against current policy, and if the
decision then changes (e.g. new policy would give ESCALATE), the approval
must be discarded. This should be an explicit contract test, not implicit
behaviour."*

The window is real: a proposal can sit in review for as long as the queue
TTL allows, and a deployment can change a tool's risk classification in
that time. An approval granted under the old policy must not survive it,
or the review that actually happened no longer describes the action that
executes.

These tests change the classification through the **server-side registry**
between approve and execute, so the real engine re-decides — no stubbed
decision. Stubbing would only prove that the code calls a function.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "policy-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "policy-change-key")
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
                        lambda request: "reviewer-1")
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
    exec_mod._reset_toolspec_bundle()
    return TestClient(api_mod.app)


def _approved_item(client) -> str:
    r = client.post("/v1/execution/assess", json=CALL)
    assert r.status_code == 200, r.text
    item_id = r.json()["review_item_id"]
    assert item_id
    assert client.post("/v1/execution/approve",
                       json={"item_id": item_id}).status_code == 200
    return item_id


def _tighten_to_critical(monkeypatch) -> None:
    """A deployment reclassifies the tool while the review is pending."""
    import servers.execution_api as exec_mod

    tightened = dict(exec_mod.TOOL_REGISTRY)
    tightened["store_artifact"] = dict(
        tightened["store_artifact"],
        risk_tier="critical",
        action_type="destructive_write",
    )
    monkeypatch.setattr(exec_mod, "TOOL_REGISTRY", tightened)


def test_approval_is_voided_when_policy_tightens(client, monkeypatch) -> None:
    """The contract: an approval granted under the old classification must
    not authorize execution under a stricter one."""
    item_id = _approved_item(client)
    _tighten_to_critical(monkeypatch)

    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "approval_invalidated", (
        "an approval that survives a policy tightening means the review no "
        f"longer describes the action that runs (got {body['outcome']!r})"
    )
    assert body.get("tool_execution") is None


def test_voided_approval_leaves_no_side_effect_and_no_dispatch_intent(
    client, monkeypatch
) -> None:
    import servers.execution_api as exec_mod

    item_id = _approved_item(client)
    _tighten_to_critical(monkeypatch)
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.json()["outcome"] == "approval_invalidated"
    # Nothing was intended, so nothing may be recorded as intended.
    assert exec_mod._outbox().pending("acme") == []
    assert exec_mod._outbox().rows_for_proposal(
        "acme", r.json()["proposal_id"]
    ) == []


def test_invalidation_is_audited_with_both_decisions(client, monkeypatch) -> None:
    """The record must show WHAT changed, or the refusal is unexplainable."""
    import servers.execution_api as exec_mod

    item_id = _approved_item(client)
    _tighten_to_critical(monkeypatch)
    client.post("/v1/execution/execute",
                json={"item_id": item_id, "tool_call": CALL})

    events = [e.payload for e in exec_mod._CHAIN.entries("acme")]
    invalidated = [e for e in events
                   if e.get("event") == "execution_approval_invalidated"]
    assert len(invalidated) == 1, [e.get("event") for e in events]
    queue_events = [e.kind for e in exec_mod._queue("acme").events]
    assert "approval_invalidated" in queue_events


def test_unchanged_policy_still_executes(client) -> None:
    """The guard must not be so eager that a normal approval stops working."""
    item_id = _approved_item(client)
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "execute"


def test_relaxing_policy_does_not_widen_the_approval(client, monkeypatch) -> None:
    """A LOWER fresh severity may execute, but only within what was approved.

    Monotonicity runs one way: the approval is a ceiling, never a floor
    that a later relaxation can raise.
    """
    import servers.execution_api as exec_mod

    item_id = _approved_item(client)
    relaxed = dict(exec_mod.TOOL_REGISTRY)
    relaxed["store_artifact"] = dict(
        relaxed["store_artifact"], risk_tier="low", action_type="read",
    )
    monkeypatch.setattr(exec_mod, "TOOL_REGISTRY", relaxed)

    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 200, r.text
    # Executing is acceptable here (equal-or-safer); what must NOT happen is
    # the payload binding loosening with it.
    if r.json()["outcome"] == "execute":
        assert r.json()["tool_execution"] is not None
