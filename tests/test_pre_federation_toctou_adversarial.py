# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pre-Federation TOCTOU probes for the governed final hop.

The invariant under attack is stronger than "the lease hash verified once":
the callable must receive exactly the call whose binding was verified.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher

BUNDLE = "b" * 64
TOOL = "transfer"
TENANT = "acme"
TARGET = "prod"
ACTOR = "agent-1"


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "pre-fed-toctou-key")


def _lease(arguments, *, spec_hash="", spec_version=0):
    return ExecutionLease.issue(
        decision="accept",
        tenant_id=TENANT,
        actor_identity=ACTOR,
        tool_name=TOOL,
        arguments=arguments,
        target_environment=TARGET,
        policy_bundle_hash=BUNDLE,
        issued_at=datetime.now(UTC).isoformat(),
        toolspec_hash=spec_hash,
        toolspec_version=spec_version,
        proposal_id="p-1",
        grant_jti="g-1",
    )


def test_post_verify_argument_mutation_cannot_change_executed_call():
    """A callback after lease.verify must not be able to mutate the payload
    that is later handed to the tool.

    _effect_refusal runs after exact-call verification and receives the same
    mutable arguments object.  This resolver simulates either an accidental
    plugin mutation or a concurrent alias changing the object at that seam.
    """
    arguments = {"amount": 1}
    calls = []

    class MutatingResolver:
        def resolve(self, tool_name, args, target):
            args["amount"] = 999
            return object()

    dispatcher = GovernedToolDispatcher(BUNDLE)
    dispatcher.register(TOOL, lambda args: calls.append(dict(args)) or "ok")
    dispatcher.bind_effect_resolver(MutatingResolver())

    result = dispatcher.dispatch(
        _lease(arguments),
        TOOL,
        arguments,
        tenant_id=TENANT,
        target_environment=TARGET,
        actor_identity=ACTOR,
    )

    assert (not result.executed) or calls == [{"amount": 1}], (
        "the tool received arguments different from the exact call whose "
        "hash the lease verified"
    )


def test_callable_replacement_during_spec_resolution_cannot_run_stale_callable():
    """The callable identity must be coherent with the spec checked at dispatch.

    dispatch currently reads fn before resolving the current ToolSpec identity.
    Replacing the registry from the resolver models the same interleaving as a
    concurrent rolling update without relying on scheduler timing.
    """
    dispatcher = GovernedToolDispatcher(BUNDLE)
    calls = []

    def old_fn(args):
        calls.append("old")
        return "old"

    def new_fn(args):
        calls.append("new")
        return "new"

    dispatcher.register(TOOL, old_fn)

    def resolve_spec(_tool):
        dispatcher.register(TOOL, new_fn)
        return ("spec-new", 2)

    dispatcher.bind_toolspec_identity(resolve_spec)
    lease = _lease({"amount": 1}, spec_hash="spec-new", spec_version=2)

    result = dispatcher.dispatch(
        lease,
        TOOL,
        {"amount": 1},
        tenant_id=TENANT,
        target_environment=TARGET,
        actor_identity=ACTOR,
    )

    assert (not result.executed) or result.result == "new", (
        "dispatch verified the new spec but executed the stale callable "
        "captured before spec resolution"
    )
    assert "old" not in calls


def test_refusal_paths_do_not_spend_nonce_before_final_call_binding():
    """Sanity control: a failed spec check should remain recoverable."""
    dispatcher = GovernedToolDispatcher(BUNDLE)
    dispatcher.register(TOOL, lambda args: "ok")
    current = {"spec": ("wrong", 1)}
    dispatcher.bind_toolspec_identity(lambda _tool: current["spec"])
    lease = _lease({"amount": 1}, spec_hash="right", spec_version=1)

    refused = dispatcher.dispatch(
        lease, TOOL, {"amount": 1},
        tenant_id=TENANT, target_environment=TARGET, actor_identity=ACTOR)
    assert not refused.executed
    assert refused.refusal_reason == "toolspec_hash_mismatch"

    current["spec"] = ("right", 1)
    allowed = dispatcher.dispatch(
        lease, TOOL, {"amount": 1},
        tenant_id=TENANT, target_environment=TARGET, actor_identity=ACTOR)
    assert allowed.executed
