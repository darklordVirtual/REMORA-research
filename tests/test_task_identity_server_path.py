# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Task identity and loop safety on the execution API (quality program Q7.2).

The library halves (tests/test_task_bound_lease_and_envelope.py and
tests/test_loop_safety.py) proved the structures refuse. These tests prove
the server path uses them:

* a proposal's ``context_id`` and ``task_id`` enter the ACCEPT token's
  authorization context, so a token redeemed under another task, or with the
  task stripped, is refused as ``context_mismatch`` before the grant is spent;
* ``REMORA_REQUIRE_TASK_IDENTITY`` refuses a call that names no task before
  anything is decided or consumed;
* every assessment that names a task is recorded in the context's loop safety
  state, a context at its limit cannot ACCEPT, and an unreadable store refuses
  the assessment;
* only the reviewer route resets the state, and the reset is on the chain;
* the custody-split executor checks the lease's task against the call.
"""
from __future__ import annotations

import dataclasses
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from remora.governance.loop_safety import (  # noqa: E402
    DurableLoopSafetyStore,
    LoopSafetyMonitor,
)
from remora.governance.task_identity import TaskIdentity  # noqa: E402
from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402
from remora.policy.report import DecisionAction, DecisionReason  # noqa: E402

TASK_A = {"context_id": "ctx-1", "task_id": "task-a"}
TASK_B = {"context_id": "ctx-1", "task_id": "task-b"}
READ_CALL = {"tool_name": "read_telemetry", "arguments": {"asset": "P-1"},
             "target_environment": "staging"}


def _mod():
    import servers.execution_api as exec_mod

    return exec_mod


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "task-server-path-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    monkeypatch.delenv("REMORA_REQUIRE_TASK_IDENTITY", raising=False)
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
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    monkeypatch.setattr(exec_mod, "_LOOP_SAFETY", None)
    return TestClient(api_mod.app)


def _token(call: dict[str, Any], task: TaskIdentity | None) -> dict[str, Any]:
    """An ACCEPT token as the assess branch issues it, under ``task``.

    The research profile refuses probabilistic ACCEPT from /assess, so the
    token is minted with the same issuance and the same context builder.
    """
    from remora.enforcement.token import PolicyDecisionToken
    from remora.execution.service import authorization_context

    exec_mod = _mod()
    request = exec_mod.ToolCallRequest(**call)
    obs, semantic = exec_mod._observation_with_context(request, "acme")
    now = datetime.now(UTC)
    return PolicyDecisionToken.issue(
        action="accept",
        observation_hash=obs.tool_call_hash or "",
        request_id="p-task-1",
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=300)).isoformat(),
        audience=exec_mod.PEP_AUDIENCE,
        context=authorization_context(
            tenant="acme", principal="agent-1", semantic=semantic,
            target_environment=call.get("target_environment", "") or "",
            policy_bundle_hash=exec_mod._current_policy_bundle_hash(),
            toolspec_hash=str(exec_mod._resolve_toolspec(
                call["tool_name"], call["arguments"],
                call.get("target_environment", "") or "")["hash"]),
            task=task,
        ),
    ).to_dict()


def _redeem(client, token, call):
    return client.post("/v1/execution/execute-accepted",
                       json={"execution_token": token, "tool_call": call})


class TestTheTokenCarriesTheTask:
    def test_the_granted_task_redeems(self, client):
        call = {**READ_CALL, **TASK_A}
        response = _redeem(client, _token(call, TaskIdentity(**TASK_A)), call)
        assert response.status_code == 200, response.text
        assert response.json()["tool_execution"]["executed"] is True

    def test_another_task_is_refused_without_spending_the_grant(self, client):
        granted = {**READ_CALL, **TASK_A}
        token = _token(granted, TaskIdentity(**TASK_A))
        refused = _redeem(client, token, {**READ_CALL, **TASK_B})
        assert refused.status_code == 409
        assert refused.json()["detail"] == "context_mismatch"
        assert _redeem(client, token, granted).status_code == 200

    def test_stripping_the_task_is_refused(self, client):
        token = _token({**READ_CALL, **TASK_A}, TaskIdentity(**TASK_A))
        response = _redeem(client, token, READ_CALL)
        assert (response.status_code, response.json()["detail"]) == (409, "context_mismatch")

    def test_a_call_without_a_task_is_unchanged(self, client):
        response = _redeem(client, _token(READ_CALL, None), READ_CALL)
        assert response.status_code == 200, response.text

    @pytest.mark.parametrize("half", [{"context_id": "ctx-1"}, {"task_id": "task-a"}])
    def test_half_an_identity_is_a_422(self, client, half):
        response = client.post("/v1/execution/assess", json={**READ_CALL, **half})
        assert response.status_code == 422


class TestRequiredTaskIdentity:
    @pytest.fixture(autouse=True)
    def _require(self, client, monkeypatch):
        monkeypatch.setenv("REMORA_REQUIRE_TASK_IDENTITY", "1")
        _mod()._reset_tool_dispatcher()

    def test_assess_without_a_task_is_refused_before_deciding(self, client):
        before = len(_mod()._CHAIN.entries("acme"))
        response = client.post("/v1/execution/assess", json=READ_CALL)
        assert response.status_code == 409
        assert response.json()["detail"].startswith("task_identity_required")
        assert len(_mod()._CHAIN.entries("acme")) == before

    def test_assess_with_a_task_proceeds(self, client):
        response = client.post("/v1/execution/assess", json={**READ_CALL, **TASK_A})
        assert response.status_code == 200, response.text

    def test_redemption_without_a_task_is_refused_before_consuming(self, client):
        token = _token(READ_CALL, None)
        response = _redeem(client, token, READ_CALL)
        assert response.status_code == 409
        assert response.json()["detail"].startswith("task_identity_required")


def _force_accept(monkeypatch) -> None:
    """The real engine, with its action forced to ACCEPT.

    Isolates the loop gate: whatever the research profile would decide, the
    only thing that can turn this ACCEPT into ESCALATE is loop state. Patched
    on the instance, because the API reads the engine's flags with vars().
    """
    engine = _mod()._ENGINE
    real = engine.decide
    monkeypatch.setattr(engine, "decide", lambda obs: dataclasses.replace(
        real(obs), action=DecisionAction.ACCEPT))


class TestLoopSafetyAtAssessment:
    def _assess(self, client, task):
        return client.post("/v1/execution/assess", json={**READ_CALL, **task})

    def test_every_assessment_with_a_task_is_recorded(self, client):
        self._assess(client, TASK_A)
        self._assess(client, TASK_B)
        state = client.get("/v1/execution/loop-safety/ctx-1").json()
        assert state["events_since_reset"] == 2
        assert state["tasks"] == ["task-a", "task-b"]

    def test_a_context_at_its_limit_cannot_accept(self, client, monkeypatch):
        exec_mod = _mod()
        _force_accept(monkeypatch)
        assert self._assess(client, TASK_A).json()["decision"] == "accept"
        monitor = exec_mod._loop_safety_monitor()
        for n in range(3):
            monitor.observe("acme", TaskIdentity("ctx-1", f"probe-{n}"), "grant_role",
                            denied=True)
        body = self._assess(client, TASK_B).json()
        assert body["decision"] == "escalate"
        assert DecisionReason.LOOP_SAFETY_ESCALATE.value in body["reasons"]
        assert "execution_token" not in body
        assert body["review_item_id"]
        assert body["loop_safety"]["escalated_by_loop_state"] is True

    def test_another_context_is_not_affected(self, client, monkeypatch):
        exec_mod = _mod()
        _force_accept(monkeypatch)
        monitor = exec_mod._loop_safety_monitor()
        for n in range(3):
            monitor.observe("acme", TaskIdentity("ctx-1", f"probe-{n}"), "x", denied=True)
        body = self._assess(client, {"context_id": "ctx-2", "task_id": "t"}).json()
        assert body["decision"] == "accept"

    def test_an_unreadable_store_refuses_and_records_nothing(self, client, monkeypatch, tmp_path):
        exec_mod = _mod()
        monkeypatch.setattr(exec_mod, "_LOOP_SAFETY", LoopSafetyMonitor(
            DurableLoopSafetyStore(db_path=str(tmp_path))))  # a directory
        before = len(exec_mod._CHAIN.entries("acme"))
        response = self._assess(client, TASK_A)
        assert response.status_code == 503
        assert len(exec_mod._CHAIN.entries("acme")) == before

    def test_a_call_without_a_task_is_not_recorded(self, client):
        client.post("/v1/execution/assess", json=READ_CALL)
        assert "loop_safety" not in client.post(
            "/v1/execution/assess", json=READ_CALL).json()


class TestReset:
    def test_a_reset_names_a_policy_decision_and_is_chained(self, client):
        monitor = _mod()._loop_safety_monitor()
        for n in range(3):
            monitor.observe("acme", TaskIdentity("ctx-1", f"t{n}"), "x", denied=True)
        assert client.get("/v1/execution/loop-safety/ctx-1").json()["action"] == "escalate"
        response = client.post("/v1/execution/loop-safety/reset", json={
            "context_id": "ctx-1", "policy_ref": "review-17", "reason": "false alarm"})
        assert response.status_code == 200, response.text
        assert client.get("/v1/execution/loop-safety/ctx-1").json()["action"] == "continue"
        last = _mod()._CHAIN.entries("acme")[-1].payload
        assert (last["event"], last["policy_ref"], last["reset_by"]) == (
            "loop_safety_reset", "review-17", "agent-1")

    @pytest.mark.parametrize("missing", ["policy_ref", "reason"])
    def test_an_unexplained_reset_is_a_422(self, client, missing):
        body = {"context_id": "ctx-1", "policy_ref": "review-17", "reason": "r"}
        body.pop(missing)
        assert client.post("/v1/execution/loop-safety/reset", json=body).status_code == 422


# ── the custody split: the executor checks the lease's task ─────────────────

LEASED_CALL = {"tool_name": "update_work_order",
               "arguments": {"work_order_id": "WO-1", "status": "closed"},
               "target_environment": "staging"}


@pytest.fixture()
def executor(monkeypatch):
    from _security_extra import require_security_extra

    require_security_extra()
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from remora.enforcement import lease_signing as signing

    key = ed25519.Ed25519PrivateKey.generate()
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "tests.dispatcher_registry_fixture")
    monkeypatch.delenv("REMORA_REQUIRE_TASK_IDENTITY", raising=False)
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
    return SimpleNamespace(client=TestClient(api_mod.app), registry=registry,
                           bundle=exec_mod._current_policy_bundle_hash(),
                           monkeypatch=monkeypatch, signing=signing)


def _leased(executor, lease_task: TaskIdentity | None, call_task: dict[str, str]):
    from remora.execution.dispatch import issue_execution_lease

    lease = issue_execution_lease(
        tenant="acme", principal="employee-1",
        tool_call=SimpleNamespace(**LEASED_CALL),
        semantic={"tool_contract_bundle_hash": "", "intent_authority_hash": ""},
        now=datetime.now(UTC), policy_bundle_hash=executor.bundle,
        task_identity=lease_task,
    )
    executor.monkeypatch.delenv(executor.signing.ENV_ED25519_PRIVATE, raising=False)
    return executor.client.post("/v1/execution/dispatch-leased", json={
        "lease": lease.to_dict(), "tool_call": {**LEASED_CALL, **call_task},
        "tenant_id": "acme"}).json()["tool_execution"]


class TestTheExecutorChecksTheLeaseTask:
    def test_the_granted_task_executes(self, executor):
        assert _leased(executor, TaskIdentity(**TASK_A), TASK_A)["executed"] is True

    def test_another_task_is_refused_and_nothing_runs(self, executor):
        result = _leased(executor, TaskIdentity(**TASK_A), TASK_B)
        assert (result["executed"], result["refusal_reason"]) == (False, "task_mismatch")
        assert executor.registry.CALLS == []

    def test_an_unbound_lease_presented_under_a_task_is_task_unbound(self, executor):
        assert _leased(executor, None, TASK_A)["refusal_reason"] == "task_unbound"
