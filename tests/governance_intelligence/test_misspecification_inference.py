# Author: Stian Skogbrott
# License: Apache-2.0
"""Misspecification inference: label/semantics disagreement becomes explicit risk."""
from __future__ import annotations

from remora.governance_intelligence.action_semantics import extract_action_semantics
from remora.governance_intelligence.misspecification import assess_misspecification
from remora.governance_intelligence.normalization import normalize_metadata


def _assess(text, *, risk_tier=None, action_type=None, environment=None,
            tool_name=None, tool_arguments=None, rollback_available=None):
    normalized = normalize_metadata(
        risk_tier=risk_tier, action_type=action_type,
        target_environment=environment, tool_name=tool_name,
    )
    semantics = extract_action_semantics(
        text, tool_name=tool_name, tool_arguments=tool_arguments,
    )
    return assess_misspecification(
        normalized, semantics,
        tool_arguments=tool_arguments,
        rollback_available=rollback_available,
        text=text,
    )


class TestTypeMismatch:
    def test_read_label_destructive_semantics_is_high_risk(self):
        a = _assess("DROP TABLE users", risk_tier="low", action_type="read",
                    environment="prod")
        assert a.model_misspecification_risk >= 0.8
        assert a.classification_confidence <= 0.4
        assert any(alt["action_type"] == "destructive_write"
                   for alt in a.classification_alternatives)

    def test_low_tier_critical_semantics_is_high_risk(self):
        a = _assess("delete the production database", risk_tier="low",
                    action_type="write", environment="prod")
        assert a.model_misspecification_risk >= 0.8

    def test_consistent_labels_low_risk(self):
        a = _assess("read local report", risk_tier="low", action_type="read",
                    environment="staging")
        assert a.model_misspecification_risk < 0.6
        assert a.classification_confidence >= 0.8
        assert a.classification_alternatives == ()

    def test_tool_name_mutation_vs_read_label(self):
        a = _assess("look something up", action_type="read",
                    environment="staging", risk_tier="low",
                    tool_name="delete_account")
        assert a.model_misspecification_risk >= 0.7


class TestEnvironmentMismatch:
    def test_unknown_env_with_production_signal(self):
        a = _assess("restart the production servers", risk_tier="medium",
                    action_type="write", environment=None)
        assert a.environment_mismatch_detected
        assert a.environment_confidence <= 0.5

    def test_staging_label_with_production_signal(self):
        a = _assess("deploy hotfix to the live site", risk_tier="medium",
                    action_type="write", environment="staging")
        assert a.environment_mismatch_detected
        assert a.model_misspecification_risk >= 0.7

    def test_unknown_env_mutating_raises_risk(self):
        a = _assess("apply schema migration", risk_tier="medium",
                    action_type="write", environment=None)
        assert a.model_misspecification_risk >= 0.65

    def test_consistent_prod_env_confident(self):
        a = _assess("read service health dashboard", risk_tier="low",
                    action_type="read", environment="prod")
        assert not a.environment_mismatch_detected
        assert a.environment_confidence >= 0.8


class TestObjectiveAmbiguity:
    def test_ambiguous_objective_on_mutation(self):
        a = _assess("clean up users", risk_tier="medium", action_type="write",
                    environment="staging")
        assert a.objective_ambiguity >= 0.5
        assert a.possible_objectives

    def test_optimize_dns_is_ambiguous(self):
        a = _assess("optimize DNS", risk_tier="medium", action_type="dns",
                    environment="prod")
        assert a.objective_ambiguity >= 0.5

    def test_clear_objective_not_ambiguous(self):
        a = _assess("read local report", risk_tier="low", action_type="read",
                    environment="dev")
        assert a.objective_ambiguity < 0.5


class TestRollbackAndStateTransition:
    def test_destructive_unknown_rollback_uncertain(self):
        a = _assess("delete old customer records", risk_tier="high",
                    action_type="delete", environment="prod",
                    rollback_available=None)
        assert a.state_transition_uncertain
        assert a.rollback_available is None

    def test_known_rollback_not_uncertain(self):
        a = _assess("delete old customer records", risk_tier="high",
                    action_type="delete", environment="prod",
                    rollback_available=True)
        assert not a.state_transition_uncertain
        assert a.rollback_available is True

    def test_read_only_never_uncertain(self):
        a = _assess("list open tickets", risk_tier="low", action_type="read",
                    environment="dev", rollback_available=None)
        assert not a.state_transition_uncertain


class TestDangerousArguments:
    def test_force_keys_raise_risk(self):
        a = _assess("apply configuration", risk_tier="medium",
                    action_type="write", environment="staging",
                    tool_arguments={"force": True, "cascade": True})
        assert a.model_misspecification_risk >= 0.5
        assert any("force" in r for r in a.reasons)

    def test_benign_args_no_flag(self):
        a = _assess("read record", risk_tier="low", action_type="read",
                    environment="dev", tool_arguments={"id": "u-1"})
        assert all("force" not in r for r in a.reasons)


class TestVisibility:
    def test_incomplete_metadata_in_reasons(self):
        a = _assess("do the thing")
        assert any("metadata incomplete" in r for r in a.reasons)
        assert a.model_misspecification_risk >= 0.3

    def test_deterministic(self):
        kwargs = dict(risk_tier="low", action_type="read", environment="prod")
        first = _assess("DROP TABLE users", **kwargs)
        for _ in range(3):
            assert _assess("DROP TABLE users", **kwargs) == first
