# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The semantic narrowing guard may reduce authority and never create it (issue #753, step 2).

Library only: these tests pin the contract a future pre-policy wiring has to
use. The guard is refused for an uncalibrated or unpinned profile, never calls
the provider for a tenant that did not opt in or a call without server-resolved
intent, reports provider failure explicitly and never as clean, and its only
possible effect on an observation is raising a narrowing flag.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remora.decision_providers import NARROWING_FLAGS, DecisionAnswer, DecisionEvidence, DecisionProviderError
from remora.decision_providers.narrowing import (
    GuardActivation,
    GuardOutcome,
    SemanticNarrowingGuard,
)
from remora.decision_providers.questions import INJECTION_QUESTIONS_V2_1, QUESTION_SET_VERSION_V2_1
from remora.policy import PolicyObservation

MODEL = "jev-1.13.0"
THRESHOLDS = {q: 0.8 for q in INJECTION_QUESTIONS_V2_1}
CALIBRATION = {"status": "calibrated", "study": "fixture-study", "corpus_sha256": "a" * 64,
               "language": "nb", "vertical": "isp", "model_version": MODEL,
               "question_set_version": QUESTION_SET_VERSION_V2_1, "thresholds": dict(THRESHOLDS)}


def _activation(**over: Any) -> GuardActivation:
    base: dict[str, Any] = dict(tenant="acme", model_version=MODEL, question_set_version=QUESTION_SET_VERSION_V2_1,
                                thresholds=dict(THRESHOLDS), calibration=dict(CALIBRATION), timeout_ms=1500,
                                execution_profile=True)
    base.update(over)
    return GuardActivation(**base)


class _Provider:
    """Answers whatever it is told to, as a malicious or broken provider might."""

    provider_name = "fake"

    def __init__(self, answers: dict[str, Any] | None = None, *, model: str = MODEL,
                 qset: str = QUESTION_SET_VERSION_V2_1, raises: BaseException | None = None) -> None:
        self.answers, self.model, self.qset, self.raises = answers or {}, model, qset, raises
        self.calls: list[tuple[str, ...]] = []

    def evaluate(self, *, state, questions, timeout_s):
        self.calls.append(tuple(q.id for q in questions))
        if self.raises:
            raise self.raises
        answers = tuple(DecisionAnswer(question_id=k, value=v) for k, v in self.answers.items())
        return DecisionEvidence(provider="fake", model_alias="fake", resolved_model=self.model,
                                question_set_version=self.qset, state_hash="s", response_hash="r",
                                answers=answers, latency_ms=1.0)


def _obs(**over: Any) -> PolicyObservation:
    base: dict[str, Any] = dict(question="reset the router for customer 4", proposed_tool_name="reset_router",
                                risk_tier="medium", action_type="write", schema_valid=True,
                                target_environment="prod")
    base.update(over)
    return PolicyObservation(**base)


def _run(provider: _Provider, *, tenant: str = "acme", intent: bool | None = True, obs=None):
    guard = SemanticNarrowingGuard({"acme": _activation()}, provider)
    return guard.evaluate(obs or _obs(), tenant=tenant, state={"operator_request": "x"},
                          intent_authority_present=intent)


# ── activation ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("over, match", [
    (dict(execution_profile=False), "execution profile"),
    (dict(model_version="jev-latest"), "pinned version"),
    (dict(model_version="jev"), "pinned version"),
    (dict(question_set_version="remora-semantic-v2"), "not allowed"),
    (dict(thresholds={"injection_override": 0.8}), "exactly"),
    (dict(thresholds={**THRESHOLDS, "intent_match": 0.5}), "exactly"),
    (dict(thresholds={q: 1.0 for q in INJECTION_QUESTIONS_V2_1}), "strictly between"),
    (dict(timeout_ms=0), "timeout"),
    (dict(timeout_ms=60_000), "timeout"),
    (dict(calibration={**CALIBRATION, "status": "uncalibrated"}), "uncalibrated"),
    (dict(calibration={k: v for k, v in CALIBRATION.items() if k != "corpus_sha256"}), "corpus_sha256"),
    (dict(calibration={k: v for k, v in CALIBRATION.items() if k != "study"}), "study"),
    (dict(calibration={**CALIBRATION, "corpus_sha256": "abc"}), "SHA-256"),
    (dict(calibration={**CALIBRATION, "model_version": "jev-1.12.0"}), "model the calibration"),
    (dict(calibration={**CALIBRATION, "question_set_version": "remora-semantic-v2"}), "question set differs"),
    (dict(calibration={**CALIBRATION, "thresholds": {q: 0.5 for q in INJECTION_QUESTIONS_V2_1}}), "thresholds differ"),
])
def test_an_unsafe_activation_is_refused(over, match) -> None:
    with pytest.raises(ValueError, match=match):
        _activation(**over)


def test_activations_are_keyed_by_their_own_tenant() -> None:
    with pytest.raises(ValueError, match="names tenant"):
        SemanticNarrowingGuard({"other": _activation()}, _Provider())


# ── when the provider is not called ─────────────────────────────────────────

@pytest.mark.parametrize("tenant, intent, reason", [
    ("someone-else", True, "tenant_not_opted_in"),
    ("acme", None, "no_server_resolved_intent"),
    ("acme", False, "no_server_resolved_intent"),
])
def test_no_opt_in_or_no_resolved_intent_means_no_call(tenant, intent, reason) -> None:
    p = _Provider({q: 0.99 for q in INJECTION_QUESTIONS_V2_1})
    r = _run(p, tenant=tenant, intent=intent)
    assert (r.outcome, r.reason) == (GuardOutcome.NOT_EVALUATED, reason)
    assert p.calls == []
    assert r.observation == _obs()


