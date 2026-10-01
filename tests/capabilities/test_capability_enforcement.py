# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A tool outside the capability set cannot run (quality program Q8.2).

Library level: the lease signs the capability digest, and the dispatcher
requires the matching set and checks the call against it after the lease
verifies and before the nonce is spent.
"""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from remora.capabilities import CapabilityPolicy, CapabilityResolver, EffectiveCapabilitySet
from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher

POLICY = CapabilityPolicy.from_dict({
    "policy_version": "p1", "registry_version": "r1",
    "registry": {"invoice.read": ["prod"], "invoice.pay": ["prod"], "bank.transfer": ["prod"]},
    "principals": {"agent-42": ["invoice.read", "invoice.pay"]},
    "tasks": {"reconcile": ["invoice.read"], "pay": ["invoice.pay", "invoice.read"]},
    "tenants": {"acme": ["invoice.read", "invoice.pay", "bank.transfer"]},
    "environments": {"prod": ["invoice.read", "invoice.pay", "bank.transfer"]},
})
ARGS = {"invoice": "4711"}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "capability-enforcement-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)


def _set(task="reconcile", now=None) -> EffectiveCapabilitySet:
    return CapabilityResolver(POLICY).resolve(
        principal_id="agent-42", tenant_id="acme", environment="prod", task_type=task,
        now=now or datetime.now(UTC))


def _lease(tool: str, capability_set: EffectiveCapabilitySet | None, actor="agent-42"):
    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity=actor, tool_name=tool,
        arguments=ARGS, target_environment="prod", policy_bundle_hash="b1",
        issued_at=datetime.now(UTC).isoformat(), capability_set=capability_set)


def _dispatch(lease, capability_set, *, require=False, now=None, actor="agent-42"):
    calls: list = []
    dispatcher = GovernedToolDispatcher("b1", require_capability_set=require)
    dispatcher.register(lease.tool_name, lambda args: calls.append(args) or "ok")
    result = dispatcher.dispatch(lease, lease.tool_name, ARGS, tenant_id="acme",
                                 target_environment="prod", actor_identity=actor,
                                 capability_set=capability_set, now=now)
    return result, calls


class TestTheDispatcher:
    def test_a_tool_in_the_set_runs(self):
        s = _set()
        result, calls = _dispatch(_lease("invoice.read", s), s)
        assert result.executed and calls == [ARGS]

    def test_a_tool_outside_the_set_is_refused_and_does_not_run(self):
        s = _set()
        result, calls = _dispatch(_lease("invoice.pay", s), s)
        assert (result.executed, result.refusal_reason) == (False, "capability_not_allowed")
        assert calls == []

    def test_a_lease_that_names_a_set_needs_the_set(self):
        s = _set()
        assert _dispatch(_lease("invoice.read", s), None)[0].refusal_reason == "capability_set_required"

    def test_a_widened_set_does_not_match_the_signed_digest(self):
        s = _set()
        widened = dataclasses.replace(s, allowed_tools=("invoice.pay", "invoice.read"))
        result, calls = _dispatch(_lease("invoice.pay", s), widened)
        assert result.refusal_reason == "capability_digest_mismatch" and calls == []

    def test_an_expired_set_is_refused(self):
        issued = datetime.now(UTC) - timedelta(seconds=POLICY.ttl_seconds + 5)
        s = _set(now=issued)
        lease = _lease("invoice.read", s)
        assert _dispatch(lease, s)[0].refusal_reason == "capability_expired"

    def test_a_set_used_by_another_actor_is_refused(self):
        s = _set()
        lease = _lease("invoice.read", s, actor="agent-7")
        assert _dispatch(lease, s, actor="agent-7")[0].refusal_reason == "capability_principal_mismatch"

    def test_the_required_flag_refuses_a_lease_without_a_set(self):
        assert _dispatch(_lease("invoice.read", None), None, require=True)[0].refusal_reason == (
            "capability_set_required")

    def test_without_the_flag_a_lease_without_a_set_is_unchanged(self):
        assert _dispatch(_lease("invoice.read", None), None)[0].executed

    def test_a_refusal_leaves_the_nonce_unspent(self):
        s = _set()
        lease = _lease("invoice.read", s)
        dispatcher = GovernedToolDispatcher("b1")
        dispatcher.register("invoice.read", lambda args: "ok")
        kwargs = dict(tenant_id="acme", target_environment="prod", actor_identity="agent-42")
        assert not dispatcher.dispatch(lease, "invoice.read", ARGS, capability_set=None,
                                       **kwargs).executed
        assert dispatcher.dispatch(lease, "invoice.read", ARGS, capability_set=s, **kwargs).executed


class TestTheSignedField:
    def test_an_unbound_lease_signs_no_capability_digest(self):
        assert "capability_digest" not in _lease("invoice.read", None)._signed_fields()

    def test_rewriting_the_digest_breaks_the_signature(self):
        data = {**_lease("invoice.read", _set()).to_dict(), "capability_digest": "sha256:" + "0" * 64}
        verdict = ExecutionLease.from_dict(data).verify(
            tool_name="invoice.read", arguments=ARGS, tenant_id="acme",
            target_environment="prod", actor_identity="agent-42")
        assert verdict.reason == "signature_invalid"
