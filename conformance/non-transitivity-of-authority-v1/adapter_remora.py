# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The REMORA adapter for the non-transitivity-of-authority suite.

Maps the suite's operations onto REMORA's capability layer and enforcement
point, with no mocks between them:

``resolve``    ``CapabilityResolver.resolve``: the principal's set for a task.
``delegate``   ``remora.capabilities.delegate``: a child set, or DelegationDenied.
``authorize``  ``ExecutionLease.issue``: a lease bound to one tool, one argument
               hash, one actor and the capability set's digest.
``dispatch``   ``GovernedToolDispatcher.dispatch``: every check at the PEP,
               including the capability set, its argument constraints and the
               revocation epochs of the set and all its ancestors.
``revoke``     a ``StaticEpochSource`` naming the revoked set, bound to the
               dispatcher.

The map from REMORA refusal reasons to outcome classes is ``REFUSAL_CLASS``
below. A reason not in it is reported verbatim, so an unexpected refusal shows
as a divergence rather than being folded into a class it does not belong to.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from adapter import Unsupported  # noqa: F401  (part of the contract surface)

REFUSAL_CLASS = {
    "tool_name_mismatch": "REFUSED_BINDING",
    "tool_args_hash_mismatch": "REFUSED_BINDING",
    "capability_not_allowed": "REFUSED_NOT_AUTHORIZED",
    "capability_not_visible": "REFUSED_NOT_AUTHORIZED",
    "capability_principal_mismatch": "REFUSED_NOT_AUTHORIZED",
    "capability_argument_mismatch": "REFUSED_ARGUMENT_SCOPE",
    "capability_scope_violation": "REFUSED_ARGUMENT_SCOPE",
    "capability_revoked": "REFUSED_REVOKED",
}

BUNDLE = "nta-suite-bundle"


class RemoraNtaAdapter:
    name = "remora"
    version = "capabilities-q8.5"

    def __init__(self) -> None:
        # A lease needs signing material; the suite supplies a throwaway key
        # only when the environment has none, and never an asymmetric one.
        os.environ.setdefault("REMORA_LEASE_SIGNING_KEY", "nta-conformance-suite-key")
        self._world: dict[str, Any] = {}

    def reset(self, world: dict[str, Any]) -> None:
        from remora.capabilities import CapabilityPolicy, CapabilityResolver

        self._world = world
        tools = sorted(world["tools"].values())
        self._policy = CapabilityPolicy.from_dict({
            "policy_version": "nta-v1", "registry_version": "nta-v1",
            "registry": {t: [world["environment"]] for t in tools},
            "principals": {world["principal"]: sorted(set().union(*world["tasks"].values()))},
            "tasks": world["tasks"],
            "tenants": {world["tenant"]: tools},
            "environments": {world["environment"]: tools},
            "constraints": world["constraints"],
        })
        self._resolver = CapabilityResolver(self._policy)
        self._sets: dict[str, Any] = {}
        self._leases: dict[str, Any] = {}
        self._revoked: set[str] = set()

    def resolve(self, handle: str, *, task: str) -> str:
        w = self._world
        self._sets[handle] = self._resolver.resolve(
            principal_id=w["principal"], tenant_id=w["tenant"], environment=w["environment"],
            task_type=task, now=datetime.now(UTC))
        return "RESOLVED"

    def delegate(self, handle: str, *, parent: str, delegatee: str, tools: list[str],
                 transitive: bool, extra_constraints: dict[str, Any]) -> str:
        from remora.capabilities import DelegationDenied, delegate

        try:
            self._sets[handle] = delegate(
                self._sets[parent], delegatee=delegatee, tools=tools,
                purpose="nta_conformance", now=datetime.now(UTC),
                extra_constraints=extra_constraints or None, transitive=transitive)
        except DelegationDenied:
            return "DELEGATION_DENIED"
        return "DELEGATED"

    def authorize(self, handle: str, *, authority_set: str, actor: str, tool: str,
                  arguments: dict[str, Any]) -> str:
        from remora.enforcement.lease import ExecutionLease

        w = self._world
        self._leases[handle] = ExecutionLease.issue(
            decision="accept", tenant_id=w["tenant"], actor_identity=actor, tool_name=tool,
            arguments=arguments, target_environment=w["environment"],
            policy_bundle_hash=BUNDLE, issued_at=datetime.now(UTC).isoformat(),
            capability_set=self._sets[authority_set])
        return "AUTHORIZED"

    def dispatch(self, *, authority: str, authority_set: str, actor: str, tool: str,
                 arguments: dict[str, Any]) -> str:
        from remora.capabilities import StaticEpochSource
        from remora.enforcement.lease import GovernedToolDispatcher

        w = self._world
        dispatcher = GovernedToolDispatcher(BUNDLE)
        for name in w["tools"].values():
            dispatcher.register(name, lambda args: "ok")
        dispatcher.bind_capability_epochs(StaticEpochSource(
            revoked_sets=frozenset(self._revoked)))
        result = dispatcher.dispatch(
            self._leases[authority], tool, arguments, tenant_id=w["tenant"],
            target_environment=w["environment"], actor_identity=actor,
            capability_set=self._sets[authority_set])
        if result.executed:
            return "EXECUTED"
        reason = str(result.refusal_reason)
        return REFUSAL_CLASS.get(reason, f"REFUSED:{reason}")

    def revoke(self, authority_set: str) -> str:
        self._revoked.add(self._sets[authority_set].capability_set_id)
        return "REVOKED"


def build() -> RemoraNtaAdapter:
    return RemoraNtaAdapter()
