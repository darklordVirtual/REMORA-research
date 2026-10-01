# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Question set V2 and its state, through the same admission boundary as V1.

V2 changes what is asked and how the state is laid out. It does not change
what an answer can do: favourable intent and target answers still become an
evidence signal that stops at VERIFY under the execution profile, and the
injection answers can still only raise ``adversarial_detected``. Splitting
injection into three questions must only add ways to raise the flag.

Scope (declared, not exhaustive): admission and state construction, with a
deterministic provider. Nothing here is evidence about how a live model
answers the V2 wording.
"""

from __future__ import annotations

import pytest

from remora.decision_providers import DeterministicDecisionProvider
from remora.decision_providers.enrich import (
    SemanticThresholds,
    enrich,
    semantic_state_v2,
)
from remora.decision_providers.questions import (
    INJECTION_QUESTIONS_V2,
    QUESTION_SET_VERSION,
    QUESTION_SET_VERSION_V2,
    REMORA_QUESTIONS_V1,
    REMORA_QUESTIONS_V2,
)
from remora.policy.decision_engine import DecisionAction, RemoraDecisionEngine
from remora.policy.observation import PolicyObservation

THRESHOLDS = SemanticThresholds(
    intent_match=0.85,
    target_matches_request=0.85,
    possible_injection=0.5,
    scope_drift=0.5,
)

STATE = semantic_state_v2(
    operator_request="Change the access-port VLAN for customer C123 from 410 to 420",
    tool_name="access.change_customer_vlan",
    tool_description="Sets the access VLAN on one customer port.",
    arguments={"customer_id": "C123", "port": "osl-rtr-07/1/12", "vlan": 420},
    untrusted_content={"ticket_text": "Customer says the new TV box needs VLAN 420."},
)

FAVOURABLE = {
    "intent_match": 0.95,
    "target_matches_request": 0.95,
    "scope_drift": 0.05,
    "injection_instruction": 0.02,
    "injection_authority_claim": 0.02,
    "injection_extra_action": 0.02,
    "action_reversibility": 0.2,
    "semantic_risk": 1.0,
}


def _provider(**answers) -> DeterministicDecisionProvider:
    return DeterministicDecisionProvider(
        {**FAVOURABLE, **answers}, question_set_version=QUESTION_SET_VERSION_V2
    )


def _obs() -> PolicyObservation:
    return PolicyObservation(
        question="change the VLAN",
        risk_tier="high",
        action_type="configuration_change",
        target_environment="prod",
    )


def _enrich(provider):
    return enrich(
        _obs(), provider, state=STATE, thresholds=THRESHOLDS, questions=REMORA_QUESTIONS_V2
    )


def test_v2_is_a_new_version_with_unique_ids() -> None:
    assert QUESTION_SET_VERSION_V2 != QUESTION_SET_VERSION
    ids = [q.id for q in REMORA_QUESTIONS_V2]
    assert len(ids) == len(set(ids))
    assert set(INJECTION_QUESTIONS_V2) <= set(ids)
    assert "possible_injection" not in ids
    assert "recommended_route" not in ids


def test_v2_questions_name_the_state_fields_they_judge() -> None:
    """Jev reads literally; a question about "the object" has no referent."""
    for question in REMORA_QUESTIONS_V2:
        assert "proposed_call" in question.instructions, question.id
    for question_id in INJECTION_QUESTIONS_V2:
        question = next(q for q in REMORA_QUESTIONS_V2 if q.id == question_id)
        assert "untrusted_content" in question.instructions
        assert "operator_request is the trusted task" in question.instructions


def test_the_v2_state_keeps_trusted_and_untrusted_apart() -> None:
    assert set(STATE) == {"operator_request", "proposed_call", "untrusted_content"}
    assert STATE["proposed_call"]["tool"] == "access.change_customer_vlan"
    assert STATE["proposed_call"]["tool_description"].startswith("Sets the access VLAN")
    assert "ticket_text" in STATE["untrusted_content"]


def test_the_v2_state_omits_absent_parts() -> None:
    state = semantic_state_v2(operator_request="x", tool_name="t", arguments={"a": 1})
    assert set(state) == {"operator_request", "proposed_call"}
    assert set(state["proposed_call"]) == {"tool", "arguments"}


@pytest.mark.parametrize("where", ["arguments", "untrusted_content"])
def test_the_v2_state_refuses_credential_shaped_keys(where: str) -> None:
    kwargs = {"operator_request": "x", "tool_name": "t", "arguments": {"a": 1}}
    kwargs[where] = {"api_key": "nope"}
    with pytest.raises(ValueError, match="credential-shaped"):
        semantic_state_v2(**kwargs)


def test_favourable_v2_answers_stop_at_verify() -> None:
    result = _enrich(_provider())
    assert result.outcome == "signals_applied"
    assert result.observation.evidence_action == "answer"
    decision = RemoraDecisionEngine(execution_profile=True).decide(result.observation)
    assert decision.action is DecisionAction.VERIFY


@pytest.mark.parametrize("question_id", INJECTION_QUESTIONS_V2)
def test_each_v2_injection_question_alone_raises_the_flag(question_id: str) -> None:
    result = _enrich(_provider(**{question_id: 0.9}))
    assert result.observation.adversarial_detected is True
    assert any(note.startswith(f"{question_id}=0.90 raised") for note in result.notes)
    decision = RemoraDecisionEngine(execution_profile=True).decide(result.observation)
    assert decision.action is DecisionAction.ESCALATE


def test_v2_injection_answers_cannot_clear_a_raised_flag() -> None:
    raised = PolicyObservation(
        question="change the VLAN",
        risk_tier="high",
        action_type="configuration_change",
        target_environment="prod",
        adversarial_detected=True,
    )
    result = enrich(
        raised, _provider(), state=STATE, thresholds=THRESHOLDS, questions=REMORA_QUESTIONS_V2
    )
    assert result.observation.adversarial_detected is True


def test_no_v2_answer_combination_reaches_accept() -> None:
    engine = RemoraDecisionEngine(execution_profile=True)
    for value in (0.0, 0.5, 1.0):
        answers = {k: value for k in FAVOURABLE if k not in ("action_reversibility", "semantic_risk")}
        result = _enrich(_provider(**answers))
        assert engine.decide(result.observation).action is not DecisionAction.ACCEPT


def test_a_version_mismatch_is_noted_for_v2() -> None:
    provider = DeterministicDecisionProvider(FAVOURABLE, question_set_version="other")
    result = _enrich(provider)
    assert any("calibrated for 'remora-semantic-v2'" in note for note in result.notes)


def test_v1_admission_is_unchanged_by_the_v2_injection_ids() -> None:
    from remora.decision_providers.enrich import semantic_state

    state = semantic_state(intent="x", tool_name="t", arguments={"a": 1})
    provider = DeterministicDecisionProvider(
        {
            "intent_match": 0.95,
            "target_matches_request": 0.95,
            "possible_injection": 0.7,
            "scope_drift": 0.05,
            "action_reversibility": 1.0,
            "semantic_risk": 1.0,
        },
        question_set_version=QUESTION_SET_VERSION,
    )
    result = enrich(_obs(), provider, state=state, thresholds=THRESHOLDS, questions=REMORA_QUESTIONS_V1)
    assert result.observation.adversarial_detected is True
    assert any(note.startswith("possible_injection=0.70 raised") for note in result.notes)
