# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Capability sets on the execution API (quality program Q8.2).

With ``REMORA_CAPABILITY_POLICY_FILE`` set, the API resolves a fresh set for
the authenticated principal, the tenant, the target environment and the
declared task type, from the deployment's policy and never from the request.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402
from remora.policy.report import DecisionReason  # noqa: E402

READ = {"tool_name": "read_telemetry", "arguments": {"asset": "P-1"},
        "target_environment": "staging", "task_type": "monitoring"}
POLICY = {
    "policy_version": "cap-1", "registry_version": "reg-1",
    "registry": {"read_telemetry": ["staging"], "store_artifact": ["staging"],
                 "update_work_order": ["staging"]},
    "principals": {"agent-1": ["read_telemetry", "store_artifact"],
                   "employee-1": ["update_work_order"]},
    "tasks": {"monitoring": ["read_telemetry"], "maintenance": ["update_work_order"]},
    "tenants": {"acme": ["read_telemetry", "store_artifact", "update_work_order"]},
    "environments": {"staging": ["read_telemetry", "store_artifact", "update_work_order"]},
}


def _mod():
    import servers.execution_api as exec_mod

    return exec_mod


@pytest.fixture()
def client(monkeypatch, tmp_path):
    policy = tmp_path / "capabilities.json"
    policy.write_text(json.dumps(POLICY))
    monkeypatch.setenv("REMORA_CAPABILITY_POLICY_FILE", str(policy))
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "capability-server-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    for name in ("REMORA_SEMANTIC_BUNDLE_MODULE", "REMORA_REQUIRE_CAPABILITY_SET",
                 "REMORA_REQUIRE_TASK_IDENTITY"):
        monkeypatch.delenv(name, raising=False)
    import servers.api as api_mod

    exec_mod = _mod()
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "operator"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "agent-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE)
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_outbox()
    exec_mod._reset_tool_dispatcher()
    yield TestClient(api_mod.app)
    exec_mod._reset_tool_dispatcher()


def _token(call: dict[str, Any]) -> dict[str, Any]:
    from remora.enforcement.token import PolicyDecisionToken
    from remora.execution.service import authorization_context

    exec_mod = _mod()
    obs, semantic = exec_mod._observation_with_context(exec_mod.ToolCallRequest(**call), "acme")
    now = datetime.now(UTC)
    return PolicyDecisionToken.issue(
        action="accept", observation_hash=obs.tool_call_hash or "",
        request_id=f"p-cap-{uuid.uuid4()}", issued_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=300)).isoformat(), audience=exec_mod.PEP_AUDIENCE,
        context=authorization_context(
            tenant="acme", principal="agent-1", semantic=semantic,
            target_environment=call.get("target_environment", "") or "",
            policy_bundle_hash=exec_mod._current_policy_bundle_hash(),
            toolspec_hash=str(exec_mod._resolve_toolspec(
                call["tool_name"], call["arguments"],
                call.get("target_environment", "") or "")["hash"]))).to_dict()


class TestAssess:
    def test_a_tool_in_the_set_is_assessed_normally_with_its_capability_block(self, client):
        body = client.post("/v1/execution/assess", json=READ).json()
        assert body["capability"]["allowed"] is True
        assert body["capability"]["allowed_tools"] == ["read_telemetry"]
        assert DecisionReason.CAPABILITY_NOT_ALLOWED.value not in body["reasons"]

    def test_a_tool_outside_the_set_abstains(self, client):
        call = {**READ, "tool_name": "store_artifact",
                "arguments": {"artifact_id": "x", "content": {}}}
        body = client.post("/v1/execution/assess", json=call).json()
        assert body["decision"] == "abstain"
        assert DecisionReason.CAPABILITY_NOT_ALLOWED.value in body["reasons"]
        assert body["capability"]["refusal"] == "capability_not_allowed"
        assert "execution_token" not in body and "review_item_id" not in body

    def test_no_task_type_means_no_tools(self, client):
        call = {k: v for k, v in READ.items() if k != "task_type"}
        body = client.post("/v1/execution/assess", json=call).json()
        assert body["decision"] == "abstain" and body["capability"]["allowed_tools"] == []

    def test_the_capability_block_is_on_the_chain(self, client):
        client.post("/v1/execution/assess", json=READ)
        record = _mod()._CHAIN.entries("acme")[-1].payload
        assert record["capability"]["capability_digest"].startswith("sha256:")


