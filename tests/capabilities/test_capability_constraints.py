# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""An allowed tool cannot exceed its argument scope (quality program Q8.4).

The SDD §8 example: ``invoice.pay`` only in NOK, at most 50 000, only to the
invoice's authorised recipient, only for an approved invoice, with the last
two facts read from trusted state and never from the agent.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from remora.capabilities import CapabilityPolicy, CapabilityRefusal, CapabilityResolver  # noqa: E402
from remora.capabilities.constraints import Condition, ToolConstraint, evaluate_constraint  # noqa: E402
from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher  # noqa: E402
from tests import capability_state_fixture as state  # noqa: E402

PAY = {
    "conditions": [
        {"argument": "currency", "eq": "NOK"},
        {"argument": "amount", "lte": 50000},
        {"argument": "recipient", "equals_state": "invoice.authorized_recipient"},
        {"state": "invoice.status", "eq": "APPROVED"},
    ],
}
UPDATE = {"allowed_fields": ["invoice", "note", "internal_reference"]}
RAW_POLICY = {
    "policy_version": "p1", "registry_version": "r1",
    "registry": {"invoice.pay": ["prod"], "invoice.update": ["prod"], "invoice.read": ["prod"]},
    "principals": {"payer-1": ["invoice.pay", "invoice.update", "invoice.read"]},
    "tasks": {"invoice_payment": ["invoice.pay", "invoice.update", "invoice.read"]},
    "tenants": {"acme": ["invoice.pay", "invoice.update", "invoice.read"]},
    "environments": {"prod": ["invoice.pay", "invoice.update", "invoice.read"]},
    "constraints": {"invoice.pay": PAY, "invoice.update": UPDATE},
}
GOOD = {"invoice": "4711", "currency": "NOK", "amount": 43441, "recipient": "supplier-381"}


def _set():
    return CapabilityResolver(CapabilityPolicy.from_dict(RAW_POLICY)).resolve(
        principal_id="payer-1", tenant_id="acme", environment="prod",
        task_type="invoice_payment", now=datetime.now(UTC))


def _check(tool, arguments, reader=state.read):
    return _set().check_arguments(tool, arguments, reader)


class TestLevel2:
    def test_allowed_fields_pass(self):
        assert _check("invoice.update", {"invoice": "4711", "note": "ok"}) is None

    def test_a_field_outside_the_allowed_set_is_refused(self):
        assert _check("invoice.update", {"invoice": "4711", "amount": 1}) is (
            CapabilityRefusal.ARGUMENT_MISMATCH)

    def test_a_tool_without_constraints_is_unconstrained(self):
        assert _check("invoice.read", {"anything": 1}) is None


class TestLevel3:
    def test_the_sdd_payment_passes_within_scope(self):
        assert _check("invoice.pay", GOOD) is None

    @pytest.mark.parametrize("change", [
        {"currency": "EUR"}, {"amount": 50001}, {"amount": "43441"}, {"amount": True},
    ])
    def test_a_literal_bound_is_enforced(self, change):
        assert _check("invoice.pay", {**GOOD, **change}) is CapabilityRefusal.ARGUMENT_MISMATCH

    def test_a_missing_constrained_argument_is_refused(self):
        args = {k: v for k, v in GOOD.items() if k != "amount"}
        assert _check("invoice.pay", args) is CapabilityRefusal.ARGUMENT_MISMATCH

    def test_a_recipient_other_than_the_authorised_one_is_a_scope_violation(self):
        assert _check("invoice.pay", {**GOOD, "recipient": "attacker-1"}) is (
            CapabilityRefusal.SCOPE_VIOLATION)

    def test_an_unapproved_invoice_is_a_scope_violation(self):
        args = {**GOOD, "invoice": "4712", "recipient": "supplier-9"}
        assert _check("invoice.pay", args) is CapabilityRefusal.SCOPE_VIOLATION

    def test_the_agent_cannot_assert_the_state_it_is_checked_against(self):
        """An argument claiming the invoice is approved changes nothing."""
        args = {**GOOD, "invoice": "4712", "recipient": "supplier-9",
                "status": "APPROVED", "invoice.status": "APPROVED"}
        assert _check("invoice.pay", args) is CapabilityRefusal.SCOPE_VIOLATION

    def test_without_a_state_reader_a_state_condition_refuses(self):
        assert _check("invoice.pay", GOOD, reader=None) is CapabilityRefusal.STATE_UNVERIFIABLE

    def test_a_failing_state_reader_refuses(self):
        assert _check("invoice.pay", {**GOOD, "invoice": "9999"}) is (
            CapabilityRefusal.STATE_UNVERIFIABLE)


