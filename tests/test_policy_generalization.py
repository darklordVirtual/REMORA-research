# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for coercion hard blocks, session sequential risk, and policy generalization gates."""
from __future__ import annotations

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason

ENGINE = RemoraDecisionEngine()


def _obs(**kwargs) -> PolicyObservation:
    """Helper: ordered-phase, medium-risk write action — reaches ACCEPT when no gates fire."""
    defaults = dict(
        question="test action",
        phase="ordered",
        trust_score=0.85,
        risk_tier="medium",
        action_type="write",
        target_environment="prod",
    )
    defaults.update(kwargs)
    return PolicyObservation(**defaults)


# ---------------------------------------------------------------------------
# Coercion hard blocks
# ---------------------------------------------------------------------------

class TestCoercionHardBlocks:

    def test_coercion_detected_escalates(self):
        obs = _obs(coercion_detected=True)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE
        assert DecisionReason.COERCION_BLOCKED in r.reasons

    def test_coercion_beats_high_trust(self):
        obs = _obs(coercion_detected=True, trust_score=0.99)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE
        assert DecisionReason.COERCION_BLOCKED in r.reasons

    def test_blackmail_pattern_escalates(self):
        obs = _obs(blackmail_pattern_detected=True)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE
        assert DecisionReason.BLACKMAIL_BLOCKED in r.reasons

    def test_blackmail_beats_high_trust(self):
        obs = _obs(blackmail_pattern_detected=True, trust_score=0.99)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE

    def test_coercion_false_no_trigger(self):
        obs = _obs(coercion_detected=False)
        r = ENGINE.decide(obs)
        assert DecisionReason.COERCION_BLOCKED not in r.reasons

    def test_blackmail_false_no_trigger(self):
        obs = _obs(blackmail_pattern_detected=False)
        r = ENGINE.decide(obs)
        assert DecisionReason.BLACKMAIL_BLOCKED not in r.reasons

    def test_coercion_fires_before_misspec_gates(self):
        """Coercion hard block fires before misspecification soft gates."""
        obs = _obs(
            coercion_detected=True,
            model_misspecification_risk=0.99,
            environment_mismatch_detected=True,
        )
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE
        assert DecisionReason.COERCION_BLOCKED in r.reasons
        assert DecisionReason.MISSPECIFICATION_VERIFY not in r.reasons


# ---------------------------------------------------------------------------
# Session sequential risk gates
# ---------------------------------------------------------------------------

class TestSessionSequentialRisk:

    def test_high_session_cumulative_risk_verifies(self):
        obs = _obs(session_cumulative_risk=0.85)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.VERIFY
        assert DecisionReason.SESSION_RISK_VERIFY in r.reasons

    def test_session_cumulative_risk_at_threshold_no_trigger(self):
        obs = _obs(session_cumulative_risk=0.80)
        r = ENGINE.decide(obs)
        assert DecisionReason.SESSION_RISK_VERIFY not in r.reasons

    def test_low_session_cumulative_risk_no_trigger(self):
        obs = _obs(session_cumulative_risk=0.50)
        r = ENGINE.decide(obs)
        assert DecisionReason.SESSION_RISK_VERIFY not in r.reasons

    def test_none_session_cumulative_risk_no_trigger(self):
        obs = _obs(session_cumulative_risk=None)
        r = ENGINE.decide(obs)
        assert DecisionReason.SESSION_RISK_VERIFY not in r.reasons

    def test_session_flood_verifies(self):
        obs = _obs(session_action_count=101)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.VERIFY
        assert DecisionReason.SESSION_FLOOD_VERIFY in r.reasons

    def test_session_action_count_at_threshold_no_trigger(self):
        obs = _obs(session_action_count=100)
        r = ENGINE.decide(obs)
        assert DecisionReason.SESSION_FLOOD_VERIFY not in r.reasons

    def test_none_session_action_count_no_trigger(self):
        obs = _obs(session_action_count=None)
        r = ENGINE.decide(obs)
        assert DecisionReason.SESSION_FLOOD_VERIFY not in r.reasons

    def test_session_id_alone_no_trigger(self):
        """session_id is for audit only — does not affect gate logic."""
        obs = _obs(session_id="sess-abc123")
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ACCEPT