class TestExecution:
    def test_a_tool_in_the_set_executes(self, client):
        response = client.post("/v1/execution/execute-accepted",
                               json={"execution_token": _token(READ), "tool_call": READ})
        assert response.status_code == 200, response.text
        assert response.json()["tool_execution"]["executed"] is True

    def test_an_injected_call_to_a_hidden_tool_is_refused_before_anything_is_spent(self, client):
        """SDD §26: a document told the agent to call a tool its task never had."""
        call = {**READ, "tool_name": "store_artifact",
                "arguments": {"artifact_id": "exfil", "content": {"all": "data"}}}
        before = len(_mod()._CHAIN.entries("acme"))
        response = client.post("/v1/execution/execute-accepted",
                               json={"execution_token": _token(call), "tool_call": call})
        assert (response.status_code, response.json()["detail"]) == (409, "capability_not_allowed")
        assert len(_mod()._CHAIN.entries("acme")) == before

    def test_the_required_flag_makes_every_lease_carry_a_set(self, client, monkeypatch):
        monkeypatch.setenv("REMORA_REQUIRE_CAPABILITY_SET", "1")
        _mod()._reset_tool_dispatcher()
        response = client.post("/v1/execution/execute-accepted",
                               json={"execution_token": _token(READ), "tool_call": READ})
        assert response.json()["tool_execution"]["executed"] is True


@pytest.fixture()
def executor(monkeypatch, tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from _security_extra import require_security_extra

    require_security_extra()
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from remora.enforcement import lease_signing as signing

    policy = tmp_path / "capabilities.json"
    policy.write_text(json.dumps(POLICY))
    key = ed25519.Ed25519PrivateKey.generate()
    monkeypatch.setenv("REMORA_CAPABILITY_POLICY_FILE", str(policy))
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "tests.dispatcher_registry_fixture")
    monkeypatch.delenv(signing.ENV_HMAC, raising=False)
    monkeypatch.delenv(signing.ENV_HMAC_FALLBACK, raising=False)
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, key.public_key().public_bytes_raw().hex())
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, key.private_bytes_raw().hex())
    import servers.api as api_mod
    from tests import dispatcher_registry_fixture as registry

    exec_mod = _mod()
    registry.CALLS.clear()
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_tool_dispatcher()
    yield SimpleNamespace(client=TestClient(api_mod.app), registry=registry,
                          bundle=exec_mod._current_policy_bundle_hash(),
                          monkeypatch=monkeypatch, signing=signing)
    exec_mod._reset_tool_dispatcher()


LEASED = {"tool_name": "update_work_order",
          "arguments": {"work_order_id": "WO-1", "status": "closed"},
          "target_environment": "staging", "task_type": "maintenance"}


def _leased(executor, *, present):
    from remora.capabilities import CapabilityPolicy, CapabilityResolver
    from remora.execution.dispatch import issue_execution_lease

    capability_set = CapabilityResolver(CapabilityPolicy.from_dict(POLICY)).resolve(
        principal_id="employee-1", tenant_id="acme", environment="staging",
        task_type="maintenance", now=datetime.now(UTC))
    lease = issue_execution_lease(
        tenant="acme", principal="employee-1", tool_call=SimpleNamespace(**LEASED),
        semantic={"tool_contract_bundle_hash": "", "intent_authority_hash": ""},
        now=datetime.now(UTC), policy_bundle_hash=executor.bundle, capability_set=capability_set)
    executor.monkeypatch.delenv(executor.signing.ENV_ED25519_PRIVATE, raising=False)
    body: dict[str, Any] = {"lease": lease.to_dict(), "tool_call": LEASED, "tenant_id": "acme"}
    if present == "set":
        body["capability_set"] = capability_set.to_dict()
    elif present == "widened":
        widened = capability_set.to_dict()
        widened["allowed_tools"] = sorted(widened["allowed_tools"] + ["read_telemetry"])
        body["capability_set"] = widened
    return executor.client.post("/v1/execution/dispatch-leased", json=body)


class TestTheExecutor:
    def test_the_lease_with_its_set_executes(self, executor):
        assert _leased(executor, present="set").json()["tool_execution"]["executed"] is True

    def test_the_lease_without_its_set_is_refused(self, executor):
        result = _leased(executor, present=None).json()["tool_execution"]
        assert result["refusal_reason"] == "capability_set_required"
        assert executor.registry.CALLS == []

    def test_a_widened_set_is_refused_before_dispatch(self, executor):
        response = _leased(executor, present="widened")
        assert response.status_code == 409
        assert "capability_digest_mismatch" in response.json()["detail"]
