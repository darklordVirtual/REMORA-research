# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""ResolutionPlan and router re-entry.

§22 of ``NEGATIVE_RESULTS.md`` measured obtainable VERIFY recall at 0%: a call
missing an argument that an available tool could supply was *accepted* rather
than routed to a bounded fetch, because the engine had no notion of "resolve,
then decide again".

The contract this establishes:

    VERIFY means a specific, permitted, bounded machine step is expected to
    establish the missing information.

Two consequences follow, and both are enforced rather than documented:

* A VERIFY produced by the resolution gate always carries a plan. A missing
  argument with **no** resolver is ABSTAIN — promising verification that cannot
  happen is worse than stopping.
* Re-entry re-runs the **whole** router on a fresh observation. The resolver
  fetches one value and hands control back; it never performs the original
  call, and it cannot redirect it.

The bounded-authority checks exist because a resolver is the one component
allowed to act before a decision is final. A resolver that could change the
target tool, or write an argument outside its plan, would be a privilege
escalation dressed as a lookup.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Protocol

from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReport


class ResolverViolation(RuntimeError):
    """A resolver exceeded the authority its plan grants."""


class ResolutionExhausted(RuntimeError):
    """The plan's attempt budget is spent."""


class DecisionEngineLike(Protocol):
    def decide(self, obs: PolicyObservation) -> DecisionReport: ...


@dataclass(frozen=True)
class ResolutionPlan:
    """A specific, bounded machine step expected to close an information gap."""

    resolver: str
    #: Exactly the arguments this plan may establish. Anything else is a
    #: violation, not an improvement.
    target_arguments: tuple[str, ...]
    #: The authoritative tools permitted to supply them.
    source_tools: tuple[str, ...]
    max_attempts: int = 1
    #: The resolver hands control back; it never executes the original call.
    reenter_router: bool = True

    def assert_within_budget(self, attempt: int) -> None:
        if attempt > self.max_attempts:
            raise ResolutionExhausted(
                f"attempt {attempt} exceeds max_attempts={self.max_attempts} "
                f"for resolver {self.resolver!r}"
            )

    def assert_preserves_call(self, *, before_tool: str | None, after_tool: str | None) -> None:
        """A resolver may not redirect the call it was invoked for."""
        if before_tool != after_tool:
            raise ResolverViolation(
                f"resolver {self.resolver!r} changed the target tool "
                f"{before_tool!r} -> {after_tool!r}"
            )

    def assert_only_targets(self, resolved: dict[str, Any]) -> None:
        """A resolver may only write the arguments its plan names."""
        extra = sorted(set(resolved) - set(self.target_arguments))
        if extra:
            raise ResolverViolation(
                f"resolver {self.resolver!r} wrote argument(s) outside its plan: "
                f"{extra}"
            )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "resolver": self.resolver,
            "target_arguments": list(self.target_arguments),
            "source_tools": list(self.source_tools),
            "max_attempts": self.max_attempts,
            "reenter_router": self.reenter_router,
        }


@dataclass(frozen=True)
class ResolutionOutcome:
    """What one resolution round established, and what the router then decided."""

    initial_report: DecisionReport
    final_report: DecisionReport
    plan: ResolutionPlan | None
    resolved: dict[str, Any] = field(default_factory=dict)
    #: argument -> the tool that supplied it. Resolved values are never
    #: anonymous: an accepted call must be traceable to where its inputs came
    #: from.
    provenance: dict[str, str] = field(default_factory=dict)
    attempts: int = 0
    violation: str | None = None


