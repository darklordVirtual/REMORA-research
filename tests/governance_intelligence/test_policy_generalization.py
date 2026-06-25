# Author: Stian Skogbrott
# License: Apache-2.0
"""Policy-generalization risk: would this class of action be safe as standing policy?"""
from __future__ import annotations

from remora.governance_intelligence.action_semantics import extract_action_semantics
from remora.governance_intelligence.causal_consequence import assess_causal_consequence
from remora.governance_intelligence.misspecification import assess_misspecification
from remora.governance_intelligence.normalization import normalize_metadata
from remora.governance_intelligence.policy_generalization import (
    assess_policy_generalization,
)


def _assess(text, *, risk_tier=None, action_type=None, environment=None, count=None):
    normalized = normalize_metadata(
        risk_tier=risk_tier, action_type=action_type,
        target_environment=environment,
    )
    semantics = extract_action_semantics(text)
    misspec = assess_misspecification(normalized, semantics, text=text)
    causal = assess_causal_consequence(normalized, semantics, misspec)
    return assess_policy_generalization(
        normalized, semantics, causal, similar_action_seen_count=count,
    )


class TestActionClasses:
    def test_repeated_reads_low_risk(self):
        g = _assess("read local report", risk_tier="low", action_type="read",
                    environment="dev", count=40)
        assert g.policy_generalization_risk < 0.5
        assert g.fleet_level_effect in ("none", "local")
        assert g.standing_policy_safe

    def test_dns_changes_systemic(self):
        g = _assess("update DNS A record", risk_tier="medium",
                    action_type="dns", environment="prod", count=2)
        assert g.fleet_level_effect == "systemic"
        assert g.policy_generalization_risk >= 0.8
        assert not g.standing_policy_safe

    def test_firewall_changes_systemic(self):
        g = _assess("open port 443 on the security group", risk_tier="medium",
                    action_type="firewall", environment="prod")
        assert g.fleet_level_effect == "systemic"

    def test_external_sends_tenant_risk(self):
        g = _assess("send newsletter emails to subscribers", risk_tier="medium",
                    action_type="write", environment="prod")
        assert g.fleet_level_effect in ("tenant", "systemic")
        assert g.policy_generalization_risk >= 0.6

    def test_permission_grants_tenant_risk(self):
        g = _assess("grant admin access to the contractor", risk_tier="high",
                    action_type="grant_access", environment="prod")
        assert g.fleet_level_effect in ("tenant", "systemic")
        assert g.policy_generalization_risk >= 0.6

    def test_destructive_prod_systemic(self):
        g = _assess("delete stale records from the production database",
                    risk_tier="high", action_type="delete", environment="prod")
        assert g.fleet_level_effect == "systemic"
        assert g.policy_generalization_risk >= 0.8


class TestRepetition:
    def test_count_above_ten_mutating_raises_risk(self):
        few = _assess("update billing config", risk_tier="medium",
                      action_type="write", environment="staging", count=2)
        many = _assess("update billing config", risk_tier="medium",
                       action_type="write", environment="staging", count=12)
        assert many.policy_generalization_risk > few.policy_generalization_risk
        assert many.policy_generalization_risk >= 0.7
        assert many.repeated_action_pattern

    def test_critical_repeated_is_systemic(self):
        g = _assess("emergency change", risk_tier="critical",
                    action_type="write", environment="prod", count=5)
        assert g.fleet_level_effect == "systemic"
        assert g.policy_generalization_risk >= 0.85

    def test_unknown_env_repeated_mutation(self):
        g = _assess("apply migration", risk_tier="medium",
                    action_type="write", environment=None, count=8)
        assert g.fleet_level_effect in ("systemic", "unknown")
        assert g.policy_generalization_risk >= 0.75

    def test_count_recorded(self):
        g = _assess("read report", action_type="read", risk_tier="low",
                    environment="dev", count=7)
        assert g.similar_action_seen_count == 7
        assert g.repeated_action_pattern


class TestNarrative:
    def test_counterfactual_text(self):
        g = _assess("update DNS A record", risk_tier="medium",
                    action_type="dns", environment="prod", count=3)
        assert "standing" in g.generalized_counterfactual
        assert g.reasons

    def test_risk_bounded(self):
        for count in (None, 0, 5, 100):
            g = _assess("delete everything", action_type="delete",
                        environment="prod", count=count)
            assert 0.0 <= g.policy_generalization_risk <= 1.0

    def test_deterministic(self):
        first = _assess("update DNS A record", action_type="dns",
                        environment="prod", count=12)
        for _ in range(3):
            assert _assess("update DNS A record", action_type="dns",
                           environment="prod", count=12) == first
