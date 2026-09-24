# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The boundary an external semantic model is admitted through.

`remora.decision_providers` exists so a provider of typed semantic judgment can
inform a decision without being able to create authority. These tests pin that
boundary in three ways.

First, structurally: the evidence record carries no authority-bearing field,
and the projection writes model-signal fields only. The projectable set is
checked against the model-signal class of the lever catalogue rather than
against a copy of it, so the two cannot drift apart.

Second, behaviourally: a provider that answers every question as favourably as
the type system allows still cannot reach ACCEPT under the execution profile.
That reuses the invariant already pinned in
`tests/test_policy_whatif.py::test_execution_profile_never_lets_model_signals_accept`
and extends it to this new class of input, which is the whole reason the
projection refuses deployment facts.

Third, on absence: a provider that fails must not leave the caller with a
favourable default, because absence of evidence and evidence of safety are
different states.

Scope (declared, not exhaustive): the contract, the projection and the
deterministic reference provider. No network adapter is tested here because
none is shipped, and the properties above hold for any adapter since they are
properties of the projection.
"""

from __future__ import annotations

import dataclasses

import pytest

from remora.decision_providers import (
    PROJECTABLE_FIELDS,
    DecisionAnswer,
    DecisionEvidence,
    DecisionProvider,
    DecisionProviderError,
    DecisionQuestion,
    DeterministicDecisionProvider,
    QuestionKind,
    evidence_fingerprint,
    project,
)
from remora.policy.observation import PolicyObservation
from remora.policy.whatif import LEVERS, LeverKind

STATE = {"tool": "crm.refund", "target": "customer:12345", "amount": 250}


def _question(qid: str, kind: QuestionKind = QuestionKind.BOOLEAN, **kw) -> DecisionQuestion:
    return DecisionQuestion(id=qid, kind=kind, instructions=f"is {qid} satisfied", **kw)


# ── the projectable set is the model-signal class, derived not copied ───────


def test_projectable_fields_are_exactly_the_model_signal_levers() -> None:
    from_catalogue = {
        field
        for lever in LEVERS
        if lever.kind is LeverKind.MODEL_SIGNAL
        for field, _ in lever.assignments
    }
    assert PROJECTABLE_FIELDS == from_catalogue, (
        "the fields a provider may write have drifted from the model-signal class of "
        "the lever catalogue. A field that left the class can now be written from "
        "model output without the execution-profile invariant covering it."
    )


def test_no_projectable_field_is_a_deployment_fact() -> None:
    deployment_fields = {
        field
        for lever in LEVERS
        if lever.kind is LeverKind.DEPLOYMENT_FACT
        for field, _ in lever.assignments
    }
    overlap = sorted(PROJECTABLE_FIELDS & deployment_fields)
    assert not overlap, f"provider output could reach deployment facts: {overlap}"


@pytest.mark.parametrize(
    "field",
    ["tool_matches_goal", "expected_effect_matches", "argument_values_grounded",
     "intent_authority_present", "risk_tier", "action_type"],
)
def test_the_tempting_mappings_are_refused(field: str) -> None:
    """The fields a semantic model most naturally seems to answer are the unsafe ones."""
    observation = PolicyObservation(question="refund the customer")
    with pytest.raises(ValueError, match="model signals"):
        project(observation, {field: True})


def test_an_unknown_field_is_refused_rather_than_ignored() -> None:
    observation = PolicyObservation(question="refund the customer")
    with pytest.raises(ValueError):
        project(observation, {"not_a_field": 1})


def test_projection_returns_a_new_observation_and_applies_the_signal() -> None:
    observation = PolicyObservation(question="refund the customer")
    projected = project(observation, {"trust_score": 0.95, "phase": "ordered"})
    assert projected.trust_score == 0.95
    assert projected.phase == "ordered"
    assert observation.trust_score is None, "the input observation was mutated"


# ── the evidence record carries no authority ────────────────────────────────


def test_the_evidence_record_has_no_authority_bearing_field() -> None:
    """A field named here would be the defect, not the feature."""
    forbidden = {
        "grant", "grant_id", "capability", "credential", "credentials", "token",
        "signature", "lease", "nonce", "tenant", "tenant_id", "actor", "actor_id",
        "tool_id", "target", "verified", "approved", "allow", "decision",
    }
    present = {f.name for f in dataclasses.fields(DecisionEvidence)}
    assert not (present & forbidden), f"authority-bearing fields on evidence: {present & forbidden}"


def test_evidence_states_that_it_is_not_authoritative() -> None:
    evidence = DeterministicDecisionProvider({"q": True}).evaluate(
        state=STATE, questions=[_question("q")], timeout_s=1.0
    )
    assert evidence.authoritative is False


def test_the_alias_and_the_resolved_model_are_recorded_separately() -> None:
    """An alias can be repointed without a code change, moving every threshold."""
    names = {f.name for f in dataclasses.fields(DecisionEvidence)}
    assert {"model_alias", "resolved_model"} <= names
    evidence = DeterministicDecisionProvider({"q": True}).evaluate(
        state=STATE, questions=[_question("q")], timeout_s=1.0
    )
    assert evidence.resolved_model
    assert evidence.question_set_version


def test_the_state_hash_distinguishes_different_states() -> None:
    assert evidence_fingerprint(STATE) != evidence_fingerprint({**STATE, "amount": 251})


def test_the_state_hash_is_key_order_independent() -> None:
    assert evidence_fingerprint({"a": 1, "b": 2}) == evidence_fingerprint({"b": 2, "a": 1})


# ── absence of evidence is not evidence of safety ───────────────────────────


def test_a_provider_that_cannot_answer_raises_rather_than_defaulting() -> None:
    provider = DeterministicDecisionProvider({"known": True})
    with pytest.raises(DecisionProviderError):
        provider.evaluate(state=STATE, questions=[_question("unknown")], timeout_s=1.0)


def test_a_failing_provider_leaves_the_observation_untouched() -> None:
    """The caller gets no signal, which is the fail-closed shape."""
    observation = PolicyObservation(question="refund the customer", risk_tier="critical")
    provider = DeterministicDecisionProvider({})
    with pytest.raises(DecisionProviderError):
        provider.evaluate(state=STATE, questions=[_question("q")], timeout_s=0.0)
    assert observation.trust_score is None
    assert observation.phase is None


# ── a maximally favourable provider still cannot reach ACCEPT ───────────────


MAXIMALLY_FAVOURABLE = {
    "trust_score": 0.99,
    "phase": "ordered",
    "evidence_action": "answer",
    "evidence_confidence": 0.99,
    "valid_oracle_count": 32,
    "oracle_failures": 0,
    "temperature": 0.0,
}


@pytest.mark.parametrize(
    "call",
    [
        dict(risk_tier="critical", action_type="production_write", target_environment="prod"),
        dict(risk_tier="high", action_type="financial_transaction", target_environment="prod"),
        dict(risk_tier="medium", action_type="write", target_environment="prod"),
        dict(risk_tier="low", action_type="delete", target_environment="prod"),
    ],
)
def test_an_adversarial_provider_cannot_reach_accept_under_the_execution_profile(call) -> None:
    """Every signal answered as favourably as the type allows, and still not ACCEPT.

    This is the property the whole module is shaped to preserve. A provider
    compromised outright, answering everything in the agent's favour, buys no
    authority it did not already have.
    """
    from remora.policy.decision_engine import DecisionAction, RemoraDecisionEngine

    engine = RemoraDecisionEngine(execution_profile=True)
    observation = project(PolicyObservation(question="do the thing", **call), MAXIMALLY_FAVOURABLE)
    result = engine.decide(observation)
    assert result.action is not DecisionAction.ACCEPT, (
        f"model signals alone reached ACCEPT for {call}; the projection is no longer "
        "confined to the class the execution-profile invariant covers"
    )


def test_favourable_signals_do_reach_the_engine() -> None:
    """The bound above would be worthless if the projection changed nothing.

    Under the execution profile a low-risk staging read moves ABSTAIN to
    VERIFY when every model signal is favourable. The signals are read; what
    they cannot do is reach ACCEPT.
    """
    from remora.policy.decision_engine import DecisionAction, RemoraDecisionEngine

    engine = RemoraDecisionEngine(execution_profile=True)
    call = dict(risk_tier="low", action_type="read", target_environment="staging")
    without = engine.decide(PolicyObservation(question="do the thing", **call))
    with_signals = engine.decide(
        project(PolicyObservation(question="do the thing", **call), MAXIMALLY_FAVOURABLE)
    )
    assert without.action is DecisionAction.ABSTAIN
    assert with_signals.action is DecisionAction.VERIFY, (
        "the projection no longer reaches the engine, so the ACCEPT bound proves nothing"
    )


def test_the_accept_bound_is_a_property_of_the_execution_profile_only() -> None:
    """A declared limit, recorded as a test so nobody discovers it in production.

    Without ``execution_profile=True`` the same favourable signals reach
    ACCEPT on a low-risk staging read. The confinement this module relies on is
    the execution profile, not the projection alone. A deployment that wires a
    decision provider to an engine without the profile has given model output
    the ability to authorise, which is precisely the inversion this module is
    shaped to prevent.
    """
    from remora.policy.decision_engine import DecisionAction, RemoraDecisionEngine

    engine = RemoraDecisionEngine()
    call = dict(risk_tier="low", action_type="read", target_environment="staging")
    with_signals = engine.decide(
        project(PolicyObservation(question="do the thing", **call), MAXIMALLY_FAVOURABLE)
    )
    assert with_signals.action is DecisionAction.ACCEPT, (
        "if this no longer holds the limit has changed, and the module docstring and "
        "the deployment guidance both need updating rather than this assertion relaxing"
    )


# ── the contract itself ─────────────────────────────────────────────────────


def test_the_deterministic_provider_satisfies_the_protocol() -> None:
    assert isinstance(DeterministicDecisionProvider({}), DecisionProvider)


def test_a_choice_question_needs_options() -> None:
    with pytest.raises(ValueError):
        DecisionQuestion(id="route", kind=QuestionKind.CHOICE, instructions="pick")
    with pytest.raises(ValueError):
        DecisionQuestion(
            id="route", kind=QuestionKind.CHOICE, instructions="pick", options=("only",)
        )


def test_a_non_choice_question_may_not_declare_options() -> None:
    with pytest.raises(ValueError):
        DecisionQuestion(
            id="risk", kind=QuestionKind.SCORE, instructions="how risky", options=("a", "b")
        )


def test_answers_are_addressable_by_question_id() -> None:
    evidence = DeterministicDecisionProvider({"a": True, "b": 0.5}).evaluate(
        state=STATE,
        questions=[_question("a"), _question("b", QuestionKind.SCORE)],
        timeout_s=1.0,
    )
    assert isinstance(evidence.answer("a"), DecisionAnswer)
    assert evidence.answer("b").value == 0.5
    assert evidence.answer("absent") is None


def test_the_same_state_and_answers_fingerprint_identically() -> None:
    provider = DeterministicDecisionProvider({"q": True})
    first = provider.evaluate(state=STATE, questions=[_question("q")], timeout_s=1.0)
    second = provider.evaluate(state=dict(reversed(list(STATE.items()))),
                               questions=[_question("q")], timeout_s=1.0)
    assert first.state_hash == second.state_hash
    assert first.response_hash == second.response_hash
