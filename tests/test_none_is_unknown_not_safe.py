# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for PR 2: None-is-unknown-not-safe.

Three specific gaps from the audit:

GAP A: counterfactual_passed=None permits ACCEPT for high-impact actions.
  - For high/critical risk_tier OR production-write action types, a missing
    counterfactual gate should VERIFY rather than silently allow through.
  - None means "test not run", not "test passed".

GAP B: schema_valid=None permits ACCEPT.
  - If the schema validator did not run (None), the call is UNVERIFIED, not VALID.
  - For non-read-only actions, unverified schema must VERIFY.

GAP C: evidence_contradictions=None with high/critical risk tier VERIFIES
  rather than allowing through as "no contradictions found".
  - None means "evidence pipeline did not run", not "no contradictions".
  - For high/critical risk, unknown evidence state must VERIFY.
"""
from __future__ import annotations

import pytest
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason


engine = RemoraDecisionEngine()


def _obs(**kwargs) -> PolicyObservation:
    return PolicyObservation(question="test action", **kwargs)


# ===========================================================================
# GAP A: counterfactual_passed=None for high-impact actions
# ===========================================================================

class TestCounterfactualNoneIsNotSafeForHighImpact:
    """counterfactual_passed=None must not permit ACCEPT for high-impact actions."""

    @pytest.mark.parametrize("risk_tier", ["high", "critical"])
    def test_counterfactual_none_high_critical_risk_not_accept(self, risk_tier):
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier=risk_tier, counterfactual_passed=None,
        )
        report = engine.decide(obs)
        # high/critical risk already routes to VERIFY via evidence_insufficient,
        # but if callers bypass that (e.g. via evidence_action), counterfactual=None
        # must still not produce ACCEPT.
        assert report.action != DecisionAction.ACCEPT, (
            f"counterfactual_passed=None + risk_tier={risk_tier!r} must not ACCEPT"
        )

    def test_counterfactual_none_production_write_not_accept(self):
        """Production write with missing counterfactual gate must not ACCEPT."""
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier="medium",
            action_type="production_write",
            target_environment="production",
            counterfactual_passed=None,
        )
        report = engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT, (
            "production_write + target=production + counterfactual=None must not ACCEPT"
        )

    @pytest.mark.parametrize("action_type", [
        "destructive_write", "delete", "emergency_write",
    ])
    def test_counterfactual_none_high_trap_action_not_accept(self, action_type):
        """High-trap actions with missing counterfactual gate must not ACCEPT."""
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier="medium", action_type=action_type,
            counterfactual_passed=None,
        )
        report = engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT

    def test_counterfactual_none_low_risk_read_can_accept(self):
        """Low-risk read action with counterfactual=None is fine — test is optional."""
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier="low", action_type="read",
            counterfactual_passed=None,
        )
        report = engine.decide(obs)
        assert report.action == DecisionAction.ACCEPT

    def test_counterfactual_true_high_risk_can_still_verify(self):
        """counterfactual_passed=True with high risk still routes to VERIFY (evidence gate)."""
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier="high", counterfactual_passed=True,
        )
        report = engine.decide(obs)
        # high risk without evidence → VERIFY regardless of counterfactual
        assert report.action == DecisionAction.VERIFY

    def test_reason_code_present_when_counterfactual_none_blocks(self):
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier="high",
            evidence_action="evidence_accept",  # bypass evidence gate
            evidence_confidence=0.9,
            counterfactual_passed=None,
        )
        report = engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT
        reason_values = [r.value for r in report.reasons]
        assert DecisionReason.COUNTERFACTUAL_UNKNOWN_VERIFY.value in reason_values, (
            f"Expected COUNTERFACTUAL_UNKNOWN_VERIFY in reasons, got {reason_values}"
        )


# ===========================================================================
# GAP B: schema_valid=None for non-read-only actions
# ===========================================================================

class TestSchemaValidNoneIsNotSafe:
    """schema_valid=None (unverified) must VERIFY for non-read-only actions."""

    @pytest.mark.parametrize("action_type", [
        "write", "delete", "config_change", "production_write",
    ])
    def test_schema_none_mutating_not_accept(self, action_type):
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier="low", action_type=action_type,
            schema_valid=None,
        )
        report = engine.decide(obs)
        assert report.action != DecisionAction.ACCEPT, (
            f"schema_valid=None + action_type={action_type!r} must not ACCEPT"
        )

    @pytest.mark.parametrize("action_type", [
        "write", "delete",
    ])
    def test_schema_none_mutating_routes_to_verify_or_escalate(self, action_type):
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier="low", action_type=action_type,
            schema_valid=None,
        )
        report = engine.decide(obs)
        assert report.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE)

    def test_schema_none_read_only_can_accept(self):
        """Read-only action with schema_valid=None is acceptable."""
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier="low", action_type="read",
            schema_valid=None,
        )
        report = engine.decide(obs)
        assert report.action == DecisionAction.ACCEPT

    def test_schema_false_still_escalates(self):
        """schema_valid=False must still ESCALATE (existing behaviour preserved)."""
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier="low", schema_valid=False,
        )
        report = engine.decide(obs)
        assert report.action == DecisionAction.ESCALATE

    def test_reason_code_present_when_schema_none_blocks(self):
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier="low", action_type="write",
            schema_valid=None,
        )
        report = engine.decide(obs)
        reason_values = [r.value for r in report.reasons]
        assert DecisionReason.SCHEMA_UNVERIFIED_VERIFY.value in reason_values, (
            f"Expected SCHEMA_UNVERIFIED_VERIFY in reasons, got {reason_values}"
        )


# ===========================================================================
# GAP C: evidence_contradictions=None with high/critical risk
# ===========================================================================

class TestEvidenceContradictionsNoneHighRisk:
    """evidence_contradictions=None + high/critical risk is unknown, not clean."""

    @pytest.mark.parametrize("risk_tier", ["high", "critical"])
    def test_contradictions_none_high_critical_not_accept(self, risk_tier):
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier=risk_tier,
            evidence_action="evidence_accept",
            evidence_confidence=0.9,
            evidence_contradictions=None,  # pipeline did not run
        )
        report = engine.decide(obs)
        # Already guarded by evidence_insufficient + critical catch-all,
        # but verifying the gap doesn't open a new path
        assert report.action != DecisionAction.ACCEPT

    def test_contradictions_none_low_risk_evidence_accept_can_accept(self):
        """Low-risk action with evidence_accept and None contradictions is fine."""
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier="low",
            evidence_action="evidence_accept",
            evidence_confidence=0.9,
            evidence_contradictions=None,
        )
        report = engine.decide(obs)
        assert report.action == DecisionAction.ACCEPT

    def test_contradictions_zero_still_allows_evidence_accept(self):
        """Explicit zero contradictions (pipeline ran, found none) is clean."""
        obs = _obs(
            phase="ordered", trust_score=0.95,
            risk_tier="low",
            evidence_action="evidence_accept",
            evidence_confidence=0.9,
            evidence_contradictions=0,
        )
        report = engine.decide(obs)
        assert report.action == DecisionAction.ACCEPT


# ── Unknown action-type floor (external security audit, 2026-07-03) ──────────

def _obs_uat(**kw):
    from remora.policy import PolicyObservation
    return PolicyObservation(question="uat probe", **kw)


def test_unknown_action_type_floored_to_verify():
    """A non-empty, unrecognised action_type must not reach ACCEPT on low risk
    + high trust — it is floored to VERIFY (deny-by-default for actuation)."""
    from remora.policy import RemoraDecisionEngine
    from remora.policy.report import DecisionReason

    engine = RemoraDecisionEngine()
    obs = _obs_uat(
        action_type="frobnicate_widget",   # not in any known set
        risk_tier="low",
        phase="ordered",
        trust_score=0.99,
        schema_valid=True,
    )
    report = engine.decide(obs)
    assert report.action.value == "verify"
    assert DecisionReason.UNKNOWN_ACTION_TYPE_VERIFY in report.reasons


def test_none_action_type_still_reaches_accept():
    """action_type=None (pure QA / no tool call) is NOT floored."""
    from remora.policy import RemoraDecisionEngine

    engine = RemoraDecisionEngine()
    obs = _obs_uat(
        action_type=None,
        risk_tier="low",
        phase="ordered",
        trust_score=0.99,
        evidence_action="answer",
        evidence_confidence=0.95,
    )
    assert engine.decide(obs).action.value == "accept"


def test_known_readonly_action_type_not_floored():
    from remora.policy import RemoraDecisionEngine

    engine = RemoraDecisionEngine()
    obs = _obs_uat(
        action_type="read",
        risk_tier="low",
        phase="ordered",
        trust_score=0.99,
        evidence_action="answer",
        evidence_confidence=0.95,
    )
    assert engine.decide(obs).action.value == "accept"


def test_unknown_action_type_does_not_override_hard_blocks():
    """The floor is a VERIFY floor — a hard ESCALATE still wins."""
    from remora.policy import RemoraDecisionEngine

    engine = RemoraDecisionEngine()
    obs = _obs_uat(action_type="frobnicate_widget", adversarial_detected=True)
    assert engine.decide(obs).action.value == "escalate"
