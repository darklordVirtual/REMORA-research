# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""NTA-2: authorization of a tool does not authorize the effects its
implementation can reach (phase 1, research profile).

The cases follow docs/design/authority-preserving-capability-mediation-v1.md
section 21. Every refusal asserts that the executor was never called: a refusal
after the effect would be a report, not a guard.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from remora.capabilities import (
    CapabilityPolicy,
    CapabilityRefusal,
    CapabilityResolver,
    DelegationDenied,
    StaticEpochSource,
    delegate,
)
from remora.enforcement.capability_mediator import CapabilityMediator, EffectState
from remora.enforcement.effect_capability import (
    CeilingRefused,
    DownstreamCeiling,
    derive_effect_authority,
)
from remora.enforcement.execution_context import ExecutionContext

TOOLS = ["report.generate", "database.read", "email.send"]
POLICY = CapabilityPolicy.from_dict({
    "policy_version": "p1", "registry_version": "r1",
    "registry": {t: ["prod"] for t in TOOLS},
    "principals": {"agent-42": TOOLS},
    "tasks": {"monthly_report": TOOLS, "no_report": ["database.read"]},
    "tenants": {"acme": TOOLS}, "environments": {"prod": TOOLS},
})

CEILING = DownstreamCeiling.from_dict("report.generate", [
    {"capability": "database.read", "resources": ["database://reporting-eu/*"],
     "purpose": "generate_report"},
    {"capability": "filesystem.read", "resources": ["workspace://reports/*",
                                                     "workspace://templates/report.html"],
     "purpose": "render_report"},
])


def _parent(task="monthly_report", now=None):
    return CapabilityResolver(POLICY).resolve(
        principal_id="agent-42", tenant_id="acme", environment="prod", task_type=task,
        now=now or datetime.now(UTC))


def _open(parent=None, *, ceiling=CEILING, epochs=None, executors=None, calls=None):
    parent = parent or _parent()
    now = datetime.now(UTC)
    authority = derive_effect_authority(parent, tool_name="report.generate",
                                        ceiling=ceiling, now=now)
    context = ExecutionContext.for_dispatch(
        tool_name="report.generate", capability_set=parent, proposal_id="p-1",
        policy_bundle_hash="b1", toolspec_hash="ts-1", lease_digest="lease-1")
    calls = calls if calls is not None else []

    def recording(name):
        return lambda resource, args: calls.append((name, resource, args)) or f"{name}-ok"

    executors = executors if executors is not None else {
        c: recording(c) for c in ("database.read", "filesystem.read", "network.http.post")}
    return CapabilityMediator(context, authority, executors=executors, epochs=epochs), calls


class TestTheCeiling:
    def test_it_parses_and_canonicalises(self):
        cap = CEILING.capability("filesystem.read")
        assert cap.resources == ("workspace://reports/*", "workspace://templates/report.html")

    @pytest.mark.parametrize("entries", [
        [{"capability": "filesystem.read", "resources": [], "purpose": "x"}],
        [{"capability": "filesystem.read", "resources": ["workspace://re*"], "purpose": "x"}],
        [{"capability": "filesystem.read", "resources": ["workspace://a/*"], "purpose": ""}],
        [{"capability": "Filesystem Read", "resources": ["workspace://a/*"], "purpose": "x"}],
        [{"capability": "filesystem.read", "resources": ["workspace://a/*"], "purpose": "x"},
         {"capability": "filesystem.read", "resources": ["workspace://b/*"], "purpose": "y"}],
    ])
    def test_malformed_declarations_are_refused(self, entries):
        with pytest.raises(CeilingRefused):
            DownstreamCeiling.from_dict("report.generate", entries)


