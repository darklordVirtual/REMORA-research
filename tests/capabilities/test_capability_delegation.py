# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Delegation never widens authority (quality program Q8.5)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remora.capabilities import (
    CapabilityPolicy,
    CapabilityRefusal,
    CapabilityResolver,
    DelegationDenied,
    EffectiveCapabilitySet,
    delegate,
)
from remora.capabilities.delegation import MAX_DELEGATION_TTL_SECONDS
from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
TOOLS = ["database.read", "email.send", "report.generate", "shell.execute"]
POLICY = CapabilityPolicy.from_dict({
    "policy_version": "p1", "registry_version": "r1",
    "registry": {t: ["prod"] for t in TOOLS},
    "principals": {"agent-42": ["report.generate", "database.read", "email.send"]},
    "tasks": {"monthly_report": ["report.generate", "database.read", "email.send"],
              "read_only": ["report.generate", "database.read"]},
    "tenants": {"acme": TOOLS}, "environments": {"prod": TOOLS},
    "constraints": {"email.send": {"allowed_fields": ["to", "subject", "body"],
                                   "conditions": [{"argument": "to", "in": ["ops@acme", "user@acme"]}]}},
})


def _parent(task="monthly_report") -> EffectiveCapabilitySet:
    return CapabilityResolver(POLICY).resolve(principal_id="agent-42", tenant_id="acme",
                                              environment="prod", task_type=task, now=NOW)


def _child(parent=None, **over):
    kwargs = dict(delegatee="report.generate", tools=["email.send"],
                  purpose="deliver_generated_report", now=NOW + timedelta(seconds=1))
    kwargs.update(over)
    return delegate(parent or _parent(), **kwargs)


class TestSubset:
    def test_a_delegation_within_the_parent_is_granted(self):
        parent = _parent()
        child = _child(parent=parent)
        assert child.allowed_tools == ("email.send",)
        assert child.principal_id == "report.generate"
        assert child.parent_digest == parent.digest

    def test_the_confused_deputy_is_refused(self):
        """A read-only task's report tool cannot reach email.send by delegation."""
        with pytest.raises(DelegationDenied, match="outside the parent"):
            _child(parent=_parent("read_only"))

    def test_asking_for_more_than_the_parent_is_refused(self):
        with pytest.raises(DelegationDenied):
            _child(tools=["email.send", "shell.execute"])

    def test_the_denial_carries_the_capability_code(self):
        assert DelegationDenied.code == CapabilityRefusal.DELEGATION_DENIED.value


class TestNarrowing:
    def test_parent_constraints_are_inherited(self):
        assert _child().canonical()["constraints"]["email.send"]["conditions"] == [
            {"in": ["ops@acme", "user@acme"], "argument": "to"}]

    def test_extra_constraints_only_add(self):
        child = _child(extra_constraints={"email.send": {
            "allowed_fields": ["to", "body"],
            "conditions": [{"argument": "to", "eq": "user@acme"}]}})
        rule = child.canonical()["constraints"]["email.send"]
        assert rule["allowed_fields"] == ["body", "to"]
        assert len(rule["conditions"]) == 2

    def test_a_widened_field_list_cannot_add_fields(self):
        child = _child(extra_constraints={"email.send": {"allowed_fields": ["to", "bcc"]}})
        assert child.canonical()["constraints"]["email.send"]["allowed_fields"] == ["to"]

    def test_the_recipient_scope_is_enforced_on_the_nested_call(self):
        child = _child(extra_constraints={"email.send": {
            "conditions": [{"argument": "to", "eq": "user@acme"}]}})
        assert child.check_arguments("email.send", {"to": "user@acme", "body": "r"}) is None
        assert child.check_arguments("email.send", {"to": "ops@acme", "body": "r"}) is (
            CapabilityRefusal.ARGUMENT_MISMATCH)

    def test_constraints_for_an_undelegated_tool_are_refused(self):
        with pytest.raises(DelegationDenied):
            _child(extra_constraints={"shell.execute": {"allowed_fields": []}})


class TestLifetimeAndTransitivity:
    def test_a_delegation_cannot_outlive_its_parent(self):
        late = datetime.fromisoformat(_parent().expires_at) - timedelta(seconds=5)
        child = _child(now=late, ttl_seconds=MAX_DELEGATION_TTL_SECONDS)
        assert child.expires_at == _parent().expires_at

    @pytest.mark.parametrize("ttl", [0, MAX_DELEGATION_TTL_SECONDS + 1])
    def test_the_lifetime_is_capped(self, ttl):
        with pytest.raises(DelegationDenied):
            _child(ttl_seconds=ttl)

    def test_an_expired_parent_cannot_delegate(self):
        with pytest.raises(DelegationDenied, match="not valid now"):
            _child(now=NOW + timedelta(seconds=POLICY.ttl_seconds + 1))

    def test_a_delegated_set_is_not_transitive_by_default(self):
        with pytest.raises(DelegationDenied, match="not transitive"):
            delegate(_child(), delegatee="email.worker", tools=["email.send"],
                     purpose="relay", now=NOW + timedelta(seconds=2))

    def test_a_transitive_delegation_can_be_delegated_once_more(self):
        grandchild = delegate(_child(transitive=True), delegatee="email.worker",
                              tools=["email.send"], purpose="relay",
                              now=NOW + timedelta(seconds=2))
        assert grandchild.delegation_depth == 2 and not grandchild.transitive

    @pytest.mark.parametrize("over", [{"purpose": " "}, {"delegatee": ""}])
    def test_purpose_and_delegatee_are_required(self, over):
        with pytest.raises(DelegationDenied):
            _child(**over)


