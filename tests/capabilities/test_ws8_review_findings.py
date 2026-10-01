# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regression tests for the 2026-09-28 WS8 review findings.

Each test fails against the code as it was before the fix.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from remora.capabilities import (
    CapabilityPolicy,
    CapabilityRefusal,
    CapabilityResolver,
    DelegationDenied,
    StaticEpochSource,
    delegate,
    revocation_refusal,
)
from remora.capabilities.delegation import MAX_DELEGATION_DEPTH

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
POLICY = CapabilityPolicy.from_dict({
    "policy_version": "p", "registry_version": "r", "registry": {"email.send": ["prod"]},
    "principals": {"a": ["email.send"]}, "tasks": {"t": ["email.send"]},
    "tenants": {"acme": ["email.send"]}, "environments": {"prod": ["email.send"]},
    "constraints": {"email.send": {"allowed_fields": ["to"],
                                   "conditions": [{"argument": "to", "in": ["x@acme"]}]}},
})


def _root():
    return CapabilityResolver(POLICY).resolve(principal_id="a", tenant_id="acme",
                                              environment="prod", task_type="t", now=NOW)


def _chain(depth: int):
    sets = [_root()]
    for n in range(depth):
        sets.append(delegate(sets[-1], delegatee=f"hop-{n}", tools=["email.send"],
                             purpose="relay", now=NOW + timedelta(seconds=1), transitive=True))
    return sets


class TestRemoteDispatchForwardsEverythingTheLeaseBinds:
    """Finding: the custody-split hop sent only tool, arguments and target."""

    def test_task_plan_and_capability_set_travel_with_the_lease(self, monkeypatch):
        from remora.execution import remote_dispatch as module
        from remora.governance.plan_binding import PlanBinding

        sent: dict = {}
        monkeypatch.setenv(module.ENDPOINT_ENV, "https://executor.internal")
        monkeypatch.setattr(module, "_post", lambda url, payload, timeout: sent.update(payload)
                            or {"tool_execution": {"executed": True}})
        capability_set = _root()
        plan = PlanBinding("plan-1", (("wo/1", "7"),), ("wo/1",))
        call = SimpleNamespace(tool_name="email.send", arguments={"to": "x@acme"},
                               target_environment="prod", context_id="ctx-1", task_id="task-1",
                               task_type="t")
        module.remote_dispatch(lease=SimpleNamespace(to_dict=lambda: {"lease": 1}), tenant="acme",
                               principal="a", tool_call=call, capability_set=capability_set,
                               plan=plan)
        assert (sent["tool_call"]["context_id"], sent["tool_call"]["task_id"]) == ("ctx-1", "task-1")
        assert sent["tool_call"]["task_type"] == "t"
        assert sent["tool_call"]["plan"] == {"plan_id": "plan-1", "reads": {"wo/1": "7"},
                                             "depends_on": ["wo/1"]}
        assert sent["capability_set"]["digest"] == capability_set.digest

    def test_a_call_without_them_sends_exactly_what_it_sent_before(self, monkeypatch):
        from remora.execution import remote_dispatch as module

        sent: dict = {}
        monkeypatch.setenv(module.ENDPOINT_ENV, "https://executor.internal")
        monkeypatch.setattr(module, "_post", lambda url, payload, timeout: sent.update(payload)
                            or {"tool_execution": {"executed": True}})
        call = SimpleNamespace(tool_name="x", arguments={}, target_environment="prod")
        module.remote_dispatch(lease=SimpleNamespace(to_dict=lambda: {}), tenant="acme",
                               principal="a", tool_call=call)
        assert sent == {"lease": {}, "tenant_id": "acme",
                        "tool_call": {"tool_name": "x", "arguments": {}, "target_environment": "prod"}}


class TestDelegationDepthIsCapped:
    """Finding: depth was recorded but never enforced."""

    def test_the_cap_is_reachable(self):
        assert _chain(MAX_DELEGATION_DEPTH)[-1].delegation_depth == MAX_DELEGATION_DEPTH

    def test_one_more_hop_is_refused(self):
        with pytest.raises(DelegationDenied, match="deeper than"):
            _chain(MAX_DELEGATION_DEPTH + 1)


class TestRevokingAParentRevokesItsChildren:
    """Finding: revocation checked only the presented set's own id."""

    def test_revoking_the_root_revokes_a_grandchild(self):
        root, child, grandchild = _chain(2)
        source = StaticEpochSource(revoked_sets=frozenset({root.capability_set_id}))
        assert revocation_refusal(grandchild, source) is CapabilityRefusal.REVOKED
        assert revocation_refusal(child, source) is CapabilityRefusal.REVOKED

    def test_revoking_a_child_does_not_revoke_its_parent(self):
        root, child = _chain(1)
        source = StaticEpochSource(revoked_sets=frozenset({child.capability_set_id}))
        assert revocation_refusal(root, source) is None

    def test_the_ancestors_are_in_the_digest(self):
        import dataclasses

        _, child = _chain(1)
        assert dataclasses.replace(child, ancestor_ids=()).digest != child.digest


class TestRegistryKeysAreChecked:
    """Finding: the wildcard check read environment values, not tool names."""

    def test_a_wildcard_tool_name_in_the_registry_is_refused(self):
        with pytest.raises(ValueError, match="wildcard"):
            CapabilityPolicy.from_dict({"policy_version": "p", "registry_version": "r",
                                        "registry": {"invoice.*": ["prod"]}})


class TestConstraintsAreImmutable:
    """Finding: a frozen dataclass held a mutable dict of constraints."""

    def test_the_constraints_cannot_be_changed_in_place(self):
        s = _root()
        with pytest.raises(TypeError):
            s.constraints["email.send"] = {}  # type: ignore[index]
        with pytest.raises(TypeError):
            s.constraints["email.send"]["conditions"][0]["in"] = ["attacker@evil"]  # type: ignore[index]

    def test_freezing_does_not_change_the_digest_form(self):
        s = _root()
        assert json.loads(json.dumps(s.canonical()))["constraints"]["email.send"] == {
            "allowed_fields": ["to"], "conditions": [{"in": ["x@acme"], "argument": "to"}]}


pytest.importorskip("fastapi")


def test_the_capabilities_route_refuses_by_name_when_epochs_are_unreadable(monkeypatch, tmp_path):
    """Finding: GET /capabilities let an epoch-source failure escape as a 500."""
    from fastapi.testclient import TestClient

    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from tests import capability_epoch_fixture as epochs

    raw = {"policy_version": "p", "registry_version": "r",
           "registry": {"read_telemetry": ["staging"]}, "principals": {"agent-1": ["read_telemetry"]},
           "tasks": {"m": ["read_telemetry"]}, "tenants": {"acme": ["read_telemetry"]},
           "environments": {"staging": ["read_telemetry"]}}
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(raw))
    monkeypatch.setenv("REMORA_CAPABILITY_POLICY_FILE", str(path))
    monkeypatch.setenv("REMORA_CAPABILITY_EPOCH_MODULE", "tests.capability_epoch_fixture")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "operator"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "agent-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    exec_mod._reset_tool_dispatcher()
    epochs.DOWN["down"] = True
    try:
        response = TestClient(api_mod.app).get(
            "/v1/execution/capabilities", params={"task_type": "m", "target_environment": "staging"})
        assert (response.status_code, response.json()["detail"]) == (503, "capability_epoch_unverifiable")
    finally:
        epochs.reset()
        exec_mod._reset_tool_dispatcher()