class TestDerivation:
    def test_the_authority_is_the_ceiling_under_the_parents_identity(self):
        parent = _parent()
        authority = derive_effect_authority(parent, tool_name="report.generate",
                                            ceiling=CEILING, now=datetime.now(UTC))
        assert authority.allowed_tools == ("database.read", "filesystem.read")
        assert authority.principal_id == "report.generate"
        assert authority.parent_digest == parent.digest
        assert parent.capability_set_id in authority.ancestor_ids
        assert (authority.tenant_id, authority.environment, authority.task_type) == (
            parent.tenant_id, parent.environment, parent.task_type)
        assert authority.expires_at <= parent.expires_at
        assert authority.transitive is False

    def test_a_tool_outside_the_parent_set_derives_nothing(self):
        with pytest.raises(DelegationDenied):
            derive_effect_authority(_parent("no_report"), tool_name="report.generate",
                                    ceiling=CEILING, now=datetime.now(UTC))

    def test_a_ceiling_for_another_tool_is_refused(self):
        with pytest.raises(DelegationDenied):
            derive_effect_authority(_parent(), tool_name="email.send", ceiling=CEILING,
                                    now=datetime.now(UTC))

    def test_policy_can_only_narrow_the_ceiling(self):
        authority = derive_effect_authority(
            _parent(), tool_name="report.generate", ceiling=CEILING, now=datetime.now(UTC),
            policy_allows=["database.read", "network.http.post"])
        assert authority.allowed_tools == ("database.read",)

    def test_an_expired_parent_derives_nothing(self):
        stale = _parent(now=datetime.now(UTC) - timedelta(days=2))
        with pytest.raises(DelegationDenied):
            derive_effect_authority(stale, tool_name="report.generate", ceiling=CEILING,
                                    now=datetime.now(UTC))

    def test_effect_authority_cannot_be_delegated_on(self):
        """Case 7 / NTA-2.5: the chain stops unless a link opted in."""
        authority = derive_effect_authority(_parent(), tool_name="report.generate",
                                            ceiling=CEILING, now=datetime.now(UTC))
        with pytest.raises(DelegationDenied, match="not transitive"):
            delegate(authority, delegatee="helper", tools=["database.read"],
                     purpose="relay", now=datetime.now(UTC))


