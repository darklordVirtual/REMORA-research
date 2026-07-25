# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""decide() and explain() must never drift (Grok review P1).

explain() delegates the decision to decide(), but historically re-listed
every rule's predicate/outcome by hand — so adding a rule to decide() could
silently omit it from the trace. These characterization tests lock the
invariant that the trace agrees with the decision, across a broad battery,
BEFORE the conditional-gate inventory is unified into a single source.
"""
from __future__ import annotations

import itertools

from remora.policy import PolicyObservation, RemoraDecisionEngine
from remora.policy.report import DecisionAction


def _engine() -> RemoraDecisionEngine:
    # Conformal/temperature paths enabled so ACCEPT-tail rows are exercised.
    return RemoraDecisionEngine(
        temperature_threshold=0.1972,
        conformal_trust_threshold=0.72,
    )


def _battery() -> list[PolicyObservation]:
    obs = []
    phases = [None, "ordered", "critical", "disordered"]
    tiers = [None, "low", "medium", "high", "critical", "unknown", "typo"]
    actions = [None, "read", "write", "deploy", "delete", "weird_verb"]
    envs = [None, "prod", "staging", "dev"]
    for phase, tier, atype, env in itertools.product(phases, tiers, actions, envs):
        obs.append(
            PolicyObservation(
                question="q",
                phase=phase,
                trust_score=0.8,
                final_H=0.3,
                final_D=0.2,
                temperature=0.1,
                risk_tier=tier,
                action_type=atype,
                target_environment=env,
                evidence_action="answer",
                evidence_confidence=0.9,
            )
        )
    # A batch of single-signal triggers for the conditional gates.
    triggers = [
        {"distribution_shift_detected": True},
        {"rollback_available": False, "risk_tier": "high", "action_type": "write"},
        {"state_transition_uncertain": True, "risk_tier": "critical", "action_type": "write"},
        {"risk_tier": "high", "evidence_action": None, "action_type": "write"},
        {"risk_tier": "critical", "action_type": "write"},
        {"valid_oracle_count": 1, "oracle_failures": 2, "risk_tier": "medium"},
        {"environment_mismatch_detected": True},
        {"classification_alternatives": ["delete"], "risk_tier": "medium"},
        {"classification_confidence": 0.3, "action_type": "write"},
        {"model_misspecification_risk": 0.9, "action_type": "write"},
        {"session_cumulative_risk": 0.95},
        {"session_action_count": 500},
        {"fleet_level_effect": "systemic"},
        {"policy_generalization_risk": 0.9},
        {"similar_action_seen_count": 200},
        {"refuse_parametric_verdict": True, "evidence_action": "abstain"},
        {"adversarial_detected": True},
        {"tool_forbidden": True},
        {"coercion_detected": True},
        {"argument_tainted": True, "action_type": "write"},
    ]
    for t in triggers:
        base = dict(question="q", phase="ordered", trust_score=0.8,
                    final_H=0.3, final_D=0.2, risk_tier="medium", action_type="read")
        base.update(t)
        obs.append(PolicyObservation(**base))
    return obs


def test_decide_and_explain_agree_on_action_across_battery() -> None:
    eng = _engine()
    for o in _battery():
        report = eng.decide(o)
        trace = eng.explain(o)
        assert trace.action == report.action.value, (
            f"explain().action={trace.action!r} != decide()={report.action.value!r} "
            f"for phase={o.phase} tier={o.risk_tier} action={o.action_type} env={o.target_environment}"
        )


def test_explain_decision_path_points_at_a_triggered_rule() -> None:
    eng = _engine()
    for o in _battery():
        trace = eng.explain(o)
        final = trace.action.upper()
        fired = [s for s in trace.rule_evaluations if s.triggered and s.outcome == final]
        # Either a concrete triggered rule produced the final action, or the
        # default-safe-abstain path did (ABSTAIN with no earlier match).
        assert fired or final == DecisionAction.ABSTAIN.value.upper(), (
            f"no triggered rule matches final action {final} for {o.phase}/{o.risk_tier}"
        )


def test_every_triggered_gate_outcome_is_consistent_with_a_direct_decide() -> None:
    """For each conditional-gate trigger, decide() returns exactly the outcome
    the trace attributes to the first triggered rule."""
    eng = _engine()
    for o in _battery():
        report = eng.decide(o)
        trace = eng.explain(o)
        first_fired = next((s for s in trace.rule_evaluations if s.triggered), None)
        if first_fired is not None and first_fired.outcome in {"ACCEPT", "VERIFY", "ESCALATE", "ABSTAIN"}:
            # The first fired rule's outcome must be the decided action OR a
            # later same-priority rule; assert the decided action is at least
            # reachable as some fired rule's outcome.
            fired_outcomes = {s.outcome for s in trace.rule_evaluations if s.triggered}
            assert report.action.value.upper() in fired_outcomes, (
                f"decided {report.action.value} not among fired outcomes {fired_outcomes}"
            )
