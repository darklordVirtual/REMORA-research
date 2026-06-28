# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for P1-P3 misspecification gates in RemoraDecisionEngine."""
from __future__ import annotations

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason

ENGINE = RemoraDecisionEngine()


def _obs(**kwargs) -> PolicyObservation:
    """Helper: ordered-phase, medium-risk write action — would normally reach ACCEPT paths."""
    defaults = dict(
        question="test action",
        phase="ordered",
        trust_score=0.85,
        risk_tier="medium",
        action_type="write",
        target_environment="prod",
        schema_valid=True,  # tests assume schema validated; None default → VERIFY floor fires
    )
    defaults.update(kwargs)
    return PolicyObservation(**defaults)


# ---------------------------------------------------------------------------
# P1 — Environment Misspecification
# ---------------------------------------------------------------------------

class TestEnvironmentMisspecification:

    def test_mismatch_detected_escalates(self):
        obs = _obs(environment_mismatch_detected=True)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE
        assert DecisionReason.ENV_MISMATCH_ESCALATE in r.reasons

    def test_mismatch_detected_beats_high_trust(self):
        """Hard signal overrides even ordered high-trust path."""
        obs = _obs(environment_mismatch_detected=True, trust_score=0.99)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE

    def test_low_env_confidence_prod_write_verifies(self):
        obs = _obs(environment_confidence=0.60, action_type="write")
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.VERIFY
        assert DecisionReason.ENV_CONFIDENCE_VERIFY in r.reasons

    def test_low_env_confidence_prod_read_not_triggered(self):
        """Read-only actions are safe regardless of env confidence."""
        obs = _obs(environment_confidence=0.60, action_type="read")
        r = ENGINE.decide(obs)
        assert DecisionReason.ENV_CONFIDENCE_VERIFY not in r.reasons

    def test_high_env_confidence_no_trigger(self):
        obs = _obs(environment_confidence=0.95, action_type="write")
        r = ENGINE.decide(obs)
        assert DecisionReason.ENV_CONFIDENCE_VERIFY not in r.reasons

    def test_none_env_confidence_no_trigger(self):
        """Missing env confidence does not trigger the gate."""
        obs = _obs(environment_confidence=None, action_type="write")
        r = ENGINE.decide(obs)
        assert DecisionReason.ENV_CONFIDENCE_VERIFY not in r.reasons

    def test_rollback_false_critical_risk_escalates(self):
        obs = _obs(rollback_available=False, risk_tier="critical",
                   phase="ordered", trust_score=0.9)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE
        assert DecisionReason.ROLLBACK_UNAVAILABLE in r.reasons

    def test_rollback_false_high_risk_escalates(self):
        obs = _obs(rollback_available=False, risk_tier="high",
                   phase="ordered", trust_score=0.9)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE
        assert DecisionReason.ROLLBACK_UNAVAILABLE in r.reasons

    def test_rollback_false_low_risk_no_trigger(self):
        obs = _obs(rollback_available=False, risk_tier="low")
        r = ENGINE.decide(obs)
        assert DecisionReason.ROLLBACK_UNAVAILABLE not in r.reasons

    def test_rollback_none_no_trigger(self):
        obs = _obs(rollback_available=None, risk_tier="critical")
        r = ENGINE.decide(obs)
        assert DecisionReason.ROLLBACK_UNAVAILABLE not in r.reasons

    def test_state_transition_uncertain_high_risk_escalates(self):
        obs = _obs(state_transition_uncertain=True, risk_tier="high",
                   phase="ordered", trust_score=0.9)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE
        assert DecisionReason.STATE_TRANSITION_UNCERTAIN in r.reasons

    def test_state_transition_uncertain_low_risk_no_trigger(self):
        obs = _obs(state_transition_uncertain=True, risk_tier="low")
        r = ENGINE.decide(obs)
        assert DecisionReason.STATE_TRANSITION_UNCERTAIN not in r.reasons


# ---------------------------------------------------------------------------
# P2 — Alternative Classification
# ---------------------------------------------------------------------------

