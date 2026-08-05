# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""VERIFY carries a machine-readable plan, and a review can be rejected.

AAE §5 requires that a VERIFY answer says what would resolve it, and that
ESCALATE is genuinely distinct from VERIFY rather than a second name for
it. §12 additionally requires ``reject`` alongside ``approve`` — the
lifecycle model already declares ``REVIEW_PENDING → REFUSED on
human_rejection``; only the implementation was missing, so a reviewer
could approve but never record a refusal.

The plan is discriminated by ``type`` because two different resolutions
exist and collapsing them would be the parallel-vocabulary problem in
reverse — one name meaning two things:

- ``human_approval``: a person with a named role must act;
- ``machine_resolution``: a bounded lookup can close the gap
  (``remora.policy.resolution.ResolutionPlan``, already produced by the
  engine and surfaced verbatim rather than re-invented).
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

WRITE_CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "res-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "resolution-key")
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
    return TestClient(api_mod.app)


def _assess(client, call=None):
    r = client.post("/v1/execution/assess", json=call or WRITE_CALL)
    assert r.status_code == 200, r.text
    return r.json()


# ── The plan is present, typed, and actionable ─────────────────────────────

def test_verify_carries_a_human_approval_plan(client) -> None:
    body = _assess(client)
    assert body["decision"] in ("verify", "escalate")
    plan = body["resolution_plan"]
    assert plan is not None, "a VERIFY must say what would resolve it"
    assert plan["type"] == "human_approval"
    assert plan["required_role"], "a plan without a role is not actionable"
    assert plan["expires_at"], "an approval window must be stated"
    assert isinstance(plan["requirements"], list) and plan["requirements"]
    assert plan["resubmit_required"] is False


def test_abstain_has_no_resolution_plan(client) -> None:
    """ABSTAIN means no bounded step is known — promising one would lie."""
    body = _assess(client, {
        "tool_name": "read_telemetry", "arguments": {"asset": "P-1"},
    })
    if body["decision"] != "abstain":
        pytest.skip("profile did not abstain on this call")
    assert body.get("resolution_plan") is None


def test_escalate_requires_a_higher_role_than_verify(client) -> None:
    """ESCALATE must not be a second name for VERIFY (AAE §5)."""
    verify = _assess(client)
    escalate = _assess(client, {
        "tool_name": "delete_production_database",
        "arguments": {"db": "main"},
        "target_environment": "prod",
    })
    if escalate["decision"] != "escalate":
        pytest.skip("profile did not escalate this call")
    v_role = verify["resolution_plan"]["required_role"]
    e_role = escalate["resolution_plan"]["required_role"]
    assert e_role != v_role, (
        "an escalation a normal reviewer can approve is not an escalation"
    )


# ── Rejection is a first-class outcome ─────────────────────────────────────

def test_reject_records_a_refusal_and_blocks_execution(client) -> None:
    item_id = _assess(client)["review_item_id"]
    r = client.post("/v1/execution/reject", json={
        "item_id": item_id, "reason": "target environment is wrong",
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"

    blocked = client.post("/v1/execution/execute", json={
        "item_id": item_id, "tool_call": WRITE_CALL,
    })
    assert blocked.status_code == 409, "a rejected item must never execute"


def test_reject_is_audited_with_the_authenticated_reviewer(client) -> None:
    import servers.execution_api as exec_mod

    item_id = _assess(client)["review_item_id"]
    client.post("/v1/execution/reject", json={
        "item_id": item_id, "reason": "not authorized by the work order",
    })
    events = [e.payload for e in exec_mod._CHAIN.entries("acme")]
    rejected = [e for e in events if e.get("event") == "rejected"]
    assert len(rejected) == 1
    assert rejected[0]["actor"] == "reviewer-1"
    assert rejected[0]["reason"] == "not authorized by the work order"


def test_rejected_item_cannot_then_be_approved(client) -> None:
    """A refusal is terminal; approving around it would erase the review."""
    item_id = _assess(client)["review_item_id"]
    client.post("/v1/execution/reject", json={"item_id": item_id,
                                              "reason": "no"})
    r = client.post("/v1/execution/approve", json={"item_id": item_id})
    assert r.status_code == 409, r.text


def test_reject_requires_a_reason(client) -> None:
    """An unexplained refusal is not reviewable after the fact."""
    item_id = _assess(client)["review_item_id"]
    r = client.post("/v1/execution/reject", json={"item_id": item_id})
    assert r.status_code == 422


# ── SDK surface ────────────────────────────────────────────────────────────

def test_sdk_exposes_resolution_plan_and_reject(client) -> None:
    from remora.sdk import RemoraClient, ResolutionPlan, ToolCall

    sdk = RemoraClient("http://demo", token="t", http_client=client)
    result = sdk.assess(ToolCall(
        tool_name="store_artifact",
        arguments={"artifact_id": "res-1", "content": {"n": 1}},
        target_environment="prod", schema_valid=True,
    ))
    assert isinstance(result.resolution_plan, ResolutionPlan)
    assert result.resolution_plan.type == "human_approval"
    assert result.resolution_plan.required_role

    rejection = sdk.reject(result.review_item_id, reason="wrong target")
    assert rejection.status == "rejected"
