# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Property-based invariant testing of the decision engine's hard guards.

The example suite pins hand-picked cases; these properties search a
declared signal domain — seven signal groups, NOT the full
PolicyObservation surface — for counterexamples: critical risk never
ACCEPTed, a production target with unknown risk never ACCEPTed, and a
detected adversarial pattern always ESCALATEd, within the generated
domain. No counterexample found in the stated example counts; searched
validation over a declared strategy domain, not formal proof
(proof-depth track, slice 2).
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction

_ENGINE = RemoraDecisionEngine()

_unit = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
_signal_kwargs = st.fixed_dictionaries({
    "phase": st.sampled_from([None, "ordered", "critical", "disordered"]),
    "trust_score": st.one_of(st.none(), _unit),
    "weighted_support": st.one_of(st.none(), _unit),
    "evidence_action": st.sampled_from([None, "answer", "verify"]),
    "evidence_confidence": st.one_of(st.none(), _unit),
    "action_type": st.sampled_from(
        [None, "read", "write", "production_write", "destructive_write"]),
    "domain": st.sampled_from([None, "infrastructure", "finance", "general"]),
})


@settings(max_examples=100, deadline=None)
@given(_signal_kwargs)
def test_critical_risk_never_accepts(signals) -> None:
    obs = PolicyObservation(question="prop: critical action",
                            risk_tier="critical",
                            target_environment="prod", **signals)
    report = _ENGINE.decide(obs)
    assert report.action is not DecisionAction.ACCEPT, (
        f"critical risk ACCEPTed with signals={signals}, "
        f"reasons={[r.value for r in report.reasons]}")


@settings(max_examples=100, deadline=None)
@given(_signal_kwargs)
def test_production_unknown_risk_never_accepts(signals) -> None:
    obs = PolicyObservation(question="prop: unknown risk in prod",
                            risk_tier=None,
                            target_environment="prod", **signals)
    report = _ENGINE.decide(obs)
    assert report.action is not DecisionAction.ACCEPT, (
        f"prod+unknown-risk ACCEPTed with signals={signals}, "
        f"reasons={[r.value for r in report.reasons]}")


@settings(max_examples=100, deadline=None)
@given(_signal_kwargs,
       st.sampled_from([None, "low", "medium", "high", "critical"]))
def test_detected_adversarial_always_escalates(signals, risk_tier) -> None:
    obs = PolicyObservation(question="prop: injected instruction",
                            risk_tier=risk_tier,
                            target_environment="prod",
                            adversarial_detected=True, **signals)
    report = _ENGINE.decide(obs)
    assert report.action is DecisionAction.ESCALATE, (
        f"adversarial_detected did not ESCALATE (got {report.action}) with "
        f"risk={risk_tier}, signals={signals}")
