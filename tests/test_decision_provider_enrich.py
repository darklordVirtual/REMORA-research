# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Provider answers meeting a policy observation, and what they may do there.

`remora.decision_providers.enrich` is the only place a decision provider's
answers reach an observation. These tests hold three properties:

* fail-closed is structural: a provider that cannot answer leaves the
  observation untouched, and the deterministic decision stands
* the only writes are a favourable model signal (evidence path, which under
  the execution profile stops at VERIFY) and one raised safety flag (which
  the hard block escalates); nothing a provider says can lower a flag or
  reach a deployment fact
* thresholds are required, not defaulted, and credential-shaped keys never
  leave the process

Scope (declared, not exhaustive): the admission logic and its interaction with
the engine under the execution profile. The deterministic provider stands in
for any adapter; no live model is involved.
"""

from __future__ import annotations

import pytest

from remora.decision_providers import (
    DecisionProviderError,
    DeterministicDecisionProvider,
    project_narrowing,
)
from remora.decision_providers.enrich import (
    Enrichment,
    SemanticThresholds,
    enrich,
    semantic_state,
)
from remora.decision_providers.questions import (
    QUESTION_SET_VERSION,
    REMORA_QUESTIONS_V1,
)
from remora.policy.decision_engine import DecisionAction, RemoraDecisionEngine
from remora.policy.observation import PolicyObservation

THRESHOLDS = SemanticThresholds(
    intent_match=0.85,
    target_matches_request=0.85,
    possible_injection=0.5,
    scope_drift=0.5,
)

STATE = semantic_state(
    intent="Refund the duplicate charge on invoice 4471 for customer C123",
    tool_name="crm.refund",
    arguments={"customer_id": "C123", "invoice": "4471", "amount": 250},
)


def _provider(**answers) -> DeterministicDecisionProvider:
    base = {
        "intent_match": 0.95,
        "target_matches_request": 0.95,
        "possible_injection": 0.02,
        "scope_drift": 0.05,
        "action_reversibility": 1.0,
        "semantic_risk": 1.0,
    }
    base.update(answers)
    return DeterministicDecisionProvider(base, question_set_version=QUESTION_SET_VERSION)


def _obs(**kw) -> PolicyObservation:
    fields = dict(
        question="refund the duplicate charge",
        risk_tier="medium",
        action_type="financial_transaction",
        target_environment="prod",
    )
    fields.update(kw)
    return PolicyObservation(**fields)


# ── fail-closed is structural ───────────────────────────────────────────────


def test_an_unavailable_provider_leaves_the_observation_untouched() -> None:
    result = enrich(_obs(), DeterministicDecisionProvider({}), state=STATE, thresholds=THRESHOLDS)
    assert result.outcome == "provider_unavailable"
    assert result.evidence is None
    assert result.observation == _obs()


def test_the_decision_without_the_provider_is_never_more_permissive() -> None:
    """The reason no per-tier failure table exists: absence cannot widen."""
    engine = RemoraDecisionEngine(execution_profile=True)
    rank = {
        DecisionAction.ABSTAIN: 0,
        DecisionAction.ESCALATE: 1,
        DecisionAction.VERIFY: 2,
        DecisionAction.ACCEPT: 3,
    }
    for call in (
        dict(risk_tier="low", action_type="read", target_environment="staging"),
        dict(risk_tier="medium", action_type="write", target_environment="prod"),
        dict(risk_tier="critical", action_type="production_write", target_environment="prod"),
    ):
        without = engine.decide(_obs(**call)).action
        with_provider = engine.decide(
            enrich(_obs(**call), _provider(), state=STATE, thresholds=THRESHOLDS).observation
        ).action
        assert rank[without] <= rank[with_provider], (
            f"absence of the provider produced {without}, presence produced "
            f"{with_provider}: a failure would widen the decision"
        )


# ── the only writes ─────────────────────────────────────────────────────────


def test_favourable_answers_become_the_evidence_signal() -> None:
    result = enrich(_obs(), _provider(), state=STATE, thresholds=THRESHOLDS)
    assert result.outcome == "signals_applied"
    assert result.observation.evidence_action == "answer"
    assert result.observation.evidence_confidence == pytest.approx(0.95)
    assert result.observation.adversarial_detected is False


def test_the_confidence_is_the_weaker_of_the_two_probabilities() -> None:
    result = enrich(
        _obs(), _provider(intent_match=0.97, target_matches_request=0.88),
        state=STATE, thresholds=THRESHOLDS,
    )
    assert result.observation.evidence_confidence == pytest.approx(0.88)


@pytest.mark.parametrize(
    "answers",
    [
        {"intent_match": 0.60},
        {"target_matches_request": 0.60},
        {"scope_drift": 0.90},
    ],
)
def test_a_weak_or_drifting_answer_withholds_the_signal_rather_than_labelling(answers) -> None:
    """No unfavourable label is ever written; the provider says no by silence."""
    result = enrich(_obs(), _provider(**answers), state=STATE, thresholds=THRESHOLDS)
    assert result.outcome == "signals_withheld"
    assert result.observation.evidence_action is None
    assert result.observation.evidence_confidence is None
    assert result.evidence is not None, "the answers are still recorded"


def test_a_likely_injection_raises_the_flag_and_the_hard_block_escalates() -> None:
    result = enrich(
        _obs(), _provider(possible_injection=0.91), state=STATE, thresholds=THRESHOLDS
    )
    assert result.observation.adversarial_detected is True
    assert result.observation.evidence_action is None, "no favourable signal alongside a flag"
    decision = RemoraDecisionEngine(execution_profile=True).decide(result.observation)
    assert decision.action is DecisionAction.ESCALATE


def test_favourable_answers_under_the_execution_profile_stop_at_verify() -> None:
    """The evidence path is reachable and bounded: VERIFY, never ACCEPT."""
    engine = RemoraDecisionEngine(execution_profile=True)
    for call in (
        dict(risk_tier="low", action_type="read", target_environment="staging"),
        dict(risk_tier="medium", action_type="financial_transaction", target_environment="prod"),
    ):
        observation = enrich(_obs(**call), _provider(), state=STATE, thresholds=THRESHOLDS).observation
        assert engine.decide(observation).action is not DecisionAction.ACCEPT


def test_reversibility_and_risk_are_recorded_but_never_projected() -> None:
    result = enrich(
        _obs(), _provider(action_reversibility=2.0, semantic_risk=3.0),
        state=STATE, thresholds=THRESHOLDS,
    )
    assert result.evidence.answer("action_reversibility").value == 2.0
    assert result.evidence.answer("semantic_risk").value == 3.0
    assert result.observation.risk_tier == "medium", "a deployment fact, untouched"
    assert result.observation.rollback_available is None or result.observation.rollback_available == _obs().rollback_available


# ── narrowing is one-directional ────────────────────────────────────────────


def test_a_provider_may_raise_the_flag_but_never_clear_it() -> None:
    raised = project_narrowing(_obs(), {"adversarial_detected": True})
    assert raised.adversarial_detected is True
    with pytest.raises(ValueError, match="never clear"):
        project_narrowing(raised, {"adversarial_detected": False})


def test_a_flag_already_raised_stays_raised_whatever_the_provider_says() -> None:
    already = _obs(adversarial_detected=True)
    result = enrich(already, _provider(possible_injection=0.0), state=STATE, thresholds=THRESHOLDS)
    assert result.observation.adversarial_detected is True


def test_only_declared_flags_can_be_raised() -> None:
    with pytest.raises(ValueError, match="may raise only"):
        project_narrowing(_obs(), {"coercion_detected": True})


# ── thresholds and state hygiene ────────────────────────────────────────────


def test_thresholds_have_no_defaults() -> None:
    with pytest.raises(TypeError):
        SemanticThresholds()  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        SemanticThresholds(
            intent_match=1.5, target_matches_request=0.5, possible_injection=0.5, scope_drift=0.5
        )


@pytest.mark.parametrize(
    "key",
    ["api_key", "Authorization", "access_token", "db_password", "session_id", "private-key"],
)
def test_credential_shaped_keys_never_leave_the_process(key: str) -> None:
    with pytest.raises(ValueError, match="credential-shaped"):
        semantic_state(intent="x", tool_name="t", arguments={key: "value"})
    with pytest.raises(ValueError, match="credential-shaped"):
        semantic_state(intent="x", tool_name="t", arguments={}, context={key: "value"})


def test_the_state_carries_only_what_a_semantic_question_needs() -> None:
    assert set(STATE) == {"intent", "tool_name", "arguments"}


def test_the_question_set_is_versioned_and_names_no_route() -> None:
    ids = {q.id for q in REMORA_QUESTIONS_V1}
    assert "recommended_route" not in ids
    assert QUESTION_SET_VERSION.startswith("remora-semantic-v")
    assert ids == {
        "intent_match",
        "target_matches_request",
        "possible_injection",
        "scope_drift",
        "action_reversibility",
        "semantic_risk",
    }


def test_a_mismatched_question_set_version_is_noted_for_the_record() -> None:
    provider = DeterministicDecisionProvider(
        {q.id: 0.9 for q in REMORA_QUESTIONS_V1}, question_set_version="remora-semantic-v0"
    )
    result = enrich(_obs(), provider, state=STATE, thresholds=THRESHOLDS)
    assert any("calibrated for" in note for note in result.notes)


def test_enrichment_records_the_resolved_model_for_the_audit_line() -> None:
    result = enrich(_obs(), _provider(), state=STATE, thresholds=THRESHOLDS)
    assert isinstance(result, Enrichment)
    assert result.evidence.resolved_model in result.notes[0]


def test_a_provider_error_is_not_swallowed_into_a_favourable_signal() -> None:
    class Broken:
        def evaluate(self, *, state, questions, timeout_s):
            raise DecisionProviderError("timeout")

    result = enrich(_obs(), Broken(), state=STATE, thresholds=THRESHOLDS)
    assert result.outcome == "provider_unavailable"
    assert result.observation.evidence_action is None