class TestTheMediator:
    def test_case_6_valid_attenuation_executes_and_is_recorded(self):
        mediator, calls = _open()
        effect = mediator.invoke("filesystem.read", "workspace://reports/september.pdf")
        assert effect.state is EffectState.EXECUTED and effect.result == "filesystem.read-ok"
        assert calls == [("filesystem.read", "workspace://reports/september.pdf", {})]
        assert mediator.records == (effect,)
        assert effect.authority_digest and effect.arguments_hash

    def test_case_1_an_undeclared_effect_is_refused_before_it_runs(self):
        mediator, calls = _open()
        effect = mediator.invoke("network.http.post", "https://billing.example/api/invoice",
                                 {"body": "x"})
        assert effect.refusal == CapabilityRefusal.NOT_ALLOWED.value and calls == []

    def test_case_2_resource_widening_is_refused(self):
        mediator, calls = _open()
        effect = mediator.invoke("filesystem.read", "secrets://production/db-password")
        assert effect.refusal == CapabilityRefusal.RESOURCE_NOT_AUTHORIZED.value and calls == []

    def test_traversal_out_of_the_subtree_is_refused(self):
        mediator, calls = _open()
        effect = mediator.invoke("filesystem.read", "workspace://reports/../secrets/key")
        assert effect.refusal == CapabilityRefusal.RESOURCE_NOT_AUTHORIZED.value and calls == []

    def test_case_3_a_switched_provider_is_a_different_resource(self):
        mediator, calls = _open()
        effect = mediator.invoke("database.read", "database://billing-us/monthly")
        assert effect.refusal == CapabilityRefusal.RESOURCE_NOT_AUTHORIZED.value and calls == []

    @pytest.mark.parametrize("resource", [None, ""])
    def test_case_4_an_unresolved_resource_is_refused(self, resource):
        mediator, calls = _open()
        effect = mediator.invoke("database.read", resource)
        assert effect.refusal == CapabilityRefusal.DEFAULT_UNRESOLVED.value and calls == []

    def test_the_arguments_cannot_carry_a_second_resource(self):
        mediator, calls = _open()
        effect = mediator.invoke("database.read", "database://reporting-eu/monthly",
                                 {"resource": "database://billing-us/monthly"})
        assert effect.refusal == CapabilityRefusal.ARGUMENT_MISMATCH.value and calls == []

    def test_a_closed_execution_mediates_nothing(self):
        mediator, calls = _open()
        mediator.close()
        effect = mediator.invoke("filesystem.read", "workspace://reports/a.pdf")
        assert effect.refusal == CapabilityRefusal.CONTEXT_MISSING.value and calls == []

    def test_revoking_the_parent_set_revokes_its_effect_authority(self):
        parent = _parent()
        mediator, calls = _open(parent, epochs=StaticEpochSource(
            revoked_sets=frozenset({parent.capability_set_id})))
        effect = mediator.invoke("filesystem.read", "workspace://reports/a.pdf")
        assert effect.refusal == CapabilityRefusal.REVOKED.value and calls == []

    def test_an_authority_from_another_execution_is_refused(self):
        other_parent = _parent()
        mediator, calls = _open()
        foreign = derive_effect_authority(other_parent, tool_name="report.generate",
                                          ceiling=CEILING, now=datetime.now(UTC))
        swapped = CapabilityMediator(mediator.context, foreign, executors={
            "filesystem.read": lambda r, a: calls.append(r)})
        effect = swapped.invoke("filesystem.read", "workspace://reports/a.pdf")
        assert effect.refusal == CapabilityRefusal.DIGEST_MISMATCH.value and calls == []

    def test_a_missing_executor_fails_closed(self):
        mediator, calls = _open(executors={})
        effect = mediator.invoke("filesystem.read", "workspace://reports/a.pdf")
        assert effect.refusal == CapabilityRefusal.EXECUTOR_UNAVAILABLE.value

    def test_an_executor_that_raises_leaves_the_effect_unknown(self):
        def boom(resource, args):
            raise ConnectionError("reset")

        mediator, _ = _open(executors={"filesystem.read": boom})
        effect = mediator.invoke("filesystem.read", "workspace://reports/a.pdf")
        assert effect.state is EffectState.UNKNOWN and effect.refusal is None
        assert mediator.records == (effect,)

    def test_the_executor_receives_the_canonical_resource(self):
        mediator, calls = _open()
        mediator.invoke("database.read", "Database://Reporting-EU/monthly")
        assert calls[0][1] == "database://reporting-eu/monthly"

    def test_refusals_are_recorded_too(self):
        mediator, _ = _open()
        mediator.invoke("network.http.post", "https://billing.example/api")
        assert [r.state for r in mediator.records] == [EffectState.REFUSED]


class TestTheContext:
    def test_it_is_immutable(self):
        mediator, _ = _open()
        with pytest.raises(AttributeError):
            mediator.context.tenant_id = "other"  # type: ignore[misc]

    def test_it_carries_the_parent_identity_not_caller_input(self):
        parent = _parent()
        context = ExecutionContext.for_dispatch(
            tool_name="report.generate", capability_set=parent, proposal_id="p",
            policy_bundle_hash="b", toolspec_hash="t", lease_digest="l")
        assert (context.tenant_id, context.principal_id, context.capability_digest) == (
            parent.tenant_id, parent.principal_id, parent.digest)
        assert context.execution_id


class TestDerivationBounds:
    def test_the_depth_cap_applies_to_effect_authority(self):
        from remora.capabilities.delegation import MAX_DELEGATION_DEPTH

        chain = _parent()
        now = datetime.now(UTC)
        for n in range(MAX_DELEGATION_DEPTH):
            chain = delegate(chain, delegatee=f"d{n}", tools=["report.generate"],
                             purpose="relay", now=now, transitive=True)
        with pytest.raises(DelegationDenied, match="deeper"):
            derive_effect_authority(chain, tool_name="report.generate", ceiling=CEILING, now=now)

    @pytest.mark.parametrize("ttl", [0, 301])
    def test_the_lifetime_is_capped(self, ttl):
        with pytest.raises(DelegationDenied, match="ttl"):
            derive_effect_authority(_parent(), tool_name="report.generate", ceiling=CEILING,
                                    now=datetime.now(UTC), ttl_seconds=ttl)
