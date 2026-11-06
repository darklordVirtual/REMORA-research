# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Structured scope of an intent authority (property D, AACP Semantic Authority).

A resolved intent says what the task is. Its scope says what the authority
behind it permits: which tools, which effects, which targets. The two are
different questions. ``tool_matches_goal`` compares a call with a task
description and can only say "looks wrong", which the engine routes to a
human. A scope is a set of permitted values taken from the work order itself,
and a call outside it is not a judgment call: an approver who lets it through
issues a wider work order without the process that issues work orders.

The OT pilot showed the difference (``artifacts/ot-pilot/
execution-path-reproduction-2026-11-05``): S06 wrote valve V-18 under a work
order for V-12, and S09 wrote a setpoint under the read-only monitoring round,
both after a scripted approver approved. Neither the goal match nor WS1 in
shadow bound the call to *its* work order.

A deployment declares a scope check through its semantic bundle module::

    def validate_intent_scope(
        intent_ref: str | None, tool_name: str, arguments: dict[str, Any], tenant: str
    ) -> IntentScopeResult: ...

The execution path calls it on every assessment and again on the fresh
observation built at execute and at dispatch, so a work order changed or
withdrawn after approval voids the approval. ``in_scope`` passes; any other
answer is a hard ABSTAIN that no review can lift (``NON_APPROVABLE_REASONS``).

The check here is deliberately exact. Identifiers are compared as given: no
case folding, trimming or prefix match, so ``"wo-1201 "`` is not ``WO-1201``
and ``"WO-1201\\n---\\n..."`` is not either. Argument values that are not
strings never match a target. Violations name the dimension, never the value,
so a hostile string is not echoed back into a review or audit record.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = [
    "IN_SCOPE",
    "OUT_OF_SCOPE",
    "SCOPE_STATUSES",
    "UNBOUND",
    "IntentScope",
    "IntentScopeResult",
    "evaluate_intent_scope",
    "normalise_scope_result",
]

IN_SCOPE: Final = "in_scope"
OUT_OF_SCOPE: Final = "out_of_scope"
UNBOUND: Final = "unbound"
SCOPE_STATUSES: Final = frozenset({IN_SCOPE, OUT_OF_SCOPE, UNBOUND})


@dataclass(frozen=True)
class IntentScopeResult:
    """A deployment's answer for one call.

    ``status`` is one of :data:`SCOPE_STATUSES`. ``violations`` names what was
    outside the scope (``tool``, ``effect``, ``target:<argument>``) or why no
    scope bound (``intent_ref_missing``, ``intent_ref_unknown``,
    ``scope_undeclared``, ``validator_error``).
    """

    status: str
    violations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in SCOPE_STATUSES:
            raise ValueError(f"unknown intent scope status {self.status!r}")


def _str_set(value: Any, what: str) -> frozenset[str]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise ValueError(f"{what} must be a list of strings")
    items = tuple(value)
    if not all(isinstance(v, str) and v for v in items):
        raise ValueError(f"{what} must be a list of non-empty strings")
    return frozenset(items)


@dataclass(frozen=True)
class IntentScope:
    """What one authority (one work order) permits.

    ``tools``: tool names the order permits. ``effects``: contract effects it
    permits (``read``, ``update``, ``create``, ``close``, ...). ``targets``:
    for each target argument, the identifiers the order names. A tool whose
    contract declares a target argument the scope does not list has no
    authority over any target, and is out of scope.
    """

    tools: frozenset[str]
    effects: frozenset[str]
    targets: Mapping[str, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any) -> IntentScope:
        """Parse a declared scope, strictly. Anything malformed raises."""
        if not isinstance(data, Mapping):
            raise ValueError("scope must be an object")
        unknown = set(data) - {"tools", "effects", "targets"}
        if unknown:
            raise ValueError(f"scope has unknown keys {sorted(unknown)}")
        tools = _str_set(data.get("tools"), "scope.tools")
        effects = _str_set(data.get("effects"), "scope.effects")
        if not tools or not effects:
            raise ValueError("scope.tools and scope.effects must not be empty")
        raw_targets = data.get("targets", {})
        if not isinstance(raw_targets, Mapping):
            raise ValueError("scope.targets must be an object")
        targets = {str(arg): _str_set(ids, f"scope.targets.{arg}")
                   for arg, ids in raw_targets.items()}
        return cls(tools=tools, effects=effects, targets=targets)

    def check(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        effect: str | None,
        target_arguments: Iterable[str],
    ) -> IntentScopeResult:
        """Is this call inside the scope?

        ``effect`` and ``target_arguments`` come from the deployment's tool
        contract, never from the call. A missing effect is out of scope.
        """
        violations: list[str] = []
        if tool_name not in self.tools:
            violations.append("tool")
        if effect is None or effect not in self.effects:
            violations.append("effect")
        for arg in sorted(set(target_arguments)):
            allowed = self.targets.get(arg)
            value = arguments.get(arg)
            if allowed is None or not isinstance(value, str) or value not in allowed:
                violations.append(f"target:{arg}")
        if violations:
            return IntentScopeResult(OUT_OF_SCOPE, tuple(violations))
        return IntentScopeResult(IN_SCOPE)


def evaluate_intent_scope(
    scope: IntentScope | None,
    tool_name: str,
    arguments: Mapping[str, Any],
    *,
    effect: str | None,
    target_arguments: Iterable[str],
    unbound_reason: str = "intent_ref_unknown",
) -> IntentScopeResult:
    """``scope.check(...)``, or ``unbound`` when no scope resolved."""
    if scope is None:
        return IntentScopeResult(UNBOUND, (unbound_reason,))
    return scope.check(tool_name, arguments, effect=effect,
                       target_arguments=target_arguments)


def normalise_scope_result(result: Any) -> IntentScopeResult:
    """What the execution path records for a validator's answer.

    Anything other than an :class:`IntentScopeResult` is read as ``unbound``:
    a deployment that cannot say the call is in scope has not bound it.
    """
    if isinstance(result, IntentScopeResult):
        return result
    return IntentScopeResult(UNBOUND, ("validator_error",))
