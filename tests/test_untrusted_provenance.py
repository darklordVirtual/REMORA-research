# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for untrusted-provenance routing (§23 follow-up).

§23 recorded ESCALATE recall at 0%: every untrusted-origin episode routed to
VERIFY. The earlier benchmark treated all untrusted provenance as one family
with gold route ESCALATE, which was too coarse — untrusted provenance is not by
itself an escalation.

The distinction that matters is whether untrusted content **controls** the call:

    untrusted content present, controlling nothing sensitive
        -> blocked from autonomy, machine-checkable  -> VERIFY

    untrusted content determines a recipient, command, credential or
    egress target
        -> it is authorising, not informing          -> ESCALATE

"Untrusted content may inform, but must never authorize" is the invariant the
v3 injection layer already states. Controlling where money goes, what command
runs, or which credential is used *is* authorising, so it escalates regardless
of the declared risk tier — a caller-supplied "low" must not buy autonomy for
an attacker-chosen recipient.
"""
from __future__ import annotations

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason

ENGINE = RemoraDecisionEngine()


def _obs(**kwargs) -> PolicyObservation:
    base: dict = dict(question="summarise the inbox", action_type="read")
    base.update(kwargs)
    return PolicyObservation(**base)


# ---------------------------------------------------------------------------
# Controlling a sensitive argument escalates, at any tier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "argument",
    ["recipient", "to", "destination", "command", "credential", "api_key", "url"],
)
def test_untrusted_control_of_a_sensitive_argument_escalates(argument: str) -> None:
    report = ENGINE.decide(
        _obs(argument_tainted=True, untrusted_controlled_arguments=(argument,))
    )
    assert report.action == DecisionAction.ESCALATE, argument
    assert DecisionReason.UNTRUSTED_CONTROLS_SENSITIVE_ARGUMENT in report.reasons


@pytest.mark.parametrize("tier", ["low", "medium", "high", "critical", None])
def test_escalation_does_not_depend_on_the_declared_risk_tier(tier) -> None:
    """A caller-declared low tier must not buy autonomy for an attacker's recipient."""
    report = ENGINE.decide(
        _obs(
            argument_tainted=True,
            untrusted_controlled_arguments=("recipient",),
            risk_tier=tier,
        )
    )
    assert report.action == DecisionAction.ESCALATE, tier


def test_case_and_separator_variants_are_recognised() -> None:
    for name in ("Recipient", "to_address", "target_url", "AWS_SECRET_KEY"):
        report = ENGINE.decide(
            _obs(argument_tainted=True, untrusted_controlled_arguments=(name,))
        )
        assert report.action == DecisionAction.ESCALATE, name


# ---------------------------------------------------------------------------
# Non-controlling untrusted content stays at VERIFY
# ---------------------------------------------------------------------------

def test_untrusted_content_controlling_nothing_sensitive_verifies() -> None:
    """Untrusted provenance alone is not an escalation.

    Escalating every tainted call would send a read whose summary text came
    from an email to a human, which is friction without a decision to make.
    """
    report = ENGINE.decide(
        _obs(argument_tainted=True, untrusted_controlled_arguments=("query", "limit"))
    )
    assert report.action == DecisionAction.VERIFY
    assert DecisionReason.UNTRUSTED_CONTROLS_SENSITIVE_ARGUMENT not in report.reasons


def test_tainted_without_the_new_field_is_unchanged() -> None:
    """Default behaviour for existing callers must not move."""
    before = RemoraDecisionEngine().decide(_obs(argument_tainted=True))
    assert before.action == DecisionAction.VERIFY
    assert DecisionReason.TAINTED_ARGUMENT_VERIFY in before.reasons


def test_critical_tier_tainted_still_escalates_by_the_existing_rule() -> None:
    """Issue #40's tier-dependent floor is preserved, not replaced."""
    report = ENGINE.decide(_obs(argument_tainted=True, risk_tier="critical"))
    assert report.action == DecisionAction.ESCALATE
    assert DecisionReason.TAINTED_ARGUMENT_ESCALATE in report.reasons


def test_controlled_arguments_without_taint_do_not_escalate() -> None:
    """The field describes *untrusted* control; without taint there is none."""
    report = ENGINE.decide(
        _obs(argument_tainted=False, untrusted_controlled_arguments=("recipient",))
    )
    assert report.action != DecisionAction.ESCALATE


# ---------------------------------------------------------------------------
# Mutation families
# ---------------------------------------------------------------------------

def test_the_two_provenance_families_have_distinct_gold_routes() -> None:
    from remora.toolcall.routing.episode import Route
    from remora.toolcall.routing.mutations import GOLD_ROUTE, MutationFamily

    assert GOLD_ROUTE[MutationFamily.UNTRUSTED_NONCONTROLLING] is Route.VERIFY
    assert GOLD_ROUTE[MutationFamily.UNTRUSTED_CONTROLS_SENSITIVE] is Route.ESCALATE
