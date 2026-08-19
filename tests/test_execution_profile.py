# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Issue #35: the execution profile structurally forbids probabilistic ACCEPT.

The /v1/execution safety previously depended on the observation builder
leaving trust/phase/evidence fields None. With execution_profile=True the
invariant is structural: even a fully-populated high-trust observation can
never reach ACCEPT through a probabilistic path — those conclusions route to
VERIFY with an explicit reason. Deterministic opt-in ACCEPTs (grounded read,
low consequence) are registry/state facts and stay available.
"""
from __future__ import annotations

import pytest

from remora.policy import PolicyObservation
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.report import DecisionAction, DecisionReason

#: Observations that reach ACCEPT through each probabilistic path in the
#: default profile.
PROBABILISTIC_ACCEPT_CASES = {
    "marginal_conformal": PolicyObservation(
        question="probe", trust_score=0.99, phase="ordered"),
    "evidence_supported": PolicyObservation(
        question="probe", evidence_action="answer", evidence_confidence=0.99,
        phase="ordered"),
    "ordered_high_trust": PolicyObservation(
        question="probe", phase="ordered", trust_score=0.95),
}


@pytest.mark.parametrize("name", sorted(PROBABILISTIC_ACCEPT_CASES))
def test_default_profile_accepts_probabilistically(name: str) -> None:
    """Characterize the precondition: these cases DO accept without the
    profile — otherwise the profile test below proves nothing."""
    report = RemoraDecisionEngine().decide(PROBABILISTIC_ACCEPT_CASES[name])
    assert report.action is DecisionAction.ACCEPT, (name, report.reasons)


@pytest.mark.parametrize("name", sorted(PROBABILISTIC_ACCEPT_CASES))
def test_execution_profile_never_accepts_probabilistically(name: str) -> None:
    engine = RemoraDecisionEngine(execution_profile=True)
    report = engine.decide(PROBABILISTIC_ACCEPT_CASES[name])
    assert report.action is DecisionAction.VERIFY, (name, report.action)
    assert DecisionReason.EXECUTION_PROFILE_PROBABILISTIC_VERIFY in report.reasons


def test_temperature_accept_also_gated() -> None:
    """The temperature path needs an explicit threshold (default None since
    the temperature hypothesis was falsified); with one configured, the
    profile still forbids the ACCEPT."""
    obs = PolicyObservation(question="probe", temperature=0.01, phase="ordered")
    assert RemoraDecisionEngine(temperature_threshold=0.3).decide(obs).action \
        is DecisionAction.ACCEPT
    report = RemoraDecisionEngine(
        temperature_threshold=0.3, execution_profile=True
    ).decide(obs)
    assert report.action is DecisionAction.VERIFY
    assert DecisionReason.EXECUTION_PROFILE_PROBABILISTIC_VERIFY in report.reasons


def test_mondrian_conformal_also_gated() -> None:
    engine = RemoraDecisionEngine(
        execution_profile=True,
        conformal_phase_thresholds={"ordered": 0.5},
    )
    report = engine.decide(
        PolicyObservation(question="probe", phase="ordered", trust_score=0.9)
    )
    assert report.action is DecisionAction.VERIFY
    assert DecisionReason.EXECUTION_PROFILE_PROBABILISTIC_VERIFY in report.reasons


def test_deterministic_grounded_read_accept_survives_the_profile() -> None:
    engine = RemoraDecisionEngine(execution_profile=True,
                                  grounded_read_accept=True)
    baseline = RemoraDecisionEngine(grounded_read_accept=True)
    obs = PolicyObservation(
        question="read sensor",
        proposed_tool_name="read_sensor",
        risk_tier="low",
        action_type="read",
        schema_valid=True,
        intent_authority_present=True,
        tool_matches_goal=True,
        expected_effect_matches=True,
        argument_values_supported=True,
        argument_values_grounded=True,
    )
    profile_report = engine.decide(obs)
    baseline_report = baseline.decide(obs)
    # Whatever the deterministic path concludes, the profile must not change
    # it — it only gates the probabilistic ACCEPTs.
    assert profile_report.action is baseline_report.action
    assert DecisionReason.EXECUTION_PROFILE_PROBABILISTIC_VERIFY \
        not in profile_report.reasons


def test_explain_trace_matches_profiled_decision() -> None:
    engine = RemoraDecisionEngine(execution_profile=True)
    obs = PROBABILISTIC_ACCEPT_CASES["ordered_high_trust"]
    report = engine.decide(obs)
    trace = engine.explain(obs)
    assert trace.action == report.action.value == "verify"
    assert "execution_profile_probabilistic_verify" in trace.reasons


def test_execution_api_engine_runs_the_profile(monkeypatch) -> None:
    import servers.execution_api as exec_mod

    monkeypatch.delenv("REMORA_LOW_CONSEQUENCE_ACCEPT", raising=False)
    monkeypatch.delenv("REMORA_GROUNDED_READ_ACCEPT", raising=False)
    assert exec_mod._engine_from_env().execution_profile is True
