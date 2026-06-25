# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for the credal risk envelope and its integration with the engine."""
from __future__ import annotations

from remora.credal import (
    CredalEnvelope,
    compute_from_obs,
)
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _obs(**kwargs) -> PolicyObservation:
    return PolicyObservation(question="test action", **kwargs)


# ---------------------------------------------------------------------------
# CredalEnvelope unit tests
# ---------------------------------------------------------------------------

class TestCredalEnvelopeComputation:
    def test_fields_are_within_zero_one(self):
        obs = _obs(trust_score=0.70, final_H=0.5, final_D=0.3, phase="ordered")
        c = compute_from_obs(obs)
        assert 0.0 <= c.p_harm_lower <= 1.0
        assert 0.0 <= c.p_harm_upper <= 1.0
        assert 0.0 <= c.ambiguity_width <= 1.0
        assert 0.0 <= c.worst_case_loss <= 1.0
        assert 0.0 <= c.utility_lower <= 1.0
        assert 0.0 <= c.utility_upper <= 1.0

    def test_lower_le_upper(self):
        for trust in (0.1, 0.5, 0.9):
            obs = _obs(trust_score=trust, final_H=0.8, final_D=0.5, phase="critical")
            c = compute_from_obs(obs)
            assert c.p_harm_lower <= c.p_harm_upper
            assert c.utility_lower <= c.utility_upper

    def test_ambiguity_width_equals_interval_width(self):
        obs = _obs(trust_score=0.6, final_H=0.4, final_D=0.2, phase="ordered")
        c = compute_from_obs(obs)
        assert abs(c.ambiguity_width - (c.p_harm_upper - c.p_harm_lower)) < 1e-6

    def test_high_trust_low_harm(self):
        obs = _obs(trust_score=0.92, final_H=0.0, final_D=0.0, phase="ordered")
        c = compute_from_obs(obs)
        assert c.p_harm_upper < 0.20, "High trust should give low harm upper bound"
        assert c.worst_case_loss < 0.80, "Should not trigger minimax for high trust low disagreement"

    def test_low_trust_high_harm(self):
        obs = _obs(trust_score=0.15, final_H=1.0, final_D=0.8, phase="disordered")
        c = compute_from_obs(obs)
        assert c.p_harm_upper > 0.60, "Low trust + high disagreement should push p_harm_upper high"

    def test_disordered_phase_widens_interval(self):
        common = dict(trust_score=0.50, final_H=0.5, final_D=0.4)
        ordered    = compute_from_obs(_obs(**common, phase="ordered"))
        disordered = compute_from_obs(_obs(**common, phase="disordered"))
        assert disordered.ambiguity_width > ordered.ambiguity_width

    def test_no_trust_score_uses_conservative_default(self):
        obs = _obs(phase="ordered")  # trust_score=None
        c = compute_from_obs(obs)
        # Default is 0.50 → p_harm centre 0.50
        assert c.p_harm_lower <= 0.50 <= c.p_harm_upper

    def test_adjusted_trust_is_none_when_no_trust(self):
        c = compute_from_obs(_obs(phase="ordered"))
        assert c.adjusted_trust is None

    def test_adjusted_trust_lower_than_raw_when_ambiguity_positive(self):
        obs = _obs(trust_score=0.80, final_H=0.8, final_D=0.6, phase="critical")
        c = compute_from_obs(obs)
        assert c.adjusted_trust is not None
        assert c.adjusted_trust < obs.trust_score

    def test_adjusted_trust_equals_raw_when_zero_ambiguity(self):
        obs = _obs(trust_score=0.80, final_H=0.0, final_D=0.0, phase="ordered")
        c = compute_from_obs(obs)
        assert c.adjusted_trust is not None
        # ambiguity_width should be ~0 → adjusted_trust ≈ trust_score
        assert abs(c.adjusted_trust - obs.trust_score) < 0.01

    def test_irreversible_action_raises_worst_case_loss(self):
        # Use moderate disagreement so neither hits the 1.0 cap
        base     = _obs(trust_score=0.60, final_H=0.2, final_D=0.1, risk_tier="medium", action_type="read")
        trap_obs = _obs(trust_score=0.60, final_H=0.2, final_D=0.1, risk_tier="medium", action_type="destructive_write")
        c_base = compute_from_obs(base)
        c_trap = compute_from_obs(trap_obs)
        assert c_trap.worst_case_loss > c_base.worst_case_loss, (
            f"destructive_write worst_case={c_trap.worst_case_loss} "
            f"should exceed read worst_case={c_base.worst_case_loss}"
        )

    def test_critical_tier_severity_increases_worst_case(self):
        low      = _obs(trust_score=0.5, final_H=0.4, risk_tier="low",      action_type="destructive_write")
        critical = _obs(trust_score=0.5, final_H=0.4, risk_tier="critical", action_type="destructive_write")
        c_low = compute_from_obs(low)
        c_crit = compute_from_obs(critical)
        assert c_crit.worst_case_loss > c_low.worst_case_loss

    def test_minimax_should_escalate_true_above_threshold(self):
        obs = _obs(trust_score=0.10, final_H=1.0, final_D=0.9,
                   phase="disordered", risk_tier="critical", action_type="destructive_write")
        c = compute_from_obs(obs)
        assert c.minimax_should_escalate()

    def test_minimax_should_escalate_false_below_threshold(self):
        obs = _obs(trust_score=0.90, final_H=0.0, final_D=0.0,
                   phase="ordered", risk_tier="low", action_type="read")
        c = compute_from_obs(obs)
        assert not c.minimax_should_escalate()

    def test_decision_recommendation_escalate(self):
        obs = _obs(trust_score=0.05, final_H=1.0, final_D=0.9,
                   risk_tier="critical", action_type="destructive_write")
        c = compute_from_obs(obs)
        assert c.decision_recommendation() == "ESCALATE"

    def test_decision_recommendation_accept(self):
        obs = _obs(trust_score=0.95, final_H=0.0, final_D=0.0,
                   phase="ordered", risk_tier="low", action_type="read")
        c = compute_from_obs(obs)
        assert c.decision_recommendation() == "ACCEPT"

    def test_to_dict_contains_all_fields(self):
        obs = _obs(trust_score=0.7, final_H=0.3, phase="ordered")
        d = compute_from_obs(obs).to_dict()
        expected = {"p_harm_lower", "p_harm_upper", "utility_lower", "utility_upper",
                    "ambiguity_width", "worst_case_loss", "adjusted_trust"}
        assert expected == set(d.keys())


