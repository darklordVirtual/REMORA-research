"""explain()/decide() parity regression (2026-07-02 external review).

``explain()`` maintains a hand-written mirror of ``decide()``'s rule ladder.
The review found it had drifted: rules were missing (oracle quorum, unknown
risk tier, GAP A+C, schema floor, ambiguity penalty), guards were missing
(counterfactual/contradiction on the ACCEPT paths), the tainted/counterfactual
ordering was inverted, and ordered_high_trust used raw instead of
ambiguity-adjusted trust.

The structural invariant enforced here: ``decide()`` returns at the FIRST rule
whose predicate fires, so — with identical predicates in identical order — the
first triggered step in ``explain()``'s trace must carry the same outcome as
``decide()``'s action, for every observation. A grid sweep over the
observation space plus targeted drift cases keeps the two ladders locked.
"""
from __future__ import annotations

import itertools

import pytest

from remora.policy import PolicyObservation, RemoraDecisionEngine


def _obs(**kwargs) -> PolicyObservation:
    return PolicyObservation(question="parity probe", **kwargs)


def _first_triggered_outcome(trace) -> str | None:
    for step in trace.rule_evaluations:
        if step.triggered:
            return step.outcome
    return None


def _assert_parity(engine: RemoraDecisionEngine, obs: PolicyObservation) -> None:
    report = engine.decide(obs)
    trace = engine.explain(obs)
    assert trace.action == report.action.value, (
        f"trace.action={trace.action!r} != decide={report.action.value!r} for {obs}"
    )
    predicted = _first_triggered_outcome(trace)
    assert predicted == report.action.value.upper(), (
        f"first triggered rule predicts {predicted!r} but decide() returned "
        f"{report.action.value.upper()!r} for {obs}; "
        f"decision_path={trace.decision_path!r}"
    )


ENGINES = {
    "default": RemoraDecisionEngine(),
    "calibrated": RemoraDecisionEngine(
        temperature_threshold=0.30,
        conformal_trust_threshold=0.72,
    ),
    "mondrian": RemoraDecisionEngine(
        conformal_phase_thresholds={"ordered": 0.80, "critical": 0.95},
    ),
}

PHASES = ["ordered", "critical", "disordered", None]
RISK_TIERS = ["low", "high", "critical", "unknown", None]
TRUST = [None, 0.1, 0.5, 0.73, 0.95]
EVIDENCE = [
    {"evidence_action": None, "evidence_confidence": None},
    {"evidence_action": "answer", "evidence_confidence": 0.9},
    {"evidence_action": "answer", "evidence_confidence": 0.5},
]


@pytest.mark.parametrize("engine_name", sorted(ENGINES))
def test_parity_grid(engine_name: str) -> None:
    """Sweep phase × risk_tier × trust × evidence for each engine config."""
    engine = ENGINES[engine_name]
    for phase, tier, trust, ev in itertools.product(
        PHASES, RISK_TIERS, TRUST, EVIDENCE
    ):
        obs = _obs(
            phase=phase,
            risk_tier=tier,
            trust_score=trust,
            **ev,
        )
        _assert_parity(engine, obs)


@pytest.mark.parametrize("engine_name", sorted(ENGINES))
@pytest.mark.parametrize(
    "fields",
    [
        # Hard blocks and floors
        {"adversarial_detected": True, "trust_score": 1.0, "phase": "ordered"},
        {"schema_valid": False, "action_type": "write"},
        {"schema_valid": None, "action_type": "write", "phase": "ordered",
         "trust_score": 0.9},
        {"tool_forbidden": True},
        {"coercion_detected": True},
        {"blackmail_pattern_detected": True},
        # Drift case: tainted + failed counterfactual — decide() escalates on
        # the counterfactual BEFORE the tainted VERIFY floor
        {"argument_tainted": True, "counterfactual_passed": False},
        {"argument_tainted": True, "phase": "ordered", "trust_score": 0.9},
        # Contradictions with and without cycles
        {"evidence_contradictions": 2, "contradiction_cycles": 1},
        {"evidence_contradictions": 2, "contradiction_cycles": 0},
        # Rollback/state-transition precede the production-write matrix
        {"rollback_available": False, "risk_tier": "high",
         "action_type": "write", "target_environment": "production"},
        {"state_transition_uncertain": True, "risk_tier": "high"},
        # Oracle quorum
        {"valid_oracle_count": 1, "oracle_failures": 2, "phase": "ordered",
         "trust_score": 0.9},
        # Unknown risk tier with mutating action / prod env
        {"risk_tier": "typo-tier", "action_type": "write"},
        {"risk_tier": None, "target_environment": "production"},
        # GAP A+C: high risk, evidence set, counterfactual never ran
        {"risk_tier": "high", "evidence_action": "answer",
         "evidence_confidence": 0.9, "counterfactual_passed": None},
        # Drift case: evidence-supported ACCEPT requires counterfactual not-failed
        {"evidence_action": "answer", "evidence_confidence": 0.9,
         "phase": "ordered", "counterfactual_passed": False},
        # Evidence-supported in critical phase: trust decides ACCEPT vs VERIFY
        {"evidence_action": "answer", "evidence_confidence": 0.9,
         "phase": "critical", "trust_score": 0.9},
        {"evidence_action": "answer", "evidence_confidence": 0.9,
         "phase": "critical", "trust_score": 0.3},
        # Drift case: ordered high trust with oracle disagreement — decide()
        # uses ambiguity-adjusted trust, which can drop below 0.72
        {"phase": "ordered", "trust_score": 0.73, "final_H": 0.9,
         "final_D": 0.9, "valid_oracle_count": 3},
        {"phase": "ordered", "trust_score": 0.95},
        # Session / fleet gates
        {"session_cumulative_risk": 0.9},
        {"session_action_count": 150},
        {"fleet_level_effect": "systemic"},
        {"policy_generalization_risk": 0.8},
        {"similar_action_seen_count": 60},
        # Misspecification gates
        {"environment_mismatch_detected": True},
        {"target_environment": "production", "environment_confidence": 0.5,
         "action_type": "write"},
        {"classification_alternatives": ["prod_deploy"], "schema_valid": True},
        {"classification_confidence": 0.4, "action_type": "write"},
        {"model_misspecification_risk": 0.7, "action_type": "write"},
        # Abstain paths
        {"phase": "disordered"},
        {"trust_score": 0.1},
        {},
    ],
)
def test_parity_targeted(engine_name: str, fields: dict) -> None:
    """Targeted cases including every drift the 2026-07-02 review found."""
    _assert_parity(ENGINES[engine_name], _obs(**fields))


def test_marginal_conformal_never_accepts_critical_phase() -> None:
    """Phase-blind conformal ACCEPT must not fire in the critical phase.

    Trust anti-correlates with correctness there (CLAIM-005), so a
    critical-phase item above the marginal trust threshold must fall through
    to the critical-phase VERIFY, not ACCEPT.
    """
    engine = RemoraDecisionEngine(conformal_trust_threshold=0.72)
    obs = _obs(phase="critical", trust_score=0.95)
    report = engine.decide(obs)
    assert report.action.value == "verify"
    _assert_parity(engine, obs)


def test_marginal_conformal_still_accepts_ordered_phase() -> None:
    engine = RemoraDecisionEngine(conformal_trust_threshold=0.72)
    obs = _obs(phase="ordered", trust_score=0.95)
    report = engine.decide(obs)
    assert report.action.value == "accept"
    _assert_parity(engine, obs)
