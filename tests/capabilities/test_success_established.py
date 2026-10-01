# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Success is established by evidence, not by the executor (quality program Q8.7).

SDD §24: ``SUCCESS_ESTABLISHED := capability ∧ authority ∧ execution ∧ effect``.
The contract ``success_established_v1`` is complete only when the chain holds
an assessment the capability check allowed, the authorization, an execution
that ran, and a verified effect.
"""
from __future__ import annotations

import json

import pytest

from remora.governance.evidence_coverage import (
    SUCCESS_ESTABLISHED,
    EvidenceContract,
    EvidenceItem,
    EvidenceRequirement,
    assess_coverage,
)


def _authentic(kind, payload):
    from remora.governance.evidence_coverage import Authenticity

    return EvidenceItem(kind, payload, ref=kind, authenticity=Authenticity.AUTHENTIC)


class TestNestedFields:
    CONTRACT = EvidenceContract("c", "claim", (EvidenceRequirement("assessed", {"capability.allowed": True}),))

    def test_a_nested_field_is_matched(self):
        item = _authentic("assessed", {"capability": {"allowed": True}})
        assert assess_coverage(self.CONTRACT, [item]).status.value == "COMPLETE"

    @pytest.mark.parametrize("payload", [
        {"capability": {"allowed": False}}, {"capability": None}, {}, {"capability.allowed": True},
    ])
    def test_anything_else_does_not_count(self, payload):
        assert assess_coverage(self.CONTRACT, [_authentic("assessed", payload)]).status.value == (
            "AUTHENTIC_BUT_INCOMPLETE")

    def test_plain_fields_behave_as_before(self):
        contract = EvidenceContract("c", "claim", (EvidenceRequirement("r", {"ok": True}),))
        assert assess_coverage(contract, [_authentic("r", {"ok": True})]).status.value == "COMPLETE"


class TestTheContract:
    FULL = [
        _authentic("assessed", {"capability": {"allowed": True}}),
        _authentic("execution_authorized", {}),
        _authentic("execution_result", {"tool_executed": True}),
        _authentic("effect_verified", {"status": "EFFECT_VERIFIED"}),
    ]

    def test_all_four_layers_establish_success(self):
        assert assess_coverage(SUCCESS_ESTABLISHED, self.FULL).status.value == "COMPLETE"

    @pytest.mark.parametrize("drop", range(4))
    def test_any_missing_layer_leaves_success_unestablished(self, drop):
        items = [item for n, item in enumerate(self.FULL) if n != drop]
        verdict = assess_coverage(SUCCESS_ESTABLISHED, items)
        assert verdict.status.value == "AUTHENTIC_BUT_INCOMPLETE" and len(verdict.missing) == 1

    def test_executor_success_alone_establishes_nothing(self):
        verdict = assess_coverage(SUCCESS_ESTABLISHED, [self.FULL[2]])
        assert len(verdict.missing) == 3


pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.effect_verification import EffectStatus, EffectVerification  # noqa: E402
from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402

CALL = {"tool_name": "store_artifact",
        "arguments": {"artifact_id": "established-1", "content": {"n": 1}},
        "target_environment": "prod", "schema_valid": True, "task_type": "archive"}
POLICY = {"policy_version": "cap-1", "registry_version": "reg-1",
          "registry": {"store_artifact": ["prod"]},
          "principals": {"employee-1": ["store_artifact"]}, "tasks": {"archive": ["store_artifact"]},
          "tenants": {"acme": ["store_artifact"]}, "environments": {"prod": ["store_artifact"]}}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "established-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "established-lease-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    for var in ("REMORA_SEMANTIC_BUNDLE_MODULE", "REMORA_TOOLSPEC_BUNDLE",
                "REMORA_TOOLSPEC_SIGNING_KEY", "REMORA_TOOLSPEC_TRUSTED_IDENTITIES",
                "REMORA_REQUIRE_TASK_IDENTITY", "REMORA_CAPABILITY_POLICY_FILE"):
        monkeypatch.delenv(var, raising=False)
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role", lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    exec_mod._reset_toolspec_bundle()
    yield TestClient(api_mod.app), exec_mod, monkeypatch, tmp_path
    exec_mod._reset_tool_dispatcher()


def _with_policy(exec_mod, monkeypatch, tmp_path):
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(POLICY))
    monkeypatch.setenv("REMORA_CAPABILITY_POLICY_FILE", str(path))
    exec_mod._reset_tool_dispatcher()


def _executed(client) -> str:
    item_id = client.post("/v1/execution/assess", json=CALL).json()["review_item_id"]
    assert client.post("/v1/execution/approve", json={"item_id": item_id}).status_code == 200
    response = client.post("/v1/execution/execute", json={"item_id": item_id, "tool_call": CALL})
    assert response.status_code == 200, response.text
    return str(response.json()["proposal_id"])


def _verify(exec_mod, proposal_id):
    exec_mod.record_effect_verification("acme", EffectVerification.build(
        proposal_id=proposal_id, execution_id="exec-1", tool_id="store_artifact",
        toolspec_hash="d" * 64, status=EffectStatus.VERIFIED, reason_code="postcondition_verified",
        verifier_identity="test.reader/v1", expected={"artifact_id": "established-1"},
        observed={"artifact_id": "established-1"}))


def _bundle(client, proposal_id):
    return client.get(f"/v1/execution/proposals/{proposal_id}/evidence").json()


class TestOnTheExecutionApi:
    def test_capability_authority_execution_and_effect_establish_success(self, client):
        test_client, exec_mod, monkeypatch, tmp_path = client
        _with_policy(exec_mod, monkeypatch, tmp_path)
        proposal_id = _executed(test_client)
        _verify(exec_mod, proposal_id)
        bundle = _bundle(test_client, proposal_id)
        assert bundle["evidence_coverage"]["success_established_v1"]["status"] == "COMPLETE"
        assert bundle["capability_decision"]["latest"]["allowed"] is True
        assert "capability_decision" in bundle["manifest"]["section_sha256"]

    def test_without_the_effect_success_is_not_established(self, client):
        test_client, exec_mod, monkeypatch, tmp_path = client
        _with_policy(exec_mod, monkeypatch, tmp_path)
        coverage = _bundle(test_client, _executed(test_client))["evidence_coverage"]
        assert coverage["success_established_v1"]["missing"] == [
            "effect_verified[status=EFFECT_VERIFIED]"]

    def test_without_a_capability_policy_the_missing_decision_is_named(self, client):
        test_client, exec_mod, _, _ = client
        proposal_id = _executed(test_client)
        _verify(exec_mod, proposal_id)
        bundle = _bundle(test_client, proposal_id)
        verdict = bundle["evidence_coverage"]["success_established_v1"]
        assert verdict["status"] == "AUTHENTIC_BUT_INCOMPLETE"
        assert verdict["missing"] == ["assessed[capability.allowed=True]"]
        assert bundle["capability_decision"] == {"decisions": [], "latest": None}
