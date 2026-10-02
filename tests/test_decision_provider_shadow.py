# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Shadow mode records what a provider would have done and changes nothing.

Scope (declared, not exhaustive): the evaluation and the local sink, with
deterministic providers. Nothing here is evidence about a live model.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from remora.decision_providers import (
    DecisionProviderError,
    DeterministicDecisionProvider,
)
from remora.decision_providers.enrich import SemanticThresholds, semantic_state_v2
from remora.decision_providers.questions import QUESTION_SET_VERSION_V2_1, REMORA_QUESTIONS_V2_1
from remora.decision_providers.shadow import JsonlShadowSink, shadow_evaluate
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation

THRESHOLDS = SemanticThresholds(
    intent_match=0.85, target_matches_request=0.85, possible_injection=0.5, scope_drift=0.5
)
STATE = semantic_state_v2(
    operator_request="Shut down port ber-sw-02/0/7 per incident I-77.",
    tool_name="network.shutdown_port",
    arguments={"port": "ber-sw-02/0/7"},
    untrusted_content={"alert": "Broadcast storm on ber-sw-02/0/7."},
)
CLEAN = {q.id: 0.02 for q in REMORA_QUESTIONS_V2_1} | {
    "intent_match": 0.95, "target_matches_request": 0.95, "scope_drift": 0.05,
    "action_reversibility": 0.2, "semantic_risk": 1.0,
}


def _obs() -> PolicyObservation:
    return PolicyObservation(
        question="shut down the flooding port", risk_tier="high",
        action_type="configuration_change", target_environment="prod",
    )


def _run(provider, *, engine=None, observation=None):
    engine = engine or RemoraDecisionEngine(execution_profile=True)
    observation = observation or _obs()
    actual = engine.decide(observation).action
    record = shadow_evaluate(
        observation, actual, provider, engine=engine, state=STATE, thresholds=THRESHOLDS,
        questions=REMORA_QUESTIONS_V2_1, proposal_id="p-1",
    )
    return observation, actual, record


def _provider(**answers):
    return DeterministicDecisionProvider(CLEAN | answers, question_set_version=QUESTION_SET_VERSION_V2_1)


def test_the_observation_is_left_exactly_as_it_was() -> None:
    observation = _obs()
    before = copy.deepcopy(observation)
    _run(_provider(injection_override=0.9), observation=observation)
    assert observation == before


def test_an_injection_answer_shows_as_a_would_change_escalation() -> None:
    _obs_, actual, record = _run(_provider(injection_override=0.9))
    assert actual.name == "VERIFY"
    assert record.shadow_action == "ESCALATE"
    assert record.would_change is True
    assert record.outcome == "signals_applied"
    assert record.answers["injection_override"]["value"] == 0.9


def test_a_clean_answer_set_does_not_change_the_action() -> None:
    _obs_, actual, record = _run(_provider())
    assert record.shadow_action == actual.name
    assert record.would_change is False
    assert record.resolved_model is not None
    assert record.authoritative is False


def test_a_provider_failure_becomes_an_unavailable_record() -> None:
    _obs_, actual, record = _run(DeterministicDecisionProvider({}))
    assert record.outcome == "provider_unavailable"
    assert record.shadow_action == actual.name
    assert record.error is None


class _Exploding:
    provider_name = "boom"

    def evaluate(self, **_kw):
        raise RuntimeError("unexpected")


class _ExplodingEngine:
    def decide(self, _obs):
        raise ValueError("engine fault")


def test_an_unexpected_exception_is_recorded_not_raised() -> None:
    # enrich() absorbs any provider exception as provider_unavailable, so the
    # deterministic decision stands and the counterfactual equals the actual.
    _obs_, actual, record = _run(_Exploding())
    assert record.error is None
    assert record.outcome == "provider_unavailable"
    assert any("RuntimeError: unexpected" in note for note in record.notes)
    assert record.shadow_action == actual.name
    assert record.would_change is False


def test_an_engine_fault_in_the_counterfactual_is_recorded_not_raised() -> None:
    record = shadow_evaluate(
        _obs(), "VERIFY", _provider(), engine=_ExplodingEngine(), state=STATE,
        thresholds=THRESHOLDS, questions=REMORA_QUESTIONS_V2_1, proposal_id="p-2",
    )
    assert record.error == "ValueError: engine fault"
    assert record.actual_action == "VERIFY"


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_the_counterfactual_never_reaches_accept_under_the_execution_profile(value: float) -> None:
    answers = {k: value for k in CLEAN if k not in ("action_reversibility", "semantic_risk")}
    for tier, action_type in (("low", "read"), ("medium", "write"), ("high", "configuration_change")):
        observation = PolicyObservation(
            question="q", risk_tier=tier, action_type=action_type, target_environment="prod"
        )
        _o, _a, record = _run(_provider(**answers), observation=observation)
        assert record.shadow_action != "ACCEPT"


def test_the_sink_writes_one_json_line_per_record(tmp_path: Path) -> None:
    sink = JsonlShadowSink(tmp_path / "shadow" / "records.jsonl")
    for provider in (_provider(), _provider(injection_override=0.9)):
        sink.write(_run(provider)[2])
    lines = (tmp_path / "shadow" / "records.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["would_change"] for line in lines] == [False, True]
    assert sink.failed_writes == 0


def test_a_sink_write_failure_is_counted_not_raised(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    sink = JsonlShadowSink(blocker / "records.jsonl")
    sink.write(_run(_provider())[2])
    assert sink.failed_writes == 1


def test_decision_provider_error_is_not_special_cased_away() -> None:
    """enrich maps DecisionProviderError to provider_unavailable; shadow keeps that."""
    class _Refuses:
        provider_name = "refuses"

        def evaluate(self, **_kw):
            raise DecisionProviderError("402")

    _o, _a, record = _run(_Refuses())
    assert record.outcome == "provider_unavailable"
    assert any("402" in note for note in record.notes)
