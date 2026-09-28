# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""EffectiveCapabilitySet and CapabilityResolver (quality program Q8.1)."""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remora.capabilities import (
    CapabilityEpochs,
    CapabilityPolicy,
    CapabilityRefusal,
    CapabilityResolver,
    EffectiveCapabilitySet,
)

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
POLICY = CapabilityPolicy.from_dict({
    "policy_version": "cap-policy-1",
    "registry_version": "registry-7",
    "registry": {
        "invoice.read": ["production", "staging"],
        "invoice.compare": ["production", "staging"],
        "supplier.read": ["production", "staging"],
        "invoice.pay": ["production"],
        "bank.transfer": ["production"],
        "shell.execute": ["staging"],
    },
    "principals": {
        "agent-42": ["invoice.read", "invoice.compare", "supplier.read", "invoice.pay"],
        "payer-1": ["invoice.pay", "invoice.read"],
    },
    "tasks": {
        "invoice_reconciliation": ["invoice.read", "invoice.compare", "supplier.read"],
        "invoice_payment": ["invoice.pay", "invoice.read"],
    },
    "tenants": {"acme": ["invoice.read", "invoice.compare", "supplier.read", "invoice.pay",
                         "bank.transfer"]},
    "environments": {"production": ["invoice.read", "invoice.compare", "supplier.read",
                                    "invoice.pay", "bank.transfer"],
                     "staging": ["invoice.read", "shell.execute"]},
    "denied": ["bank.transfer"],
    "ttl_seconds": 600,
})


def _resolve(**over):
    kwargs = dict(principal_id="agent-42", tenant_id="acme", environment="production",
                  task_type="invoice_reconciliation", now=NOW)
    kwargs.update(over)
    return CapabilityResolver(POLICY).resolve(**kwargs)


class TestResolution:
    def test_the_sdd_example_resolves_to_three_read_tools(self):
        """SDD §2: 'Check invoice 4711' sees read and compare, never pay or transfer."""
        assert _resolve().allowed_tools == ("invoice.compare", "invoice.read", "supplier.read")

    def test_the_task_decides_even_when_the_principal_could_pay(self):
        assert "invoice.pay" not in _resolve().allowed_tools
        assert _resolve(task_type="invoice_payment").allowed_tools == ("invoice.pay", "invoice.read")

    @pytest.mark.parametrize("over", [
        {"principal_id": "stranger"}, {"task_type": "unknown_task"},
        {"tenant_id": "other"}, {"environment": "dev"},
    ])
    def test_anything_the_policy_does_not_name_resolves_to_nothing(self, over):
        assert _resolve(**over).allowed_tools == ()

    def test_the_environment_narrows_through_the_registry(self):
        assert _resolve(environment="staging").allowed_tools == ("invoice.read",)

    def test_the_denylist_wins_over_every_allow(self):
        s = _resolve(task_type="invoice_payment", requested=["bank.transfer", "invoice.pay"])
        assert s.allowed_tools == ("invoice.pay",)
        assert s.denied_tools == ("bank.transfer",)

    def test_a_request_narrows_and_records_what_it_lost(self):
        s = _resolve(requested=["invoice.read", "invoice.pay", "shell.execute"])
        assert s.allowed_tools == ("invoice.read",)
        assert s.denied_tools == ("invoice.pay", "shell.execute")

    def test_the_set_is_bound_and_expires(self):
        s = _resolve()
        assert (s.principal_id, s.tenant_id, s.environment) == ("agent-42", "acme", "production")
        assert s.expires_at == (NOW + timedelta(seconds=600)).isoformat()
        assert (s.policy_version, s.registry_version) == ("cap-policy-1", "registry-7")


TOOLS = st.sets(st.sampled_from(sorted(POLICY.registry) + ["unregistered.tool"]))


