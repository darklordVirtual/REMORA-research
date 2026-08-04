# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Task-tool semantic compatibility (§34 backlog theme 1).

§34 measured the gap blind: 86.8% of substituted-but-well-formed calls were
accepted, because every structural signal was satisfied. §35's value grounding
cut that to 11.6% on development data, but 30 of 258 still passed — their
argument values coincidentally occurred in the task. Grounding answers "do these
values come from this context?"; it cannot answer "is this the right tool and
the right effect for the user's goal?".

These tests pin the answer to the second question, and — more importantly — pin
the *limits* of the authority that answers it. A model may propose a TaskIntent.
It may not thereby assert SUPPORTED: the match must be re-derivable from the
task text, the declared tool contract, and the call itself.
"""
from __future__ import annotations

import pytest

from remora.toolcall.routing.goal_match import (
    GoalMatch,
    TaskIntent,
    match_tool_to_intent,
)
from remora.toolcall.routing.tool_contract import ToolContract, ToolContractRegistry

TASK = "Show me booking B-104 for the Oslo trip."

GET_BOOKING = ToolContract(
    tool="get_booking",
    capability="booking_management",
    effect="read",
    resource_type="booking",
    mutation=False,
    argument_roles={"booking_id": "target_resource"},
)
CANCEL_BOOKING = ToolContract(
    tool="cancel_booking",
    capability="booking_management",
    effect="cancel",
    resource_type="booking",
    mutation=True,
    argument_roles={"booking_id": "target_resource"},
)
GET_HOTEL = ToolContract(
    tool="get_hotel",
    capability="hotel_search",
    effect="read",
    resource_type="hotel",
    mutation=False,
    argument_roles={"hotel_id": "target_resource"},
)

REGISTRY = ToolContractRegistry((GET_BOOKING, CANCEL_BOOKING, GET_HOTEL))

READ_INTENT = TaskIntent(
    operation="retrieve",
    resource_type="booking",
    requested_effect="read",
    target_entities=("target_resource",),
    source_spans=("booking B-104",),
    action_spans=("show me",),
)


def _match(tool, intent=READ_INTENT, args=None, task=TASK):
    return match_tool_to_intent(
        contract=REGISTRY.get(tool),
        intent=intent,
        proposed_args=args if args is not None else {"booking_id": "B-104"},
        task_text=task,
    )


# ---------------------------------------------------------------------------
# The three verdicts
# ---------------------------------------------------------------------------

def test_the_right_tool_for_the_goal_is_supported() -> None:
    result = _match("get_booking")
    assert result.verdict is GoalMatch.SUPPORTED


def test_the_wrong_resource_is_unsupported_even_with_a_wellformed_call() -> None:
    # This is §34's failure: a valid hotel call answering a booking question.
    # Every structural signal is satisfied; only the goal says no.
    result = _match("get_hotel", args={"hotel_id": "H-77"})
    assert result.verdict is GoalMatch.UNSUPPORTED
    assert "resource" in result.reason


def test_the_right_resource_with_the_wrong_effect_is_unsupported() -> None:
    # The case the review singled out: same resource, read requested, delete
    # proposed. Nothing about the arguments distinguishes these.
    result = _match("cancel_booking")
    assert result.verdict is GoalMatch.UNSUPPORTED
    assert "effect" in result.reason


def test_an_unregistered_tool_is_unknown_not_unsupported() -> None:
    # Absence of a contract is absence of evidence. Treating it as a mismatch
    # would make every unmodelled deployment fail closed into uselessness.
    result = match_tool_to_intent(
        contract=None, intent=READ_INTENT,
        proposed_args={"booking_id": "B-104"}, task_text=TASK,
    )
    assert result.verdict is GoalMatch.UNKNOWN


def test_no_intent_is_unknown() -> None:
    result = match_tool_to_intent(
        contract=GET_BOOKING, intent=None,
        proposed_args={"booking_id": "B-104"}, task_text=TASK,
    )
    assert result.verdict is GoalMatch.UNKNOWN


# ---------------------------------------------------------------------------
# The authority limit: a proposed intent is a claim, not a fact
# ---------------------------------------------------------------------------

def test_an_intent_whose_spans_are_not_in_the_task_cannot_support_anything() -> None:
    # A model that invents "cancel my booking" out of a task that says
    # "show me booking B-104" would otherwise manufacture SUPPORTED for a
    # destructive call. Spans must be re-derivable from the task text.
    fabricated = TaskIntent(
        operation="cancel",
        resource_type="booking",
        requested_effect="cancel",
        target_entities=("target_resource",),
        source_spans=("cancel my booking",),
    )
    result = _match("cancel_booking", intent=fabricated)
    assert result.verdict is GoalMatch.UNKNOWN
    assert "span" in result.reason


def test_span_verification_is_case_and_whitespace_insensitive() -> None:
    intent = TaskIntent(
        operation="retrieve", resource_type="booking", requested_effect="read",
        target_entities=("target_resource",), source_spans=("BOOKING   b-104",),
        action_spans=("SHOW  me",),  # normalised → "show me" → grounded
    )
    assert _match("get_booking", intent=intent).verdict is GoalMatch.SUPPORTED


def test_an_intent_with_no_spans_at_all_cannot_support() -> None:
    intent = TaskIntent(
        operation="retrieve", resource_type="booking", requested_effect="read",
        target_entities=("target_resource",), source_spans=(),
    )
    assert _match("get_booking", intent=intent).verdict is GoalMatch.UNKNOWN


def test_the_call_must_actually_carry_the_targeted_role() -> None:
    # Right tool, right effect, but the call does not fill the role the intent
    # says is being targeted. Nothing establishes the match.
    result = _match("get_booking", args={})
    assert result.verdict is GoalMatch.UNKNOWN
    assert "role" in result.reason


# ---------------------------------------------------------------------------
# Read/write asymmetry
# ---------------------------------------------------------------------------

def test_a_mutating_tool_never_reaches_supported_from_a_read_intent() -> None:
    for effect in ("read", "retrieve"):
        intent = TaskIntent(
            operation="retrieve", resource_type="booking", requested_effect=effect,
            target_entities=("target_resource",), source_spans=("booking B-104",),
            action_spans=("show me",),  # grounded → proceeds to effect mismatch
        )
        assert _match("cancel_booking", intent=intent).verdict is GoalMatch.UNSUPPORTED


def test_a_matching_mutation_is_supported_when_the_task_asks_for_it() -> None:
    task = "Please cancel booking B-104."
    intent = TaskIntent(
        operation="cancel", resource_type="booking", requested_effect="cancel",
        target_entities=("target_resource",), source_spans=("cancel booking B-104",),
        action_spans=("cancel",),  # explicit action grounding
    )
    result = _match("cancel_booking", intent=intent, task=task)
    assert result.verdict is GoalMatch.SUPPORTED
    # SUPPORTED is not permission: the write path still routes it to VERIFY.
    assert result.mutation is True


# ---------------------------------------------------------------------------
# Contract registry
# ---------------------------------------------------------------------------

def test_registry_round_trips_through_json() -> None:
    loaded = ToolContractRegistry.from_json_dict(REGISTRY.to_json_dict())
    assert loaded.get("cancel_booking") == CANCEL_BOOKING


def test_registry_rejects_a_role_that_is_not_a_declared_argument() -> None:
    with pytest.raises(ValueError, match="mutation"):
        ToolContract(
            tool="x", capability="c", effect="delete", resource_type="r",
            mutation=False, argument_roles={},
        )


# ---------------------------------------------------------------------------
# Semantic binding — the §34 residue that source-span presence cannot close
#
# These cases pin the authority gap identified in the external review:
# source_spans proves the entity was mentioned; it cannot prove the effect
# was requested.  "Show me booking B-104" must not ground a cancel claim
# however clearly "booking B-104" appears in the task.
# ---------------------------------------------------------------------------

from remora.toolcall.routing.goal_match import (  # noqa: E402
    EFFECT_VOCABULARY,
    EFFECT_VOCABULARY_VERSION,
    match_tool_to_intent,
)

_SHOW_TASK = "Show me booking B-104."


def test_real_entity_span_with_wrong_effect_is_unknown() -> None:
    # THE HEADLINE GAP: entity span verifies, resource type matches, and the
    # effect label matches the contract — but "cancel" is not in the task.
    intent = TaskIntent(
        operation="cancel", resource_type="booking", requested_effect="cancel",
        target_entities=("target_resource",),
        source_spans=("booking B-104",),   # entity grounded ✓
        action_spans=("booking B-104",),   # no cancel keyword → NOT grounded
    )
    result = match_tool_to_intent(
        contract=CANCEL_BOOKING, intent=intent,
        proposed_args={"booking_id": "B-104"}, task_text=_SHOW_TASK,
    )
    assert result.verdict is GoalMatch.UNKNOWN
    assert "effect" in result.reason


def test_read_verb_does_not_ground_cancel_effect() -> None:
    # A model claiming cancel intent while quoting a read-verb action span.
    intent = TaskIntent(
        operation="cancel", resource_type="booking", requested_effect="cancel",
        target_entities=("target_resource",),
        source_spans=("booking B-104",),
        action_spans=("show me",),  # read keyword, not in cancel vocabulary
    )
    result = match_tool_to_intent(
        contract=CANCEL_BOOKING, intent=intent,
        proposed_args={"booking_id": "B-104"}, task_text=_SHOW_TASK,
    )
    assert result.verdict is GoalMatch.UNKNOWN


def test_no_action_spans_yields_unknown_even_with_entity_spans() -> None:
    # A TaskIntent constructed without action_spans cannot reach SUPPORTED.
    # The effect is ungrounded, regardless of the entity span.
    intent = TaskIntent(
        operation="retrieve", resource_type="booking", requested_effect="read",
        target_entities=("target_resource",),
        source_spans=("booking B-104",),
        # action_spans defaults to ()
    )
    result = _match("get_booking", intent=intent)
    assert result.verdict is GoalMatch.UNKNOWN
    assert "effect" in result.reason or "action" in result.reason


def test_negation_prevents_effect_grounding() -> None:
    # "do not cancel" contains the keyword but it is negated — must be UNKNOWN.
    task = "Please do not cancel booking B-104."
    intent = TaskIntent(
        operation="cancel", resource_type="booking", requested_effect="cancel",
        target_entities=("target_resource",),
        source_spans=("booking B-104",),
        action_spans=("do not cancel",),
    )
    result = match_tool_to_intent(
        contract=CANCEL_BOOKING, intent=intent,
        proposed_args={"booking_id": "B-104"}, task_text=task,
    )
    assert result.verdict is GoalMatch.UNKNOWN


def test_conditionality_prevents_effect_grounding() -> None:
    # "inspect before closing" — "closing" is conditional, not immediate.
    task = "Please inspect pump P-401 before closing it."
    close_pump = ToolContract(
        tool="close_pump", capability="pump_management", effect="close",
        resource_type="pump", mutation=True,
        argument_roles={"pump_id": "target_resource"},
        state_delta={"pump.status": "closed"},
    )
    intent = TaskIntent(
        operation="close", resource_type="pump", requested_effect="close",
        target_entities=("target_resource",),
        source_spans=("pump P-401",),
        action_spans=("before closing",),  # conditional → NOT grounded
    )
    result = match_tool_to_intent(
        contract=close_pump, intent=intent,
        proposed_args={"pump_id": "P-401"}, task_text=task,
    )
    assert result.verdict is GoalMatch.UNKNOWN


def test_action_spans_not_in_task_text_are_unknown() -> None:
    # Action span text that does not appear in the task cannot ground anything.
    intent = TaskIntent(
        operation="cancel", resource_type="booking", requested_effect="cancel",
        target_entities=("target_resource",),
        source_spans=("booking B-104",),
        action_spans=("cancel this reservation",),  # not in _SHOW_TASK
    )
    result = _match("cancel_booking", intent=intent, task=_SHOW_TASK)
    assert result.verdict is GoalMatch.UNKNOWN


def test_unrecognised_effect_cannot_be_grounded() -> None:
    # An effect name absent from EFFECT_VOCABULARY yields UNKNOWN regardless
    # of how well the span verifies.
    assert "frobnicate" not in EFFECT_VOCABULARY, (
        f"update this test — 'frobnicate' was added to "
        f"EFFECT_VOCABULARY/{EFFECT_VOCABULARY_VERSION}"
    )
    custom_contract = ToolContract(
        tool="custom_tool", capability="misc", effect="frobnicate",
        resource_type="booking", mutation=True,
        argument_roles={"booking_id": "target_resource"},
        state_delta={"booking.state": "frobnicated"},
    )
    intent = TaskIntent(
        operation="frobnicate", resource_type="booking",
        requested_effect="frobnicate",
        target_entities=("target_resource",),
        source_spans=("booking B-104",),
        action_spans=("frobnicate booking B-104",),
    )
    result = match_tool_to_intent(
        contract=custom_contract, intent=intent,
        proposed_args={"booking_id": "B-104"},
        task_text="frobnicate booking B-104",
    )
    assert result.verdict is GoalMatch.UNKNOWN


# ---------------------------------------------------------------------------
# Policy routing: what an established mismatch does, and what it must not do
# ---------------------------------------------------------------------------

from remora.policy.decision_engine import RemoraDecisionEngine  # noqa: E402
from remora.policy.observation import PolicyObservation  # noqa: E402
from remora.policy.report import DecisionAction, DecisionReason  # noqa: E402


def _obs(**kw) -> PolicyObservation:
    base = dict(
        question="show me booking B-104",
        action_type="read", risk_tier="low", target_environment="staging",
        trust_score=0.9, phase="ordered", schema_valid=True,
    )
    base.update(kw)
    return PolicyObservation(**base)


def test_a_refuted_read_abstains() -> None:
    engine = RemoraDecisionEngine(low_consequence_accept=True)
    report = engine.decide(_obs(tool_matches_goal=False))
    assert report.action is DecisionAction.ABSTAIN
    assert DecisionReason.TOOL_DOES_NOT_MATCH_GOAL in report.reasons


def test_a_refuted_write_escalates() -> None:
    # Proposing a state change the task did not ask for is a question about
    # authority, not about information.
    engine = RemoraDecisionEngine(low_consequence_accept=True)
    report = engine.decide(_obs(action_type="production_write", tool_matches_goal=False))
    assert report.action is DecisionAction.ESCALATE


def test_an_unknown_action_type_escalates_rather_than_abstains() -> None:
    engine = RemoraDecisionEngine(low_consequence_accept=True)
    report = engine.decide(_obs(action_type=None, tool_matches_goal=False))
    assert report.action is DecisionAction.ESCALATE


def test_unknown_goal_match_changes_nothing() -> None:
    # A deployment that declares no tool contracts must be unaffected. This is
    # the inert-by-default property every argument gate here has.
    engine = RemoraDecisionEngine(low_consequence_accept=True)
    without = engine.decide(_obs())
    with_unknown = engine.decide(_obs(tool_matches_goal=None))
    assert without.action is with_unknown.action


def test_a_supported_match_is_not_permission_by_itself() -> None:
    # SUPPORTED must not *create* an accept. Held at a trust level that would
    # not accept on its own, a matching goal changes nothing — the gate only
    # ever refutes, and the observation must earn its accept elsewhere.
    engine = RemoraDecisionEngine(low_consequence_accept=False)
    low_trust = dict(trust_score=0.2, phase="critical")
    without = engine.decide(_obs(**low_trust))
    with_match = engine.decide(_obs(tool_matches_goal=True, **low_trust))
    assert with_match.action is without.action
    assert with_match.action is not DecisionAction.ACCEPT


def test_the_gate_can_never_unblock_a_hard_guard() -> None:
    # The whole placement argument: this rule sits after every blocking gate,
    # so a matching goal cannot rescue a forbidden tool or a tainted argument.
    engine = RemoraDecisionEngine(low_consequence_accept=True)
    for blocking in ({"tool_forbidden": True}, {"adversarial_detected": True},
                     {"schema_valid": False}):
        report = engine.decide(_obs(tool_matches_goal=True, **blocking))
        assert report.action is DecisionAction.ESCALATE, blocking


def test_a_mismatch_cannot_downgrade_an_escalation() -> None:
    engine = RemoraDecisionEngine(low_consequence_accept=True)
    report = engine.decide(_obs(tool_matches_goal=False, tool_forbidden=True))
    assert report.action is DecisionAction.ESCALATE


def test_explain_reports_the_goal_gate() -> None:
    engine = RemoraDecisionEngine(low_consequence_accept=True)
    trace = engine.explain(_obs(tool_matches_goal=False))
    assert trace is not None