def test_only_the_injection_questions_are_asked() -> None:
    p = _Provider({q: 0.1 for q in INJECTION_QUESTIONS_V2_1})
    _run(p)
    assert p.calls == [INJECTION_QUESTIONS_V2_1]


# ── failure is explicit and never clean ─────────────────────────────────────

@pytest.mark.parametrize("provider, reason", [
    (_Provider(raises=DecisionProviderError("down")), "provider_error:DecisionProviderError"),
    (_Provider(raises=TimeoutError()), "provider_error:TimeoutError"),
    (_Provider({q: 0.99 for q in INJECTION_QUESTIONS_V2_1}, model="jev-1.14.0"), "model_version_mismatch"),
    (_Provider({q: 0.99 for q in INJECTION_QUESTIONS_V2_1}, qset="remora-semantic-v2"), "question_set_mismatch"),
    (_Provider({**{q: 0.1 for q in INJECTION_QUESTIONS_V2_1}, "intent_match": 0.99}),
     "answers_outside_the_declared_questions"),
])
def test_an_unavailable_or_untrustworthy_provider_is_reported_and_never_clean(provider, reason) -> None:
    r = _run(provider)
    assert r.outcome is GuardOutcome.PROVIDER_UNAVAILABLE
    assert r.reason == reason
    assert r.clean is False and r.provider_available is False
    assert r.observation == _obs()


def test_no_narrowing_is_not_a_clean_bill() -> None:
    r = _run(_Provider({q: 0.1 for q in INJECTION_QUESTIONS_V2_1}))
    assert r.outcome is GuardOutcome.NO_NARROWING
    assert r.clean is False and r.provider_available is True
    assert r.observation == _obs()


# ── the only effect is narrowing ────────────────────────────────────────────

def test_an_injection_answer_past_its_threshold_raises_the_flag_and_nothing_else() -> None:
    r = _run(_Provider({**{q: 0.1 for q in INJECTION_QUESTIONS_V2_1}, "injection_override": 0.9}))
    assert r.outcome is GuardOutcome.NARROWED
    assert r.flags_raised == ("adversarial_detected",)
    assert r.observation.adversarial_detected is True
    assert r.observation == _obs(adversarial_detected=True)


def test_the_threshold_is_inclusive() -> None:
    """At the calibrated cut exactly, the flag is raised; just below, it is not."""
    at = _run(_Provider({**{q: 0.0 for q in INJECTION_QUESTIONS_V2_1}, "injection_instruction": 0.8}))
    below = _run(_Provider({**{q: 0.0 for q in INJECTION_QUESTIONS_V2_1}, "injection_instruction": 0.7999}))
    assert at.outcome is GuardOutcome.NARROWED
    assert below.outcome is GuardOutcome.NO_NARROWING


def test_a_raised_flag_is_never_lowered() -> None:
    raised = _obs(adversarial_detected=True)
    r = _run(_Provider({q: 0.0 for q in INJECTION_QUESTIONS_V2_1}), obs=raised)
    assert r.observation.adversarial_detected is True


_answer_value = st.one_of(st.floats(allow_nan=True, allow_infinity=True), st.booleans(),
                          st.text(max_size=5), st.integers(-3, 3))


@settings(max_examples=200, deadline=None)
@given(answers=st.dictionaries(st.sampled_from(INJECTION_QUESTIONS_V2_1), _answer_value),
       start_flag=st.booleans())
def test_whatever_a_provider_answers_the_only_change_is_raising_a_narrowing_flag(answers, start_flag) -> None:
    before = _obs(adversarial_detected=start_flag)
    try:
        provider = _Provider(answers)
        r = _run(provider, obs=before)
    except (ValueError, TypeError):
        return  # the answer type itself refused the value; nothing reached the observation
    for name in ("adversarial_detected", "evidence_action", "evidence_confidence", "trust_score",
                 "tool_matches_goal", "expected_effect_matches", "argument_values_grounded"):
        old, new = getattr(before, name), getattr(r.observation, name)
        if old != new:
            assert name in NARROWING_FLAGS and new is True, name
    assert r.clean is False
    for v in r.answers.values():
        assert math.isfinite(v) and 0.0 <= v <= 1.0


def test_a_maximally_favourable_provider_cannot_reach_accept_through_the_guard() -> None:
    from remora.policy.decision_engine import RemoraDecisionEngine
    from remora.policy.report import DecisionAction

    engine = RemoraDecisionEngine(execution_profile=True)
    r = _run(_Provider({q: 0.0 for q in INJECTION_QUESTIONS_V2_1}))
    assert r.observation == _obs()  # nothing favourable was written
    assert engine.decide(r.observation).action is engine.decide(_obs()).action
    narrowed = _run(_Provider({q: 1.0 for q in INJECTION_QUESTIONS_V2_1})).observation
    assert engine.decide(narrowed).action is not DecisionAction.ACCEPT


# ── not wired ───────────────────────────────────────────────────────────────

def test_the_guard_is_not_wired_into_any_live_path() -> None:
    """Step 3 of #753 waits for a calibrated profile. Until then nothing live imports the guard."""
    root = Path(__file__).resolve().parents[1]
    for base in ("servers", "remora/execution", "remora/policy", "remora/enforcement"):
        for path in (root / base).rglob("*.py"):
            assert "decision_providers.narrowing" not in path.read_text(encoding="utf-8"), path
