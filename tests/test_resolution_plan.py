# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for ResolutionPlan and router re-entry.

§22 measured obtainable VERIFY recall at 0%: a call missing an argument that an
available tool could supply was accepted rather than routed to a bounded fetch,
because the engine had no notion of "resolve, then decide again".

The contract this establishes:

    VERIFY means a specific, permitted, bounded machine step is expected to
    establish the missing information.

A VERIFY without a plan is invalid. A missing argument with no resolver is
ABSTAIN, not VERIFY — the distinction §21 said the router could not make.

Re-entry runs the **whole** router again on a fresh observation. The resolver
never performs the original call: it fetches one value and hands control back.
"""
from __future__ import annotations

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason
from remora.policy.resolution import (
    ResolutionExhausted,
    ResolutionPlan,
    ResolverViolation,
    resolve_and_reenter,
)

ENGINE = RemoraDecisionEngine(low_consequence_accept=True)


def _obs(**kwargs) -> PolicyObservation:
    base: dict = dict(
        question="Get reservation details for EHGLP3",
        action_type="read",
        proposed_tool_name="get_reservation_details",
    )
    base.update(kwargs)
    return PolicyObservation(**base)


# ---------------------------------------------------------------------------
# 1-2. Missing argument routes on whether a resolver exists
# ---------------------------------------------------------------------------

def test_missing_argument_with_a_resolver_verifies_with_a_plan() -> None:
    report = ENGINE.decide(
        _obs(
            missing_required_arguments=("reservation_id",),
            argument_resolver_tools=("lookup_reservation_id",),
            arguments_satisfiable=True,
        )
    )
    assert report.action == DecisionAction.VERIFY
    assert DecisionReason.ARGUMENT_RESOLUTION_REQUIRED in report.reasons
    assert report.resolution_plan is not None
    assert report.resolution_plan.target_arguments == ("reservation_id",)
    assert report.resolution_plan.source_tools == ("lookup_reservation_id",)


def test_missing_argument_without_a_resolver_abstains() -> None:
    """No bounded step can close the gap, so VERIFY would be a false promise."""
    report = ENGINE.decide(
        _obs(
            missing_required_arguments=("reservation_id",),
            argument_resolver_tools=(),
            arguments_satisfiable=False,
        )
    )
    assert report.action == DecisionAction.ABSTAIN
    assert DecisionReason.NO_RESOLVER_AVAILABLE in report.reasons
    assert report.resolution_plan is None


def test_no_verify_from_this_gate_without_a_plan() -> None:
    """The contract: a VERIFY produced here always carries a plan."""
    report = ENGINE.decide(
        _obs(
            missing_required_arguments=("reservation_id",),
            argument_resolver_tools=("lookup_reservation_id",),
            arguments_satisfiable=True,
        )
    )
    if DecisionReason.ARGUMENT_RESOLUTION_REQUIRED in report.reasons:
        assert report.resolution_plan is not None


def test_default_behaviour_is_unchanged_when_the_field_is_empty() -> None:
    assert ENGINE.decide(_obs()).action == DecisionAction.ACCEPT
    assert RemoraDecisionEngine().decide(_obs()).action == DecisionAction.ABSTAIN


# ---------------------------------------------------------------------------
# 3-4. Re-entry outcome depends on what the resolver returns
# ---------------------------------------------------------------------------

def test_successful_resolution_re_enters_and_can_accept() -> None:
    obs = _obs(
        missing_required_arguments=("reservation_id",),
        argument_resolver_tools=("lookup_reservation_id",),
        arguments_satisfiable=True,
    )
    result = resolve_and_reenter(
        obs, ENGINE, resolver=lambda tool, arg: "EHGLP3"
    )
    assert result.attempts == 1
    assert result.resolved == {"reservation_id": "EHGLP3"}
    assert result.final_report.action == DecisionAction.ACCEPT


def test_resolver_returning_nothing_abstains() -> None:
    """An unresolved gap must not fall through to acceptance."""
    obs = _obs(
        missing_required_arguments=("reservation_id",),
        argument_resolver_tools=("lookup_reservation_id",),
        arguments_satisfiable=True,
    )
    result = resolve_and_reenter(obs, ENGINE, resolver=lambda tool, arg: None)
    assert result.final_report.action == DecisionAction.ABSTAIN
    assert result.resolved == {}


def test_resolver_raising_abstains_rather_than_propagating() -> None:
    def failing(tool: str, arg: str):
        raise RuntimeError("registry unreachable")

    obs = _obs(
        missing_required_arguments=("reservation_id",),
        argument_resolver_tools=("lookup_reservation_id",),
        arguments_satisfiable=True,
    )
    result = resolve_and_reenter(obs, ENGINE, resolver=failing)
    assert result.final_report.action == DecisionAction.ABSTAIN


# ---------------------------------------------------------------------------
# 5. The resolver's authority is bounded
# ---------------------------------------------------------------------------

def test_resolver_cannot_change_the_target_tool() -> None:
    """A resolver that redirects the call is an escalation of privilege."""
    plan = ResolutionPlan(
        resolver="argument_resolution",
        target_arguments=("reservation_id",),
        source_tools=("lookup_reservation_id",),
    )
    with pytest.raises(ResolverViolation, match="tool"):
        plan.assert_preserves_call(
            before_tool="get_reservation_details", after_tool="cancel_reservation"
        )


def test_resolver_cannot_touch_an_argument_outside_the_plan() -> None:
    plan = ResolutionPlan(
        resolver="argument_resolution",
        target_arguments=("reservation_id",),
        source_tools=("lookup_reservation_id",),
    )
    with pytest.raises(ResolverViolation, match="recipient"):
        plan.assert_only_targets({"reservation_id": "X", "recipient": "attacker@x"})


def test_re_entry_rejects_a_resolver_that_changes_the_tool() -> None:
    obs = _obs(
        missing_required_arguments=("reservation_id",),
        argument_resolver_tools=("lookup_reservation_id",),
        arguments_satisfiable=True,
    )
    result = resolve_and_reenter(
        obs, ENGINE, resolver=lambda tool, arg: "EHGLP3",
        _tamper_tool="cancel_reservation",
    )
    assert result.final_report.action == DecisionAction.ABSTAIN
    assert result.violation is not None


# ---------------------------------------------------------------------------
# 6. Attempts are bounded
# ---------------------------------------------------------------------------

def test_max_attempts_is_enforced() -> None:
    plan = ResolutionPlan(
        resolver="argument_resolution",
        target_arguments=("a",),
        source_tools=("lookup_a",),
        max_attempts=2,
    )
    plan.assert_within_budget(1)
    plan.assert_within_budget(2)
    with pytest.raises(ResolutionExhausted):
        plan.assert_within_budget(3)


def test_re_entry_never_loops() -> None:
    """One resolution round, then a terminal decision. No unbounded retry."""
    calls = {"n": 0}

    def counting(tool: str, arg: str):
        calls["n"] += 1
        return None

    obs = _obs(
        missing_required_arguments=("reservation_id",),
        argument_resolver_tools=("lookup_reservation_id",),
        arguments_satisfiable=True,
    )
    resolve_and_reenter(obs, ENGINE, resolver=counting)
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# 7. Provenance
# ---------------------------------------------------------------------------

def test_resolved_values_carry_provenance() -> None:
    obs = _obs(
        missing_required_arguments=("reservation_id",),
        argument_resolver_tools=("lookup_reservation_id",),
        arguments_satisfiable=True,
    )
    result = resolve_and_reenter(obs, ENGINE, resolver=lambda tool, arg: "EHGLP3")
    assert result.provenance == {"reservation_id": "lookup_reservation_id"}


def test_re_entry_runs_the_whole_router_not_just_the_gate() -> None:
    """A hard guard must still fire on the re-entered observation.

    If re-entry only re-ran the resolution gate, a resolved call could bypass
    every block the engine applies before it.
    """
    obs = _obs(
        missing_required_arguments=("reservation_id",),
        argument_resolver_tools=("lookup_reservation_id",),
        arguments_satisfiable=True,
        tool_forbidden=True,
    )
    result = resolve_and_reenter(obs, ENGINE, resolver=lambda tool, arg: "EHGLP3")
    assert result.final_report.action == DecisionAction.ESCALATE
    assert DecisionReason.FORBIDDEN_TOOL_BLOCKED in result.final_report.reasons


# ---------------------------------------------------------------------------
# An unresolvable VERIFY from any gate is a false promise
# ---------------------------------------------------------------------------

def test_unresolvable_gap_downgrades_a_verify_from_another_gate() -> None:
    """A VERIFY produced upstream must not survive an unobtainable requirement.

    The §23 contract says VERIFY means a specific bounded step is expected to
    establish the missing information. That has to hold whichever gate emitted
    the VERIFY: a mutating call with an unknown schema gets VERIFY from
    schema_unverified_verify long before the resolution gate is reached, and
    without this the engine promises a verification it has already established
    cannot happen. Both outcomes block execution, so this is a statement about
    honesty rather than a change in safety.
    """
    obs = PolicyObservation(
        question="cancel reservation",
        action_type="write",            # mutating -> schema_unverified_verify
        proposed_tool_name="cancel_reservation",
        missing_required_arguments=("reservation_id",),
        argument_resolver_tools=(),     # nothing can supply it
        arguments_satisfiable=False,
    )
    report = ENGINE.decide(obs)
    assert report.action == DecisionAction.ABSTAIN
    assert DecisionReason.NO_RESOLVER_AVAILABLE in report.reasons


def test_a_resolvable_gap_leaves_an_upstream_verify_alone() -> None:
    """Only the unresolvable case downgrades; a real plan keeps VERIFY."""
    obs = PolicyObservation(
        question="cancel reservation",
        action_type="write",
        proposed_tool_name="cancel_reservation",
        missing_required_arguments=("reservation_id",),
        argument_resolver_tools=("lookup_reservation_id",),
        arguments_satisfiable=True,
    )
    assert ENGINE.decide(obs).action == DecisionAction.VERIFY


def test_an_escalate_is_never_downgraded_by_this_rule() -> None:
    """A block outranks the honesty rule; ESCALATE must survive."""
    obs = PolicyObservation(
        question="cancel reservation",
        action_type="write",
        tool_forbidden=True,
        missing_required_arguments=("reservation_id",),
        argument_resolver_tools=(),
        arguments_satisfiable=False,
    )
    assert ENGINE.decide(obs).action == DecisionAction.ESCALATE