def validate_and_reenter(
    obs: PolicyObservation,
    engine: DecisionEngineLike,
    *,
    validator: Callable[[str, str], bool | None],
    _tamper_tool: str | None = None,
) -> ResolutionOutcome:
    """Run one bounded validation round, then re-run the whole router.

    Validation differs from resolution in what the resolver is allowed to do:
    it **writes no argument values**. The value is already in the call; the
    validator only establishes its status against the system of record.
    *validator* is called as ``validator(source_tool, argument)`` and returns
    tri-state: ``True`` (the entity exists), ``False`` (the system of record
    confirms it absent), ``None`` (nothing establishes either).

    The outcome mapping is the §32 contract:

    * every target confirmed → re-enter with the values supported; reads may
      then ACCEPT, writes keep their verification posture
    * any target confirmed absent → re-enter with the value unsupported; the
      call is blocked, never retried into acceptance
    * any target unknown, or a validator error → the gap stands and no
      resolver remains, so the router abstains — a validation that cannot
      happen is not promised
    """
    initial = engine.decide(obs)
    plan = initial.resolution_plan

    if (
        plan is None
        or initial.action is not DecisionAction.VERIFY
        or plan.resolver != "argument_validation"
    ):
        return ResolutionOutcome(
            initial_report=initial, final_report=initial, plan=plan
        )

    verdicts: dict[str, bool] = {}
    provenance: dict[str, str] = {}
    attempts = 0
    violation: str | None = None

    for index, argument in enumerate(plan.target_arguments):
        attempts += 1
        try:
            plan.assert_within_budget(attempts)
        except ResolutionExhausted as exc:
            violation = str(exc)
            break

        source = plan.source_tools[min(index, len(plan.source_tools) - 1)]
        try:
            verdict = validator(source, argument)
        except Exception as exc:  # noqa: BLE001 — an unreachable validator is a gap
            violation = f"validator raised: {exc}"
            break

        if verdict is None:
            continue
        verdicts[argument] = bool(verdict)
        provenance[argument] = source

    if violation is None:
        try:
            plan.assert_only_targets(verdicts)
            plan.assert_preserves_call(
                before_tool=obs.proposed_tool_name,
                after_tool=_tamper_tool or obs.proposed_tool_name,
            )
        except ResolverViolation as exc:
            violation = str(exc)

    confirmed_absent = [a for a in plan.target_arguments if verdicts.get(a) is False]
    unresolved = [a for a in plan.target_arguments if a not in verdicts]

    if confirmed_absent and violation is None:
        # The system of record says the value does not exist. Blocked, never
        # retried into acceptance.
        final = engine.decide(
            replace(
                obs,
                argument_values_supported=False,
                argument_resolver_tools=(),
            )
        )
    elif violation is not None or unresolved:
        # Nothing establishes the status and no resolver remains: the gap
        # stands, so the decision is terminal rather than optimistic.
        final = engine.decide(replace(obs, argument_resolver_tools=()))
    else:
        # Every target confirmed present. Fresh observation, full router:
        # every guard the engine applies runs again on the validated call.
        final = engine.decide(
            replace(
                obs,
                argument_values_supported=True,
                unvalidated_required_arguments=(),
                argument_resolver_tools=(),
            )
        )

    return ResolutionOutcome(
        initial_report=initial,
        final_report=final,
        plan=plan,
        resolved={},
        provenance=provenance,
        attempts=attempts,
        violation=violation,
    )


def resolve_and_reenter(
    obs: PolicyObservation,
    engine: DecisionEngineLike,
    *,
    resolver: Callable[[str, str], Any],
    _tamper_tool: str | None = None,
) -> ResolutionOutcome:
    """Run one bounded resolution round, then re-run the whole router.

    *resolver* is called as ``resolver(source_tool, argument)`` and returns the
    established value, or ``None`` when it cannot establish one. Exceptions are
    contained: an unreachable registry is an unresolved gap, not a crash that
    propagates into a caller's request path.

    ``_tamper_tool`` is a test seam that simulates a resolver attempting to
    redirect the call, so the bounded-authority check can be exercised without
    a malicious resolver implementation.
    """
    initial = engine.decide(obs)
    plan = initial.resolution_plan

    if plan is None or initial.action is not DecisionAction.VERIFY:
        return ResolutionOutcome(
            initial_report=initial, final_report=initial, plan=plan
        )

    resolved: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    attempts = 0
    violation: str | None = None

    for index, argument in enumerate(plan.target_arguments):
        attempts += 1
        try:
            plan.assert_within_budget(attempts)
        except ResolutionExhausted as exc:
            violation = str(exc)
            break

        source = plan.source_tools[min(index, len(plan.source_tools) - 1)]
        try:
            value = resolver(source, argument)
        except Exception as exc:  # noqa: BLE001 — an unreachable resolver is a gap
            violation = f"resolver raised: {exc}"
            break

        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        resolved[argument] = value
        provenance[argument] = source

    if violation is None:
        try:
            plan.assert_only_targets(resolved)
            plan.assert_preserves_call(
                before_tool=obs.proposed_tool_name,
                after_tool=_tamper_tool or obs.proposed_tool_name,
            )
        except ResolverViolation as exc:
            violation = str(exc)

    unresolved = [a for a in plan.target_arguments if a not in resolved]

    if violation is not None or unresolved:
        # Nothing was established, or the resolver overstepped. The gap stands,
        # so the decision is terminal rather than optimistic.
        final = engine.decide(
            replace(
                obs,
                missing_required_arguments=tuple(unresolved) or plan.target_arguments,
                argument_resolver_tools=(),
                arguments_satisfiable=False,
            )
        )
        return ResolutionOutcome(
            initial_report=initial,
            final_report=final,
            plan=plan,
            resolved=resolved,
            provenance=provenance,
            attempts=attempts,
            violation=violation,
        )

    # Fresh observation, full router. Every guard the engine applies before the
    # resolution gate runs again on the resolved call.
    final = engine.decide(
        replace(
            obs,
            missing_required_arguments=(),
            arguments_satisfiable=True,
        )
    )
    return ResolutionOutcome(
        initial_report=initial,
        final_report=final,
        plan=plan,
        resolved=resolved,
        provenance=provenance,
        attempts=attempts,
    )