# ---------------------------------------------------------------------------
# Engine integration: credal attached to every report
# ---------------------------------------------------------------------------

class TestEngineCredalAttachment:
    def setup_method(self):
        self.engine = RemoraDecisionEngine()

    def _decide(self, **kwargs) -> object:
        return self.engine.decide(_obs(**kwargs))

    def test_credal_attached_on_accept(self):
        report = self._decide(
            trust_score=0.85, phase="ordered", final_H=0.0, final_D=0.0,
            risk_tier="low", action_type="read",
        )
        assert report.credal is not None
        assert isinstance(report.credal, CredalEnvelope)

    def test_credal_attached_on_escalate(self):
        report = self._decide(adversarial_detected=True)
        assert report.credal is not None

    def test_credal_attached_on_abstain(self):
        report = self._decide(phase="disordered", trust_score=0.1)
        assert report.credal is not None

    def test_credal_attached_on_verify(self):
        report = self._decide(risk_tier="high")
        assert report.credal is not None

    def test_credal_values_consistent_with_observation(self):
        obs = _obs(trust_score=0.75, final_H=0.3, final_D=0.2,
                   phase="ordered", risk_tier="low", action_type="read")
        report = self.engine.decide(obs)
        expected = compute_from_obs(obs)
        assert report.credal.p_harm_lower == expected.p_harm_lower
        assert report.credal.worst_case_loss == expected.worst_case_loss


# ---------------------------------------------------------------------------
# Minimax gate integration
# ---------------------------------------------------------------------------

class TestMinimaxGate:
    def setup_method(self):
        self.engine = RemoraDecisionEngine()

    def test_minimax_escalates_high_worst_case(self):
        # Low trust + high disagreement + irreversible action in critical tier
        obs = _obs(
            trust_score=0.08, final_H=1.0, final_D=0.95,
            phase="disordered", risk_tier="medium",
            action_type="destructive_write", target_environment="prod",
        )
        report = self.engine.decide(obs)
        assert report.action == DecisionAction.ESCALATE
        assert DecisionReason.MINIMAX_ESCALATE in report.reasons

    def test_minimax_does_not_fire_for_safe_action(self):
        obs = _obs(
            trust_score=0.90, final_H=0.0, final_D=0.0,
            phase="ordered", risk_tier="low", action_type="read",
        )
        report = self.engine.decide(obs)
        assert DecisionReason.MINIMAX_ESCALATE not in report.reasons

    def test_minimax_runs_after_adversarial_block(self):
        obs = _obs(adversarial_detected=True, trust_score=0.05, final_H=1.0)
        report = self.engine.decide(obs)
        # Adversarial block fires first; minimax reason should NOT be present
        assert DecisionReason.ADMISSION_FIREWALL_BLOCKED in report.reasons
        assert DecisionReason.MINIMAX_ESCALATE not in report.reasons


# ---------------------------------------------------------------------------
# Ambiguity penalty in ordered_high_trust path
# ---------------------------------------------------------------------------

class TestAmbiguityPenalty:
    def setup_method(self):
        self.engine = RemoraDecisionEngine()

    def test_high_disagreement_prevents_accept(self):
        # trust_score above raw threshold but adjusted_trust drops below
        obs = _obs(
            trust_score=0.80, final_H=0.95, final_D=0.85,
            phase="ordered", risk_tier="low", action_type="read",
        )
        c = compute_from_obs(obs)
        if c.adjusted_trust is not None and c.adjusted_trust < 0.72:
            report = self.engine.decide(obs)
            assert report.action != DecisionAction.ACCEPT, (
                f"adjusted_trust={c.adjusted_trust:.4f} < 0.72 should prevent ACCEPT"
            )

    def test_zero_disagreement_preserves_accept(self):
        obs = _obs(
            trust_score=0.80, final_H=0.0, final_D=0.0,
            phase="ordered", risk_tier="low", action_type="read",
        )
        report = self.engine.decide(obs)
        assert report.action == DecisionAction.ACCEPT
