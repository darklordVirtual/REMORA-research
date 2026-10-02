# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The WS7 pre-dispatch checks on the execution API (Q7.4 to Q7.7).

The library tests prove each check refuses. These prove the API binds them
when a deployment configures them, and leaves the dispatcher unchanged when
it does not: resolved-effect binding from REMORA_EFFECT_REGISTRY_MODULE,
plan premises from REMORA_STATE_REVISION_MODULE, the independent recorder
from REMORA_RECORDER_ADDRESS, procedure contracts from
REMORA_PROCEDURE_MODULE.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.governance.procedure import Step  # noqa: E402
from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402
from tests import ws7_deployment_fixture as deployment  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
READ = {"tool_name": "read_telemetry", "arguments": {"asset": "P-1"},
        "target_environment": "staging"}
PLAN = {"plan_id": "plan-1", "reads": {"asset/P-1": "7", "calendar/today": "12"},
        "depends_on": ["asset/P-1"]}
SETTINGS = ("REMORA_EFFECT_REGISTRY_MODULE", "REMORA_STATE_REVISION_MODULE",
            "REMORA_RECORDER_ADDRESS", "REMORA_RECORDER_MANDATORY_TOOLS",
            "REMORA_PROCEDURE_MODULE", "REMORA_REQUIRE_TASK_IDENTITY")


def _mod():
    import servers.execution_api as exec_mod

    return exec_mod


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "ws7-server-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    for name in SETTINGS:
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
    # A dispatcher cached by an earlier test module (built before this
    # fixture set REMORA_TOOL_REGISTRY_MODULE) would otherwise be reused here
    # and refuse read_telemetry as unknown_tool.
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_outbox()
    deployment.reset()
    test_client = TestClient(api_mod.app)
    yield test_client
    exec_mod._reset_tool_dispatcher()


def _configure(monkeypatch, **env: str) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    _mod()._reset_tool_dispatcher()


def _token(call: dict[str, Any]) -> dict[str, Any]:
    from remora.enforcement.token import PolicyDecisionToken
    from remora.execution.service import authorization_context

    exec_mod = _mod()
    obs, semantic = exec_mod._observation_with_context(exec_mod.ToolCallRequest(**call), "acme")
    now = datetime.now(UTC)
    return PolicyDecisionToken.issue(
        action="accept", observation_hash=obs.tool_call_hash or "",
        request_id=f"p-ws7-{uuid.uuid4()}",
        issued_at=now.isoformat(), expires_at=(now + timedelta(seconds=300)).isoformat(),
        audience=exec_mod.PEP_AUDIENCE,
        context=authorization_context(
            tenant="acme", principal="agent-1", semantic=semantic,
            target_environment=call.get("target_environment", "") or "",
            policy_bundle_hash=exec_mod._current_policy_bundle_hash(),
            toolspec_hash=str(exec_mod._resolve_toolspec(
                call["tool_name"], call["arguments"],
                call.get("target_environment", "") or "")["hash"]),
        )).to_dict()


def _execute(client, call=READ) -> dict[str, Any]:
    response = client.post("/v1/execution/execute-accepted",
                           json={"execution_token": _token(call), "tool_call": call})
    assert response.status_code == 200, response.text
    return response.json()["tool_execution"]


class TestUnconfigured:
    def test_no_setting_leaves_dispatch_unchanged(self, client):
        assert _execute(client)["executed"] is True


class TestResolvedEffect:
    def test_a_known_effect_executes(self, client, monkeypatch):
        _configure(monkeypatch, REMORA_EFFECT_REGISTRY_MODULE="tests.ws7_deployment_fixture")
        assert _execute(client)["executed"] is True

    def test_an_unknown_reference_is_refused_not_guessed(self, client, monkeypatch):
        _configure(monkeypatch, REMORA_EFFECT_REGISTRY_MODULE="tests.ws7_deployment_fixture")
        result = _execute(client, {**READ, "arguments": {"asset": "P-404"}})
        assert (result["executed"], result["refusal_reason"]) == (False, "unresolved_reference")


class TestPlanPremises:
    def test_unchanged_premises_execute(self, client, monkeypatch):
        _configure(monkeypatch, REMORA_STATE_REVISION_MODULE="tests.ws7_deployment_fixture")
        assert _execute(client, {**READ, "plan": PLAN})["executed"] is True

    def test_a_moved_dependency_refuses(self, client, monkeypatch):
        _configure(monkeypatch, REMORA_STATE_REVISION_MODULE="tests.ws7_deployment_fixture")
        deployment.REVISIONS["asset/P-1"] = "8"
        result = _execute(client, {**READ, "plan": PLAN})
        assert (result["executed"], result["refusal_reason"]) == (False, "stale_plan")

    def test_a_moved_irrelevant_read_is_ignored(self, client, monkeypatch):
        _configure(monkeypatch, REMORA_STATE_REVISION_MODULE="tests.ws7_deployment_fixture")
        deployment.REVISIONS["calendar/today"] = "13"
        assert _execute(client, {**READ, "plan": PLAN})["executed"] is True

    def test_a_plan_without_a_revision_source_refuses(self, client):
        result = _execute(client, {**READ, "plan": PLAN})
        assert result["refusal_reason"] == "plan_state_unverifiable"

    def test_a_dependency_the_plan_did_not_read_is_a_422(self, client):
        bad = {**PLAN, "depends_on": ["asset/P-9"]}
        response = client.post("/v1/execution/assess", json={**READ, "plan": bad})
        assert response.status_code == 422


class TestProcedure:
    def test_a_step_that_would_violate_is_refused(self, client, monkeypatch):
        _configure(monkeypatch, REMORA_PROCEDURE_MODULE="tests.ws7_deployment_fixture",
                   REMORA_TOOL_REGISTRY_MODULE="tests.dispatcher_registry_fixture")
        call = {"tool_name": "update_work_order",
                "arguments": {"work_order_id": "WO-1", "status": "closed"},
                "target_environment": "staging"}
        assert _execute(client, call)["refusal_reason"] == "procedure_violation"
        deployment.TRACE.append(Step("read_telemetry"))
        assert _execute(client, call)["executed"] is True


def _free_address() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"127.0.0.1:{sock.getsockname()[1]}"


class TestRecorder:
    def test_a_mandatory_tool_is_recorded_before_it_runs(self, client, monkeypatch, tmp_path):
        process = subprocess.Popen(
            [sys.executable, "-m", "remora.audit.recorder", "--db", str(tmp_path / "r.db")],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            address = process.stdout.readline().split()[1]
            _configure(monkeypatch, REMORA_RECORDER_ADDRESS=address,
                       REMORA_RECORDER_MANDATORY_TOOLS="read_telemetry")
            assert _execute(client)["executed"] is True
            from remora.audit.recorder import RecorderClient

            assert RecorderClient(address).head().seq == 1  # intent, outcome
        finally:
            process.terminate()
            process.communicate(timeout=10)

    def test_a_down_recorder_refuses_a_mandatory_tool(self, client, monkeypatch):
        _configure(monkeypatch, REMORA_RECORDER_ADDRESS=_free_address(),
                   REMORA_RECORDER_MANDATORY_TOOLS="*")
        result = _execute(client)
        assert (result["executed"], result["refusal_reason"]) == (False, "recorder_unavailable")