class TestTheChain:
    def test_the_parent_digest_is_part_of_the_child_digest(self):
        import dataclasses

        child = _child()
        assert dataclasses.replace(child, parent_digest="sha256:" + "0" * 64).digest != child.digest

    def test_a_delegated_set_round_trips(self):
        child = _child()
        assert EffectiveCapabilitySet.from_dict(child.to_dict()) == child

    def test_an_ordinary_set_carries_no_delegation_block(self):
        assert "delegation" not in _parent().canonical()


class TestProperties:
    @settings(max_examples=150, deadline=None)
    @given(first=st.sets(st.sampled_from(TOOLS), min_size=1),
           second=st.sets(st.sampled_from(TOOLS), min_size=1),
           ttl=st.integers(min_value=1, max_value=MAX_DELEGATION_TTL_SECONDS))
    def test_every_link_is_a_subset_and_never_outlives_its_parent(self, first, second, ttl):
        parent = _parent()
        now = NOW + timedelta(seconds=1)
        try:
            child = delegate(parent, delegatee="a", tools=first, purpose="p", now=now,
                             ttl_seconds=ttl, transitive=True)
        except DelegationDenied:
            assert not first <= set(parent.allowed_tools)
            return
        assert set(child.allowed_tools) <= set(parent.allowed_tools)
        assert child.expires_at <= parent.expires_at
        try:
            grandchild = delegate(child, delegatee="b", tools=second, purpose="p", now=now,
                                  ttl_seconds=ttl)
        except DelegationDenied:
            assert not second <= set(child.allowed_tools)
            return
        assert set(grandchild.allowed_tools) <= set(child.allowed_tools) <= set(parent.allowed_tools)
        for tool in grandchild.allowed_tools:
            parent_rule = parent.constraints.get(tool)
            if parent_rule:
                for condition in parent.canonical()["constraints"][tool].get("conditions", []):
                    assert condition in grandchild.canonical()["constraints"][tool]["conditions"]


class TestTheNestedCallIsEnforced:
    @pytest.fixture(autouse=True)
    def _key(self, monkeypatch):
        monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "delegation-key")
        for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                     "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
            monkeypatch.delenv(name, raising=False)

    def _nested(self, child, tool, arguments, actor="report.generate"):
        now = datetime.now(UTC)
        lease = ExecutionLease.issue(
            decision="accept", tenant_id="acme", actor_identity=actor, tool_name=tool,
            arguments=arguments, target_environment="prod", policy_bundle_hash="b1",
            issued_at=now.isoformat(), capability_set=child)
        calls: list = []
        dispatcher = GovernedToolDispatcher("b1")
        dispatcher.register(tool, lambda args: calls.append(args) or "sent")
        result = dispatcher.dispatch(lease, tool, arguments, tenant_id="acme",
                                     target_environment="prod", actor_identity=actor,
                                     capability_set=child)
        return result, calls

    def _live_child(self, **over):
        now = datetime.now(UTC)
        parent = CapabilityResolver(POLICY).resolve(principal_id="agent-42", tenant_id="acme",
                                                    environment="prod", task_type="monthly_report",
                                                    now=now)
        return delegate(parent, delegatee="report.generate", tools=["email.send"],
                        purpose="deliver_generated_report", now=now, **over)

    def test_the_delegated_nested_call_runs(self):
        result, calls = self._nested(self._live_child(), "email.send",
                                     {"to": "user@acme", "subject": "r", "body": "b"})
        assert result.executed and len(calls) == 1

    def test_a_nested_call_outside_the_delegation_is_refused(self):
        result, calls = self._nested(self._live_child(), "database.read", {"q": 1})
        assert result.refusal_reason == "capability_not_allowed" and calls == []

    def test_a_nested_call_outside_the_inherited_scope_is_refused(self):
        result, calls = self._nested(self._live_child(), "email.send",
                                     {"to": "attacker@evil", "body": "b"})
        assert result.refusal_reason == "capability_argument_mismatch" and calls == []

    def test_the_delegation_is_bound_to_its_delegatee(self):
        result, _ = self._nested(self._live_child(), "email.send",
                                 {"to": "user@acme", "body": "b"}, actor="other.tool")
        assert result.refusal_reason == "capability_principal_mismatch"