class TestTheConstraintModel:
    @pytest.mark.parametrize("raw", [
        {"eq": 1}, {"argument": "a", "state": "s", "eq": 1}, {"argument": "a", "lte": "x"},
        {"argument": "a", "in": 3}, {"argument": "a", "eq": 1, "ne": 2}, {"argument": "a", "like": 1},
    ])
    def test_a_malformed_condition_is_refused(self, raw):
        with pytest.raises(ValueError):
            Condition.from_dict(raw)

    def test_a_non_mapping_argument_set_is_refused(self):
        constraint = ToolConstraint.from_dict(UPDATE)
        assert evaluate_constraint(constraint, ["not", "a", "mapping"]) is (
            CapabilityRefusal.ARGUMENT_MISMATCH)

    def test_constraints_enter_the_digest(self):
        with_constraints = _set()
        relaxed = dataclasses.replace(with_constraints,
                                      constraints={"invoice.update": with_constraints.constraints["invoice.update"]})
        assert relaxed.digest != with_constraints.digest

    def test_a_set_without_constraints_keeps_its_pre_q84_canonical_form(self):
        policy = {k: v for k, v in RAW_POLICY.items() if k != "constraints"}
        plain = CapabilityResolver(CapabilityPolicy.from_dict(policy)).resolve(
            principal_id="payer-1", tenant_id="acme", environment="prod",
            task_type="invoice_payment", now=datetime.now(UTC))
        assert "constraints" not in plain.canonical()

    def test_a_relaxed_constraint_with_the_old_digest_is_refused(self):
        data = _set().to_dict()
        data["constraints"]["invoice.pay"]["conditions"] = []
        with pytest.raises(ValueError, match="capability_digest_mismatch"):
            type(_set()).from_dict(data)


class TestTheDispatcher:
    @pytest.fixture(autouse=True)
    def _key(self, monkeypatch):
        monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "constraint-key")
        for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                     "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
            monkeypatch.delenv(name, raising=False)

    def _run(self, arguments, *, reader=state.read, lease_args=None):
        s = _set()
        lease = ExecutionLease.issue(
            decision="accept", tenant_id="acme", actor_identity="payer-1", tool_name="invoice.pay",
            arguments=lease_args or arguments, target_environment="prod",
            policy_bundle_hash="b1", issued_at=datetime.now(UTC).isoformat(), capability_set=s)
        calls: list = []
        dispatcher = GovernedToolDispatcher("b1")
        dispatcher.register("invoice.pay", lambda args: calls.append(args) or "paid")
        if reader is not None:
            dispatcher.bind_capability_state(reader)
        result = dispatcher.dispatch(lease, "invoice.pay", arguments, tenant_id="acme",
                                     target_environment="prod", actor_identity="payer-1",
                                     capability_set=s)
        return result, calls

    def test_an_in_scope_payment_runs(self):
        result, calls = self._run(GOOD)
        assert result.executed and calls == [GOOD]

    def test_an_over_limit_payment_is_refused_and_not_run(self):
        args = {**GOOD, "amount": 73441}
        result, calls = self._run(args)
        assert (result.executed, result.refusal_reason) == (False, "capability_argument_mismatch")
        assert calls == []

    def test_a_dispatcher_without_a_state_reader_refuses(self):
        assert self._run(GOOD, reader=None)[0].refusal_reason == "capability_state_unverifiable"


pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402


def test_assess_abstains_on_an_out_of_scope_argument(monkeypatch, tmp_path):
    api_policy = {
        "policy_version": "p1", "registry_version": "r1",
        "registry": {"store_artifact": ["staging"]},
        "principals": {"agent-1": ["store_artifact"]}, "tasks": {"archive": ["store_artifact"]},
        "tenants": {"acme": ["store_artifact"]}, "environments": {"staging": ["store_artifact"]},
        "constraints": {"store_artifact": {"allowed_fields": ["artifact_id", "content"],
                                           "conditions": [{"argument": "artifact_id",
                                                           "in": ["report-1", "report-2"]}]}},
    }
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(api_policy))
    monkeypatch.setenv("REMORA_CAPABILITY_POLICY_FILE", str(path))
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "operator"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "agent-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_tool_dispatcher()
    client = TestClient(api_mod.app)
    try:
        base = {"tool_name": "store_artifact", "target_environment": "staging",
                "task_type": "archive"}
        inside = client.post("/v1/execution/assess", json={
            **base, "arguments": {"artifact_id": "report-1", "content": {}}}).json()
        outside = client.post("/v1/execution/assess", json={
            **base, "arguments": {"artifact_id": "secrets", "content": {}}}).json()
        assert inside["capability"]["allowed"] is True
        assert outside["decision"] == "abstain"
        assert outside["capability"]["refusal"] == "capability_argument_mismatch"
    finally:
        exec_mod._reset_tool_dispatcher()


@pytest.mark.parametrize("raw", PAY["conditions"] + [{"argument": "a", "in": ["x", "y"]}])
def test_a_condition_round_trips_through_its_canonical_form(raw):
    condition = Condition.from_dict(raw)
    assert Condition.from_dict(condition.canonical()) == condition
