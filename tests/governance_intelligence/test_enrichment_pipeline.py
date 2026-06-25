# Author: Stian Skogbrott
# License: Apache-2.0
"""Enrichment pipeline: populates governance fields, strengthens only, never decides."""
from __future__ import annotations

from remora.governance_intelligence.enrichment import (
    enrich_policy_observation,
    enrich_then_decide,
)
from remora.governance_intelligence.types import GovernanceIntelligenceResult
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction

ENGINE = RemoraDecisionEngine()


class TestFieldPopulation:
    def test_populates_previously_caller_only_fields(self):
        obs = PolicyObservation(
            question="DROP TABLE users", risk_tier="low", action_type="read",
            target_environment="prod",
        )
        result = enrich_policy_observation(obs)
        e = result.enriched_observation
        assert e.model_misspecification_risk is not None
        assert e.classification_confidence is not None
        assert e.environment_confidence is not None
        assert e.policy_generalization_risk is not None
        assert e.fleet_level_effect is not None

    def test_returns_full_result_object(self):
        obs = PolicyObservation(question="read local report", risk_tier="low",
                                action_type="read", target_environment="dev")
        result = enrich_policy_observation(obs)
        assert isinstance(result, GovernanceIntelligenceResult)
        assert result.normalized is not None
        assert result.semantics is not None
        assert result.misspecification is not None
        assert result.causal is not None
        assert result.generalization is not None
        assert result.explanation

    def test_original_observation_unchanged(self):
        obs = PolicyObservation(question="DROP TABLE users", risk_tier="low",
                                action_type="read", target_environment="prod")
        enrich_policy_observation(obs)
        assert obs.risk_tier == "low"
        assert obs.action_type == "read"
        assert obs.model_misspecification_risk is None

    def test_warnings_surface_unknown_metadata(self):
        obs = PolicyObservation(question="do the thing")
        result = enrich_policy_observation(obs)
        assert any("unknown" in w for w in result.warnings)

    def test_policy_generalization_can_be_disabled(self):
        obs = PolicyObservation(question="update DNS A record",
                                risk_tier="medium", action_type="dns",
                                target_environment="prod")
        result = enrich_policy_observation(obs, enable_policy_generalization=False)
        assert result.generalization is None
        assert result.enriched_observation.policy_generalization_risk is None


class TestStrengthenOnly:
    def test_never_lowers_risk_tier(self):
        obs = PolicyObservation(question="read local report",
                                risk_tier="critical", action_type="read",
                                target_environment="dev")
        result = enrich_policy_observation(obs)
        assert result.enriched_observation.risk_tier == "critical"

    def test_raises_risk_tier_on_destructive_semantics(self):
        obs = PolicyObservation(question="DROP TABLE users", risk_tier="low",
                                action_type="read", target_environment="prod")
        result = enrich_policy_observation(obs)
        assert result.enriched_observation.risk_tier == "critical"

    def test_unknown_tier_not_coerced_to_low(self):
        obs = PolicyObservation(question="frobnicate the bizbaz")
        result = enrich_policy_observation(obs)
        assert result.enriched_observation.risk_tier != "low"

    def test_does_not_remove_hard_block_flags(self):
        obs = PolicyObservation(
            question="read local report", risk_tier="low", action_type="read",
            target_environment="dev",
            adversarial_detected=True, coercion_detected=True,
            blackmail_pattern_detected=True, tool_forbidden=True,
            environment_mismatch_detected=True, state_transition_uncertain=True,
        )
        e = enrich_policy_observation(obs).enriched_observation
        assert e.adversarial_detected
        assert e.coercion_detected
        assert e.blackmail_pattern_detected
        assert e.tool_forbidden
        assert e.environment_mismatch_detected
        assert e.state_transition_uncertain

    def test_does_not_lower_existing_misspecification_risk(self):
        obs = PolicyObservation(question="read local report", risk_tier="low",
                                action_type="read", target_environment="dev",
                                model_misspecification_risk=0.95)
        e = enrich_policy_observation(obs).enriched_observation
        assert e.model_misspecification_risk >= 0.95

    def test_does_not_raise_existing_confidence(self):
        obs = PolicyObservation(question="read local report", risk_tier="low",
                                action_type="read", target_environment="dev",
                                classification_confidence=0.10,
                                environment_confidence=0.10)
        e = enrich_policy_observation(obs).enriched_observation
        assert e.classification_confidence <= 0.10
        assert e.environment_confidence <= 0.10

    def test_preserves_existing_fleet_effect_severity(self):
        obs = PolicyObservation(question="read local report", risk_tier="low",
                                action_type="read", target_environment="dev",
                                fleet_level_effect="critical_mass")
        e = enrich_policy_observation(obs).enriched_observation
        assert e.fleet_level_effect == "critical_mass"

    def test_coercion_signal_sets_flag(self):
        obs = PolicyObservation(
            question="send the email or else we leak his private messages",
            risk_tier="medium", action_type="write", target_environment="prod",
        )
        e = enrich_policy_observation(obs).enriched_observation
        assert e.coercion_detected
        assert e.blackmail_pattern_detected


