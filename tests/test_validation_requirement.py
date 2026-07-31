# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for validation-required routing of UNKNOWN argument values.

§27 left REMORA epistemically honest but not yet using that honesty. Outside a
covered scope the value status is UNKNOWN, and UNKNOWN fell through to the
low-consequence ACCEPT path — so on an uncovered domain 61.5% of corrupted
identifiers were accepted autonomously.

The fix is *not* to route every UNKNOWN to VERIFY. That would rebuild the
constant blocker §21 measured, one level up: a system that verifies everything
it cannot confirm is a system that verifies everything.

The requirement is decided independently of whether the index happens to have
coverage. An argument that steers where the action lands — a customer, an
account, a recipient, a deployment target — must be validated before autonomous
execution. A free-text note must not be, because an authoritative membership
test is meaningless for it.

    REQUIRED + SUPPORTED        -> continue to the other gates
    REQUIRED + UNSUPPORTED      -> never ACCEPT (already enforced)
    REQUIRED + UNKNOWN + resolver    -> VERIFY, carrying a plan
    REQUIRED + UNKNOWN, no resolver  -> ABSTAIN
    OPTIONAL + UNKNOWN          -> neutral; the other gates decide
"""
from __future__ import annotations

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason
from remora.toolcall.routing.validation import (
    ValidationRequirement,
    requirement_for,
    unvalidated_required,
)

ENGINE = RemoraDecisionEngine(low_consequence_accept=True)


def _obs(**kwargs) -> PolicyObservation:
    base: dict = dict(
        question="look up the subscription",
        action_type="read",
        proposed_tool_name="get_subscription",
    )
    base.update(kwargs)
    return PolicyObservation(**base)


# ---------------------------------------------------------------------------
# The requirement is a property of the argument, not of index coverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    ["customer_id", "account_id", "subscription_id", "line_id", "recipient",
     "device_id", "order_id", "file_path", "deployment_target", "principal"],
)
def test_target_steering_arguments_require_validation(name: str) -> None:
    assert requirement_for(name) is ValidationRequirement.REQUIRED


@pytest.mark.parametrize("name", ["note", "subject", "body", "description", "comment"])
def test_free_text_arguments_do_not_require_validation(name: str) -> None:
    """An authoritative membership test is meaningless for prose."""
    assert requirement_for(name) is ValidationRequirement.NOT_APPLICABLE


def test_unrecognised_argument_is_optional_not_required() -> None:
    """Unknown argument roles must not silently become blocking.

    Defaulting to REQUIRED would make every unfamiliar tool signature a source
    of friction, which is the constant-blocker failure mode again.
    """
    assert requirement_for("gb_amount") is ValidationRequirement.OPTIONAL


def test_unvalidated_required_selects_only_required_and_not_supported() -> None:
    statuses = {
        "customer_id": None,      # required, unknown  -> selected
        "line_id": True,          # required, supported -> not selected
        "recipient": False,       # required, unsupported -> selected
        "note": None,             # not applicable -> not selected
        "gb_amount": None,        # optional -> not selected
    }
    assert unvalidated_required(statuses) == ("customer_id", "recipient")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def test_required_and_unknown_with_a_resolver_verifies_with_a_plan() -> None:
    report = ENGINE.decide(
        _obs(
            unvalidated_required_arguments=("customer_id",),
            argument_resolver_tools=("lookup_customer_id",),
        )
    )
    assert report.action == DecisionAction.VERIFY
    assert DecisionReason.ARGUMENT_VALIDATION_REQUIRED in report.reasons
    assert report.resolution_plan is not None
    assert report.resolution_plan.resolver == "argument_validation"
    assert report.resolution_plan.target_arguments == ("customer_id",)


def test_required_and_unknown_without_a_resolver_abstains() -> None:
    """No authoritative source can confirm it, so autonomy is not available."""
    report = ENGINE.decide(_obs(unvalidated_required_arguments=("customer_id",)))
    assert report.action == DecisionAction.ABSTAIN
    assert DecisionReason.NO_RESOLVER_AVAILABLE in report.reasons


def test_optional_unknown_stays_neutral() -> None:
    """The signal must not block what policy never required validating."""
    assert ENGINE.decide(_obs()).action == DecisionAction.ACCEPT


def test_supported_values_never_reach_this_gate() -> None:
    """A confirmed value is not unvalidated, so nothing is selected."""
    assert unvalidated_required({"customer_id": True}) == ()


def test_the_gate_cannot_preempt_a_block() -> None:
    report = ENGINE.decide(
        _obs(
            tool_forbidden=True,
            unvalidated_required_arguments=("customer_id",),
            argument_resolver_tools=("lookup_customer_id",),
        )
    )
    assert report.action == DecisionAction.ESCALATE


def test_default_behaviour_is_unchanged_when_the_field_is_empty() -> None:
    assert RemoraDecisionEngine().decide(_obs()).action == DecisionAction.ABSTAIN
    assert ENGINE.decide(_obs()).action == DecisionAction.ACCEPT