class TestProperties:
    @settings(max_examples=200, deadline=None)
    @given(requested=TOOLS)
    def test_the_result_is_inside_every_operand(self, requested):
        s = _resolve(requested=requested)
        allowed = set(s.allowed_tools)
        assert allowed <= requested
        assert allowed <= POLICY.principal_tools["agent-42"]
        assert allowed <= POLICY.task_tools["invoice_reconciliation"]
        assert allowed <= POLICY.tenant_tools["acme"]
        assert allowed <= POLICY.environment_tools["production"]
        assert not allowed & POLICY.denied_tools

    @settings(max_examples=200, deadline=None)
    @given(requested=TOOLS, extra=TOOLS)
    def test_asking_for_more_never_yields_more_than_the_unrequested_resolution(self, requested, extra):
        """An agent cannot enlarge its set through its own request."""
        unrequested = set(_resolve().allowed_tools)
        assert set(_resolve(requested=requested | extra).allowed_tools) <= unrequested

    @settings(max_examples=100, deadline=None)
    @given(requested=TOOLS)
    def test_resolution_is_deterministic_apart_from_the_id(self, requested):
        a, b = _resolve(requested=requested), _resolve(requested=requested)
        assert a.allowed_tools == b.allowed_tools and a.denied_tools == b.denied_tools


class TestTheSet:
    def test_the_digest_covers_every_field(self):
        s = _resolve()
        for name, value in [("allowed_tools", ("invoice.read",)), ("principal_id", "x"),
                            ("tenant_id", "x"), ("environment", "x"), ("task_type", "x"),
                            ("policy_version", "x"), ("registry_version", "x"),
                            ("expires_at", (NOW + timedelta(seconds=1)).isoformat()),
                            ("denied_tools", ("y",)), ("epochs", CapabilityEpochs(policy=1))]:
            assert dataclasses.replace(s, **{name: value}).digest != s.digest, name

    def test_a_round_trip_keeps_the_digest(self):
        s = _resolve()
        assert EffectiveCapabilitySet.from_dict(s.to_dict()) == s

    def test_a_widened_set_with_its_old_digest_is_refused(self):
        data = _resolve().to_dict()
        data["allowed_tools"] = sorted(data["allowed_tools"] + ["invoice.pay"])
        with pytest.raises(ValueError, match="capability_digest_mismatch"):
            EffectiveCapabilitySet.from_dict(data)

    @pytest.mark.parametrize("tools", [("b", "a"), ("a", "a"), ("invoice.*",)])
    def test_an_unsorted_duplicated_or_wildcard_set_is_refused(self, tools):
        with pytest.raises(ValueError):
            dataclasses.replace(_resolve(), allowed_tools=tools)

    def test_a_wildcard_in_the_policy_is_refused(self):
        with pytest.raises(ValueError, match="wildcard"):
            CapabilityPolicy.from_dict({"policy_version": "p", "registry_version": "r",
                                        "principals": {"a": ["*"]}})


class TestCheck:
    def _check(self, tool="invoice.read", **over):
        kwargs = dict(principal_id="agent-42", tenant_id="acme", environment="production",
                      now=NOW + timedelta(seconds=1))
        kwargs.update(over)
        return _resolve().check(tool, **kwargs)

    def test_an_allowed_tool_passes(self):
        assert self._check() is None

    def test_a_tool_outside_the_set_is_not_allowed(self):
        assert self._check("invoice.pay") is CapabilityRefusal.NOT_ALLOWED

    @pytest.mark.parametrize("over,reason", [
        ({"principal_id": "other"}, CapabilityRefusal.PRINCIPAL_MISMATCH),
        ({"tenant_id": "other"}, CapabilityRefusal.TENANT_MISMATCH),
        ({"environment": "staging"}, CapabilityRefusal.ENVIRONMENT_MISMATCH),
        ({"now": NOW + timedelta(seconds=600)}, CapabilityRefusal.EXPIRED),
        ({"now": NOW - timedelta(seconds=1)}, CapabilityRefusal.NOT_YET_VALID),
    ])
    def test_the_binding_refuses_with_its_own_reason(self, over, reason):
        assert self._check(**over) is reason

    def test_a_binding_refusal_outranks_membership(self):
        """A stolen set used elsewhere says so, not 'tool missing'."""
        assert self._check("invoice.pay", tenant_id="other") is CapabilityRefusal.TENANT_MISMATCH

    def test_epochs_report_which_scope_moved(self):
        assert CapabilityEpochs(policy=3).behind(CapabilityEpochs(policy=4, tenant=0)) == ("policy",)
