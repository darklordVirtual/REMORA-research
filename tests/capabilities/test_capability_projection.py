# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The agent is shown only the tools in its capability set (quality program Q8.3)."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remora.capabilities import CapabilityPolicy, CapabilityProjector, CapabilityResolver

REGISTRY = ["bank.transfer", "invoice.compare", "invoice.pay", "invoice.read",
            "shell.execute", "supplier.read"]
POLICY = CapabilityPolicy.from_dict({
    "policy_version": "p1", "registry_version": "r1",
    "registry": {t: ["prod"] for t in REGISTRY + ["unregistered.tool"]},
    "principals": {"agent-42": REGISTRY + ["unregistered.tool"]},
    "tasks": {"reconcile": ["invoice.read", "invoice.compare", "supplier.read",
                            "unregistered.tool"]},
    "tenants": {"acme": REGISTRY + ["unregistered.tool"]},
    "environments": {"prod": REGISTRY + ["unregistered.tool"]},
})


def _projector(task="reconcile"):
    return CapabilityProjector(CapabilityResolver(POLICY).resolve(
        principal_id="agent-42", tenant_id="acme", environment="prod", task_type=task,
        now=datetime.now(UTC)))


class TestProjection:
    def test_only_tools_in_the_set_and_the_registry_are_exposed(self):
        projection = _projector().project(REGISTRY)
        assert projection.exposed == ("invoice.compare", "invoice.read", "supplier.read")
        assert "unregistered.tool" not in projection.exposed

    def test_the_exposure_ratio_is_exposed_over_registered(self):
        assert _projector().project(REGISTRY).exposure_ratio == pytest.approx(3 / 6)

    def test_an_empty_set_exposes_nothing(self):
        projection = _projector(task="unknown").project(REGISTRY)
        assert projection.exposed == () and projection.exposure_ratio == 0.0

    def test_the_projection_names_the_set_it_came_from(self):
        projector = _projector()
        data = projector.project(REGISTRY).to_dict()
        assert data["capability_digest"] == projector.capability_set.digest

    @settings(max_examples=150, deadline=None)
    @given(registered=st.sets(st.sampled_from(REGISTRY + ["other"])))
    def test_nothing_outside_the_set_is_ever_exposed(self, registered):
        projector = _projector()
        exposed = set(projector.project(registered).exposed)
        assert exposed <= set(projector.capability_set.allowed_tools) & registered


class TestFormats:
    def test_openai_tools_carry_only_allowed_functions(self):
        specs = {name: {"description": name, "parameters": {"type": "object",
                                                             "properties": {"id": {"type": "string"}}}}
                 for name in REGISTRY}
        tools = _projector().for_openai(specs)
        assert [t["function"]["name"] for t in tools] == ["invoice.compare", "invoice.read",
                                                          "supplier.read"]
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["parameters"]["properties"] == {"id": {"type": "string"}}

    def test_a_tool_without_a_schema_gets_no_invented_arguments(self):
        tools = _projector().for_openai({"invoice.read": {"description": "d", "parameters": None}})
        assert tools[0]["function"]["parameters"] == {"type": "object", "properties": {}}

    def test_an_mcp_tools_list_keeps_its_other_keys_and_order(self):
        result = {"tools": [{"name": n, "inputSchema": {}} for n in reversed(REGISTRY)],
                  "nextCursor": "c1"}
        filtered = _projector().for_mcp(result)
        assert [t["name"] for t in filtered["tools"]] == ["supplier.read", "invoice.read",
                                                          "invoice.compare"]
        assert filtered["nextCursor"] == "c1"


class TestTheReferenceRuntime:
    def test_the_offered_list_is_filtered_by_the_set(self, tmp_path):
        from remora.toolcall.surface_evaluation import reference_runtime

        runtime = reference_runtime(tmp_path)[0]
        assert [t["name"] for t in runtime.offered_tools()] == ["write"]
        policy = CapabilityPolicy.from_dict({
            "policy_version": "p", "registry_version": "r", "registry": {"write": ["local-record"]},
            "principals": {"a": ["write"]}, "tasks": {"read_only": []},
            "tenants": {"reference": ["write"]}, "environments": {"local-record": ["write"]}})
        empty = CapabilityResolver(policy).resolve(
            principal_id="a", tenant_id="reference", environment="local-record",
            task_type="read_only", now=datetime.now(UTC))
        assert runtime.offered_tools(capability_set=empty) == []


pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402

API_POLICY = {
    "policy_version": "cap-1", "registry_version": "reg-1",
    "registry": {"read_telemetry": ["staging"], "store_artifact": ["staging"],
                 "delete_production_database": ["staging"]},
    "principals": {"agent-1": ["read_telemetry", "store_artifact"]},
    "tasks": {"monitoring": ["read_telemetry"]},
    "tenants": {"acme": ["read_telemetry", "store_artifact", "delete_production_database"]},
    "environments": {"staging": ["read_telemetry", "store_artifact", "delete_production_database"]},
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    policy = tmp_path / "capabilities.json"
    policy.write_text(json.dumps(API_POLICY))
    monkeypatch.setenv("REMORA_CAPABILITY_POLICY_FILE", str(policy))
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "operator"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "agent-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_tool_dispatcher()
    yield TestClient(api_mod.app)
    exec_mod._reset_tool_dispatcher()


class TestTheEndpoint:
    def _get(self, client, **params):
        return client.get("/v1/execution/capabilities",
                          params={"task_type": "monitoring", "target_environment": "staging",
                                  **params})

    def test_the_agent_is_shown_only_its_task_tools(self, client):
        body = self._get(client).json()
        assert [t["function"]["name"] for t in body["tools"]] == ["read_telemetry"]
        assert body["projection"]["exposed"] == ["read_telemetry"]
        assert body["projection"]["exposure_ratio"] < 0.2
        assert body["capability_set"]["principal_id"] == "agent-1"

    def test_a_dangerous_registered_tool_is_not_shown(self, client):
        names = [t["function"]["name"] for t in self._get(client).json()["tools"]]
        assert "delete_production_database" not in names

    def test_no_task_type_shows_nothing(self, client):
        assert self._get(client, task_type="").json()["tools"] == []

    def test_without_a_policy_the_endpoint_says_so(self, client, monkeypatch):
        monkeypatch.delenv("REMORA_CAPABILITY_POLICY_FILE")
        import servers.execution_api as exec_mod

        exec_mod._reset_tool_dispatcher()
        assert self._get(client).status_code == 404
