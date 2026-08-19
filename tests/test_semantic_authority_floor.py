# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Semantic-authority floor + capability/resource grounding (§34/§36 remediation).

Low consequence is not the same thing as correct purpose: with the floor on,
a proposed tool whose goal fit or expected effect is UNKNOWN can never reach
any ACCEPT path — FALSE stops (existing conditional gates), UNKNOWN
verifies, only TRUE proceeds to the ordinary gates. The grounding
extensions let contracts and intents establish capability and resource
claims explicitly (booking read tools are not substitutes across capability
families).
"""
from __future__ import annotations

from remora.policy import PolicyObservation
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.report import DecisionAction, DecisionReason
from remora.toolcall.routing.goal_match import (
    GoalMatch,
    TaskIntent,
    match_tool_to_intent,
)
from remora.toolcall.routing.tool_contract import ToolContract


def _low_consequence_read(**overrides) -> PolicyObservation:
    base = dict(
        question="read sensor PT-101",
        proposed_tool_name="read_sensor",
        risk_tier="low",
        action_type="read",
        schema_valid=True,
        target_environment="staging",
    )
    base.update(overrides)
    return PolicyObservation(**base)


# ── The floor ────────────────────────────────────────────────────────────────

def test_without_floor_low_consequence_accepts_unknown_fit() -> None:
    """Characterize the BFCL C-ext2 configuration: goal fit UNKNOWN, low
    consequence read → ACCEPT. This is exactly the 28/258 mechanism."""
    engine = RemoraDecisionEngine(low_consequence_accept=True)
    report = engine.decide(_low_consequence_read())
    assert report.action is DecisionAction.ACCEPT


def test_floor_routes_unknown_fit_to_verify() -> None:
    engine = RemoraDecisionEngine(low_consequence_accept=True,
                                  semantic_authority_floor=True)
    report = engine.decide(_low_consequence_read())
    assert report.action is DecisionAction.VERIFY
    assert DecisionReason.SEMANTIC_AUTHORITY_UNKNOWN_VERIFY in report.reasons


def test_floor_routes_unknown_effect_to_verify() -> None:
    engine = RemoraDecisionEngine(low_consequence_accept=True,
                                  semantic_authority_floor=True)
    report = engine.decide(
        _low_consequence_read(tool_matches_goal=True,
                              expected_effect_matches=None)
    )
    assert report.action is DecisionAction.VERIFY
    assert DecisionReason.SEMANTIC_AUTHORITY_UNKNOWN_VERIFY in report.reasons


def test_floor_established_false_still_stops_not_verifies() -> None:
    """FALSE is handled by the conditional gates (ABSTAIN for reads), and the
    floor must not soften that into VERIFY."""
    engine = RemoraDecisionEngine(low_consequence_accept=True,
                                  semantic_authority_floor=True)
    report = engine.decide(_low_consequence_read(tool_matches_goal=False))
    assert report.action is DecisionAction.ABSTAIN


def test_floor_established_true_reaches_ordinary_gates() -> None:
    engine = RemoraDecisionEngine(low_consequence_accept=True,
                                  semantic_authority_floor=True)
    report = engine.decide(
        _low_consequence_read(tool_matches_goal=True,
                              expected_effect_matches=True)
    )
    assert report.action is DecisionAction.ACCEPT
    assert DecisionReason.SEMANTIC_AUTHORITY_UNKNOWN_VERIFY not in report.reasons


def test_floor_is_inert_without_a_proposed_tool() -> None:
    engine = RemoraDecisionEngine(low_consequence_accept=True,
                                  semantic_authority_floor=True)
    report = engine.decide(
        PolicyObservation(question="free-text question, no tool proposal")
    )
    assert DecisionReason.SEMANTIC_AUTHORITY_UNKNOWN_VERIFY not in report.reasons


def test_floor_explain_parity() -> None:
    engine = RemoraDecisionEngine(low_consequence_accept=True,
                                  semantic_authority_floor=True)
    obs = _low_consequence_read()
    assert engine.explain(obs).action == engine.decide(obs).action.value == "verify"


# ── Capability / resource grounding ──────────────────────────────────────────

_BOOKING_TASK = "Please cancel my booking B-104 today"


def _contract(**overrides) -> ToolContract:
    base = dict(tool="cancel_booking", capability="booking_management",
                effect="cancel", resource_type="booking", mutation=True,
                argument_roles={"booking_id": "target_resource"})
    base.update(overrides)
    return ToolContract(**base)


def _intent(**overrides) -> TaskIntent:
    base = dict(operation="cancel", resource_type="booking",
                requested_effect="cancel",
                target_entities=("target_resource",),
                source_spans=("booking B-104",),
                action_spans=("cancel my booking",))
    base.update(overrides)
    return TaskIntent(**base)


def test_capability_mismatch_is_unsupported() -> None:
    """Same resource, same read effect — different capability family."""
    result = match_tool_to_intent(
        contract=_contract(tool="get_booking_payments",
                           capability="payment_reporting", effect="read",
                           mutation=False),
        intent=_intent(requested_effect="read",
                       action_spans=("show", "booking B-104"),
                       requested_capability="booking_management"),
        proposed_args={"booking_id": "B-104"},
        task_text="Please show booking B-104",
    )
    assert result.verdict is GoalMatch.UNSUPPORTED
    assert "capability mismatch" in result.reason


def test_capability_alias_matches() -> None:
    result = match_tool_to_intent(
        contract=_contract(capability_aliases=("reservations",)),
        intent=_intent(requested_capability="reservations"),
        proposed_args={"booking_id": "B-104"},
        task_text=_BOOKING_TASK,
    )
    assert result.verdict is GoalMatch.SUPPORTED


def test_no_requested_capability_keeps_old_semantics() -> None:
    result = match_tool_to_intent(
        contract=_contract(), intent=_intent(),
        proposed_args={"booking_id": "B-104"}, task_text=_BOOKING_TASK,
    )
    assert result.verdict is GoalMatch.SUPPORTED


def test_resource_alias_matches() -> None:
    result = match_tool_to_intent(
        contract=_contract(resource_type="reservation",
                           resource_aliases=("booking",)),
        intent=_intent(),
        proposed_args={"booking_id": "B-104"}, task_text=_BOOKING_TASK,
    )
    assert result.verdict is GoalMatch.SUPPORTED


def test_ungrounded_resource_span_is_unknown_not_supported() -> None:
    result = match_tool_to_intent(
        contract=_contract(), intent=_intent(resource_spans=("hotel room",)),
        proposed_args={"booking_id": "B-104"}, task_text=_BOOKING_TASK,
    )
    assert result.verdict is GoalMatch.UNKNOWN
    assert "resource span" in result.reason


def test_wrong_resource_tool_still_unsupported() -> None:
    """The get_weather-for-a-booking case (§34 residue)."""
    result = match_tool_to_intent(
        contract=_contract(tool="get_weather", capability="weather",
                           effect="read", resource_type="weather",
                           mutation=False),
        intent=_intent(requested_effect="read",
                       action_spans=("show", "booking B-104")),
        proposed_args={},
        task_text="Please show booking B-104",
    )
    assert result.verdict is GoalMatch.UNSUPPORTED
    assert "resource mismatch" in result.reason