class TestAlternativeClassification:

    def test_critical_alternative_escalates(self):
        obs = _obs(classification_alternatives=["destructive_write"])
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE
        assert DecisionReason.CRITICAL_ALTERNATIVE in r.reasons

    def test_privilege_escalation_alternative_escalates(self):
        obs = _obs(classification_alternatives=["read", "privilege_escalation"])
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE
        assert DecisionReason.CRITICAL_ALTERNATIVE in r.reasons

    def test_high_risk_alternative_verifies(self):
        obs = _obs(classification_alternatives=["delete"])
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.VERIFY
        assert DecisionReason.HIGH_RISK_ALTERNATIVE in r.reasons

    def test_low_risk_alternatives_no_trigger(self):
        obs = _obs(classification_alternatives=["read", "list"])
        r = ENGINE.decide(obs)
        assert DecisionReason.CRITICAL_ALTERNATIVE not in r.reasons
        assert DecisionReason.HIGH_RISK_ALTERNATIVE not in r.reasons

    def test_none_alternatives_no_trigger(self):
        obs = _obs(classification_alternatives=None)
        r = ENGINE.decide(obs)
        assert DecisionReason.CRITICAL_ALTERNATIVE not in r.reasons

    def test_low_classification_confidence_write_verifies(self):
        obs = _obs(classification_confidence=0.40, action_type="write")
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.VERIFY
        assert DecisionReason.LOW_CLASSIFICATION_CONF in r.reasons

    def test_low_classification_confidence_read_no_trigger(self):
        obs = _obs(classification_confidence=0.40, action_type="read")
        r = ENGINE.decide(obs)
        assert DecisionReason.LOW_CLASSIFICATION_CONF not in r.reasons

    def test_high_classification_confidence_no_trigger(self):
        obs = _obs(classification_confidence=0.90, action_type="write")
        r = ENGINE.decide(obs)
        assert DecisionReason.LOW_CLASSIFICATION_CONF not in r.reasons


# ---------------------------------------------------------------------------
# P3 — Misspecification Guard
# ---------------------------------------------------------------------------

class TestMisspecificationGuard:

    def test_high_misspec_risk_write_verifies(self):
        obs = _obs(model_misspecification_risk=0.80, action_type="write")
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.VERIFY
        assert DecisionReason.MISSPECIFICATION_VERIFY in r.reasons

    def test_high_misspec_risk_read_no_trigger(self):
        obs = _obs(model_misspecification_risk=0.80, action_type="read")
        r = ENGINE.decide(obs)
        assert DecisionReason.MISSPECIFICATION_VERIFY not in r.reasons

    def test_low_misspec_risk_no_trigger(self):
        obs = _obs(model_misspecification_risk=0.40, action_type="write")
        r = ENGINE.decide(obs)
        assert DecisionReason.MISSPECIFICATION_VERIFY not in r.reasons

    def test_none_misspec_risk_no_trigger(self):
        obs = _obs(model_misspecification_risk=None)
        r = ENGINE.decide(obs)
        assert DecisionReason.MISSPECIFICATION_VERIFY not in r.reasons


# ---------------------------------------------------------------------------
# Gate ordering: hard blocks still fire first
# ---------------------------------------------------------------------------

class TestGateOrdering:

    def test_adversarial_beats_misspec_gates(self):
        """Hard ESCALATE from adversarial detection must fire before misspec gates."""
        obs = _obs(
            adversarial_detected=True,
            environment_mismatch_detected=True,
            classification_alternatives=["destructive_write"],
            model_misspecification_risk=0.99,
        )
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE
        assert DecisionReason.ADMISSION_FIREWALL_BLOCKED in r.reasons
        assert DecisionReason.ENV_MISMATCH_ESCALATE not in r.reasons

    def test_all_fields_none_no_behaviour_change(self):
        """Baseline: no new fields → same verdict as before these gates existed."""
        obs = _obs(
            environment_confidence=None,
            environment_mismatch_detected=False,
            rollback_available=None,
            state_transition_uncertain=False,
            classification_confidence=None,
            classification_alternatives=None,
            model_misspecification_risk=None,
        )
        r = ENGINE.decide(obs)
        # ordered + high trust + medium risk + no block → should ACCEPT
        assert r.action == DecisionAction.ACCEPT
