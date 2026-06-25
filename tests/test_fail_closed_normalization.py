# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for fail-closed normalization of risk_tier / action_type / target_environment.

PR 1: Unknown or absent context fields must never silently bypass safety gates.

Design intent:
  - risk_tier = None or any string not in {low,medium,high,critical} → treated as "unknown"
  - unknown + mutating action (not read-only) → VERIFY
  - unknown + production environment → VERIFY
  - unknown + trap-classified destructive action → ESCALATE (via trap gate)
  - unknown + production + trap → ESCALATE

All tests are RED initially. Write minimal production code to pass them.
"""
from __future__ import annotations

import pytest
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason


engine = RemoraDecisionEngine()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _obs(**kwargs) -> PolicyObservation:
    return PolicyObservation(question="test action", **kwargs)


# ---------------------------------------------------------------------------
# risk_tier = None, mutating action → VERIFY
# ---------------------------------------------------------------------------

class TestUnknownRiskTierMutatingAction:
    """risk_tier absent + mutating action must never silently reach ACCEPT."""

    @pytest.mark.parametrize("action_type", [
        "write", "shell_write", "delete",
        "permission_change", "config_change",
        "production_write", "destructive_write",
    ])
    def test_none_risk_tier_mutating_action_is_not_accept(self, action_type):
        obs = _obs(
            phase="ordered", trust_score=0.95, risk_tier=None,
            action_type=action_type,
        )
        report = engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT, (
            f"risk_tier=None + action_type={action_type!r} must not ACCEPT, got {report.action}"
        )

    @pytest.mark.parametrize("action_type", [
        "write", "config_change",
    ])
    def test_none_risk_tier_mutating_action_routes_to_verify(self, action_type):
        obs = _obs(
            phase="ordered", trust_score=0.95, risk_tier=None,
            action_type=action_type,
        )
        report = engine.decide(obs)
        # VERIFY or ESCALATE are both acceptable; ACCEPT and ABSTAIN are not
        assert report.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE), (
            f"Expected VERIFY or ESCALATE, got {report.action}"
        )

    def test_unknown_risk_tier_string_mutating_action_is_not_accept(self):
        """risk_tier with unrecognised value (typo) must be treated as unknown."""
        for bad_tier in ("CRITICAL", "high_risk", "ultra", "0", ""):
            obs = _obs(
                phase="ordered", trust_score=0.95, risk_tier=bad_tier,
                action_type="write",
            )
            report = engine.decide(obs)
            assert report.action != DecisionAction.ACCEPT, (
                f"risk_tier={bad_tier!r} (unknown) + write must not ACCEPT, got {report.action}"
            )

    def test_read_only_action_with_none_risk_tier_can_accept(self):
        """Read-only action with no risk context should still be allowed."""
        obs = _obs(
            phase="ordered", trust_score=0.95, risk_tier=None,
            action_type="read",
        )
        report = engine.decide(obs)
        # Read-only + high trust should still be acceptable
        assert report.action == DecisionAction.ACCEPT, (
            f"read-only action with high trust should ACCEPT, got {report.action}"
        )


# ---------------------------------------------------------------------------
# risk_tier = None, production environment → VERIFY
# ---------------------------------------------------------------------------

class TestUnknownRiskTierProductionEnvironment:

    @pytest.mark.parametrize("target_env", ["prod", "production", "live"])
    def test_none_risk_tier_prod_env_is_not_accept(self, target_env):
        obs = _obs(
            phase="ordered", trust_score=0.95, risk_tier=None,
            target_environment=target_env,
        )
        report = engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT, (
            f"risk_tier=None + target_environment={target_env!r} must not ACCEPT"
        )

    @pytest.mark.parametrize("target_env", ["prod", "production", "live"])
    def test_none_risk_tier_prod_env_routes_to_verify_or_escalate(self, target_env):
        obs = _obs(
            phase="ordered", trust_score=0.95, risk_tier=None,
            target_environment=target_env,
        )
        report = engine.decide(obs)
        assert report.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE)

    def test_none_risk_tier_staging_env_can_accept(self):
        """Non-production environment with absent risk_tier + read-only is fine."""
        obs = _obs(
            phase="ordered", trust_score=0.95, risk_tier=None,
            action_type="read", target_environment="staging",
        )
        report = engine.decide(obs)
        assert report.action == DecisionAction.ACCEPT

    def test_unknown_string_risk_tier_prod_env_not_accept(self):
        obs = _obs(
            phase="ordered", trust_score=0.99, risk_tier="CRITICAL",
            target_environment="prod",
        )
        report = engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT


# ---------------------------------------------------------------------------
# risk_tier = None, destructive trap action → ESCALATE
# ---------------------------------------------------------------------------

class TestUnknownRiskTierTrapAction:

    @pytest.mark.parametrize("action_type", ["delete", "destructive_write"])
    def test_none_risk_tier_trap_action_escalates(self, action_type):
        """High-trap destructive action escalates even without explicit risk_tier."""
        obs = _obs(
            phase="ordered", trust_score=0.99, risk_tier=None,
            action_type=action_type, target_environment="staging",
        )
        report = engine.decide(obs)
        # Trap gate should fire here
        assert report.action == DecisionAction.ESCALATE, (
            f"action_type={action_type!r} with None risk_tier should ESCALATE via trap"
        )


# ---------------------------------------------------------------------------
# Reason code present when unknown tier gate fires
# ---------------------------------------------------------------------------

class TestUnknownRiskTierReasonCode:

    def test_unknown_risk_tier_reason_in_report(self):
        obs = _obs(
            phase="ordered", trust_score=0.95, risk_tier=None,
            action_type="write",
        )
        report = engine.decide(obs)
        reason_names = [r.value for r in report.reasons]
        assert DecisionReason.UNKNOWN_RISK_TIER_VERIFY.value in reason_names, (
            f"Expected UNKNOWN_RISK_TIER_VERIFY in reasons, got {reason_names}"
        )

    def test_known_risk_tier_has_no_unknown_reason(self):
        obs = _obs(
            phase="ordered", trust_score=0.95, risk_tier="high",
            action_type="write",
        )
        report = engine.decide(obs)
        reason_names = [r.value for r in report.reasons]
        assert "unknown_risk_tier_verify" not in reason_names


# ---------------------------------------------------------------------------
# Normalization is explicit, not silent
# ---------------------------------------------------------------------------

class TestNormalizationIdempotency:

    @pytest.mark.parametrize("known_tier", ["low", "medium", "high", "critical"])
    def test_known_risk_tiers_are_unaffected(self, known_tier):
        """Known tiers must behave identically before and after normalization."""
        obs_ordered_high_trust = _obs(
            phase="ordered", trust_score=0.95, risk_tier=known_tier,
            action_type="read",
        )
        report = engine.decide(obs_ordered_high_trust)
        # low/medium with read + ordered + high trust should accept
        if known_tier in ("low", "medium"):
            assert report.action == DecisionAction.ACCEPT

    def test_case_insensitive_normalization(self):
        """risk_tier string comparison is case-insensitive after normalisation."""
        obs_upper = _obs(phase="ordered", trust_score=0.95, risk_tier="HIGH", action_type="read")
        obs_lower = _obs(phase="ordered", trust_score=0.95, risk_tier="high", action_type="read")
        report_upper = engine.decide(obs_upper)
        report_lower = engine.decide(obs_lower)
        # Both should produce the same action
        assert report_upper.action == report_lower.action