# ---------------------------------------------------------------------------
# Policy generalization gates
# ---------------------------------------------------------------------------

class TestPolicyGeneralization:

    def test_fleet_systemic_verifies(self):
        obs = _obs(fleet_level_effect="systemic")
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.VERIFY
        assert DecisionReason.FLEET_SYSTEMIC_VERIFY in r.reasons

    def test_fleet_critical_mass_verifies(self):
        obs = _obs(fleet_level_effect="critical_mass")
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.VERIFY
        assert DecisionReason.FLEET_SYSTEMIC_VERIFY in r.reasons

    def test_fleet_local_no_trigger(self):
        obs = _obs(fleet_level_effect="local")
        r = ENGINE.decide(obs)
        assert DecisionReason.FLEET_SYSTEMIC_VERIFY not in r.reasons

    def test_none_fleet_no_trigger(self):
        obs = _obs(fleet_level_effect=None)
        r = ENGINE.decide(obs)
        assert DecisionReason.FLEET_SYSTEMIC_VERIFY not in r.reasons

    def test_high_policy_generalization_risk_verifies(self):
        obs = _obs(policy_generalization_risk=0.85)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.VERIFY
        assert DecisionReason.POLICY_GENERALIZATION_VERIFY in r.reasons

    def test_policy_generalization_risk_at_threshold_no_trigger(self):
        obs = _obs(policy_generalization_risk=0.70)
        r = ENGINE.decide(obs)
        assert DecisionReason.POLICY_GENERALIZATION_VERIFY not in r.reasons

    def test_low_policy_generalization_risk_no_trigger(self):
        obs = _obs(policy_generalization_risk=0.50)
        r = ENGINE.decide(obs)
        assert DecisionReason.POLICY_GENERALIZATION_VERIFY not in r.reasons

    def test_similar_action_flood_verifies(self):
        obs = _obs(similar_action_seen_count=51)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.VERIFY
        assert DecisionReason.SIMILAR_ACTION_FLOOD_VERIFY in r.reasons

    def test_similar_action_count_at_threshold_no_trigger(self):
        obs = _obs(similar_action_seen_count=50)
        r = ENGINE.decide(obs)
        assert DecisionReason.SIMILAR_ACTION_FLOOD_VERIFY not in r.reasons

    def test_none_similar_action_count_no_trigger(self):
        obs = _obs(similar_action_seen_count=None)
        r = ENGINE.decide(obs)
        assert DecisionReason.SIMILAR_ACTION_FLOOD_VERIFY not in r.reasons


# ---------------------------------------------------------------------------
# Gate ordering and None-safety
# ---------------------------------------------------------------------------

class TestGateOrdering:

    def test_adversarial_beats_coercion(self):
        """Existing hard block fires before new coercion block — both ESCALATE, reason is adversarial."""
        obs = _obs(adversarial_detected=True, coercion_detected=True)
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ESCALATE
        assert DecisionReason.ADMISSION_FIREWALL_BLOCKED in r.reasons
        assert DecisionReason.COERCION_BLOCKED not in r.reasons

    def test_coercion_beats_fleet_gates(self):
        """Coercion hard block fires before fleet soft gates."""
        obs = _obs(coercion_detected=True, fleet_level_effect="systemic",
                   policy_generalization_risk=0.99)
        r = ENGINE.decide(obs)
        assert DecisionReason.COERCION_BLOCKED in r.reasons
        assert DecisionReason.FLEET_SYSTEMIC_VERIFY not in r.reasons

    def test_all_new_fields_none_no_behaviour_change(self):
        """All new fields at defaults → ordered high-trust medium-risk action still ACCEPTs."""
        obs = _obs(
            coercion_detected=False,
            blackmail_pattern_detected=False,
            similar_action_seen_count=None,
            policy_generalization_risk=None,
            fleet_level_effect=None,
            session_id=None,
            session_action_count=None,
            session_cumulative_risk=None,
        )
        r = ENGINE.decide(obs)
        assert r.action == DecisionAction.ACCEPT