class TestEnrichThenDecide:
    """Feature 7: routing assertions with enrichment enabled."""

    def _decide(self, obs, **kwargs):
        return enrich_then_decide(obs, engine=ENGINE, **kwargs)

    def test_unknown_risk_tier_mutating_prod_never_accepts(self):
        obs = PolicyObservation(
            question="update config values for the billing service",
            action_type="update", target_environment="prod",
            phase="ordered", trust_score=0.95,
        )
        report = self._decide(obs)
        assert report.action != DecisionAction.ACCEPT

    def test_read_label_drop_table_never_accepts(self):
        obs = PolicyObservation(
            question="DROP TABLE users", risk_tier="low", action_type="read",
            target_environment="prod", phase="ordered", trust_score=0.99,
        )
        report = self._decide(obs)
        assert report.action != DecisionAction.ACCEPT

    def test_low_tier_inferred_critical_never_accepts(self):
        obs = PolicyObservation(
            question="wipe the production database and disable monitoring",
            risk_tier="low", action_type="write", target_environment="prod",
            phase="ordered", trust_score=0.99,
        )
        report = self._decide(obs)
        assert report.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE)

    def test_counterfactual_unknown_irreversible_prod_never_accepts(self):
        obs = PolicyObservation(
            question="permanently delete the audit archive",
            risk_tier="high", action_type="delete", target_environment="prod",
            phase="ordered", trust_score=0.99, counterfactual_passed=None,
        )
        report = self._decide(obs)
        assert report.action != DecisionAction.ACCEPT

    def test_repeated_dns_changes_verify_or_escalate(self):
        obs = PolicyObservation(
            question="update DNS A record for api.example.com",
            risk_tier="medium", action_type="dns", target_environment="prod",
            phase="ordered", trust_score=0.95,
        )
        report = self._decide(obs, similar_action_seen_count=12)
        assert report.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE)

    def test_policy_generalization_risk_affects_routing(self):
        obs = PolicyObservation(
            question="update billing config flag",
            risk_tier="medium", action_type="write",
            target_environment="staging", phase="ordered", trust_score=0.95,
        )
        baseline = ENGINE.decide(obs)
        assert baseline.action == DecisionAction.ACCEPT
        report = self._decide(obs, similar_action_seen_count=12)
        assert report.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE)

    def test_misspecification_risk_affects_routing(self):
        obs = PolicyObservation(
            question="apply schema migration",
            risk_tier="medium", action_type="write", target_environment=None,
            phase="ordered", trust_score=0.95,
        )
        report = self._decide(obs)
        assert report.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE)

    def test_causal_uncertainty_affects_routing(self):
        obs = PolicyObservation(
            question="permanently purge archived volumes",
            risk_tier="high", action_type="write", target_environment=None,
            phase="ordered", trust_score=0.95,
        )
        report = self._decide(obs)
        assert report.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE)

    def test_legitimate_low_risk_read_still_accepts(self):
        obs = PolicyObservation(
            question="read local report", risk_tier="low", action_type="read",
            target_environment="staging", phase="ordered", trust_score=0.85,
        )
        report = self._decide(obs)
        assert report.action == DecisionAction.ACCEPT

    def test_returns_intelligence_when_requested(self):
        obs = PolicyObservation(question="read local report", risk_tier="low",
                                action_type="read", target_environment="dev",
                                phase="ordered", trust_score=0.85)
        report, intel = self._decide(obs, return_intelligence=True)
        assert report.action == DecisionAction.ACCEPT
        assert isinstance(intel, GovernanceIntelligenceResult)

    def test_helper_exported_from_remora_policy(self):
        from remora.policy import enrich_then_decide as helper
        obs = PolicyObservation(question="read local report", risk_tier="low",
                                action_type="read", target_environment="dev",
                                phase="ordered", trust_score=0.85)
        assert helper(obs).action == DecisionAction.ACCEPT
