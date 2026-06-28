# Author: Stian Skogbrott
# License: Apache-2.0
"""Mutation-detecting tests for remora/policy/decision_engine.py (REM-017).

Each test is designed to FAIL if a specific mutation is introduced to the policy
logic. These tests guard the critical safety invariants against accidental or
adversarial code changes.

Named mutations this file guards against:
  M_ADV:  adversarial_detected → ESCALATE downgraded to VERIFY
  M_SCHEMA: schema_valid=False → ESCALATE downgraded to VERIFY
  M_TOOL: tool_forbidden → ESCALATE downgraded to VERIFY
  M_COERCE: coercion_detected → ESCALATE downgraded to VERIFY
  M_TAINT: argument_tainted → ACCEPT instead of VERIFY
  M_TRUST0: ordered trust threshold changed from 0.72 to 0.0 (all ordered → ACCEPT)
  M_TRUST1: ordered trust threshold changed from 0.72 to 1.0 (no ordered → ACCEPT)
  M_EVCONF: evidence confidence threshold changed from 0.7 to 0.0 (all evidence → ACCEPT)
  M_CRIT:  critical phase + critical risk → downgraded from ESCALATE
  M_PROD:  production write + critical → downgraded from ESCALATE
  M_CONTRAD: contradiction_cycles>0 → ESCALATE changed to ABSTAIN (downgrade)
  M_PRIORITY: adversarial block fires AFTER (not before) trust check
  M_SCHEMA_NONE: schema_valid=None + mutating → ACCEPT instead of VERIFY (floor bypass)
  M_ABSTHRESH: trust<0.2 ABSTAIN threshold mutation (0.2 → 0.1)
  M_SESSION: session_cumulative_risk>0.80 threshold mutation
  M_NEGATION: inverted flag conditions (tool_forbidden=False but triggers ESCALATE)
"""
from __future__ import annotations

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction


def _obs(**kwargs) -> PolicyObservation:
    """Build a PolicyObservation with safe defaults."""
    defaults: dict = {
        "question": "test action",
        "phase": "ordered",
        "trust_score": 0.85,
        "risk_tier": "low",
        "adversarial_detected": False,
        "schema_valid": True,
        "tool_forbidden": False,
        "coercion_detected": False,
        "blackmail_pattern_detected": False,
        "argument_tainted": False,
        "counterfactual_passed": True,
        "evidence_contradictions": None,
        "evidence_action": None,
    }
    defaults.update(kwargs)
    return PolicyObservation(**defaults)


@pytest.fixture
def engine():
    return RemoraDecisionEngine()


class TestHardBlockMutations:
    """Guards against downgrading hard ESCALATE blocks (M_ADV, M_SCHEMA, M_TOOL, M_COERCE)."""

    def test_adversarial_detected_forces_escalate_not_verify(self, engine) -> None:
        """M_ADV: adversarial_detected must produce ESCALATE, never VERIFY or ACCEPT."""
        obs = _obs(adversarial_detected=True, trust_score=0.99, risk_tier="low")
        result = engine.decide(obs)
        assert result.action == DecisionAction.ESCALATE, (
            "M_ADV CAUGHT: adversarial_detected=True must always ESCALATE. "
            "If this fails, the adversarial gate was mutated to a weaker action."
        )

    def test_adversarial_not_detected_does_not_escalate_on_flag(self, engine) -> None:
        """M_NEGATION: adversarial_detected=False with high trust must not ESCALATE."""
        obs = _obs(adversarial_detected=False, trust_score=0.99, phase="ordered")
        result = engine.decide(obs)
        assert result.action != DecisionAction.ESCALATE, (
            "M_NEGATION CAUGHT: adversarial_detected=False should not ESCALATE. "
            "Gate is inverting the condition."
        )

    def test_schema_invalid_forces_escalate_not_verify(self, engine) -> None:
        """M_SCHEMA: schema_valid=False must produce ESCALATE, never VERIFY."""
        obs = _obs(schema_valid=False, trust_score=0.99, risk_tier="low")
        result = engine.decide(obs)
        assert result.action == DecisionAction.ESCALATE, (
            "M_SCHEMA CAUGHT: schema_valid=False must always ESCALATE. "
            "If this fails, the malformed-call gate was mutated to VERIFY."
        )

    def test_tool_forbidden_forces_escalate(self, engine) -> None:
        """M_TOOL: tool_forbidden=True must produce ESCALATE regardless of trust."""
        obs = _obs(tool_forbidden=True, trust_score=0.99, risk_tier="low")
        result = engine.decide(obs)
        assert result.action == DecisionAction.ESCALATE, (
            "M_TOOL CAUGHT: tool_forbidden=True must always ESCALATE."
        )

    def test_tool_not_forbidden_does_not_block_accept(self, engine) -> None:
        """M_NEGATION: tool_forbidden=False must not cause ESCALATE on its own."""
        obs = _obs(tool_forbidden=False, trust_score=0.99, phase="ordered", risk_tier="low")
        result = engine.decide(obs)
        # With high trust, ordered phase, low risk — should reach ACCEPT (with engine default thresholds)
        # or at least not ESCALATE due to tool_forbidden
        assert result.action != DecisionAction.ESCALATE, (
            "M_NEGATION CAUGHT: tool_forbidden=False should not cause ESCALATE."
        )

    def test_coercion_forces_escalate(self, engine) -> None:
        """M_COERCE: coercion_detected=True must ESCALATE."""
        obs = _obs(coercion_detected=True, trust_score=0.99)
        result = engine.decide(obs)
        assert result.action == DecisionAction.ESCALATE, (
            "M_COERCE CAUGHT: coercion_detected=True must always ESCALATE."
        )

    def test_blackmail_forces_escalate(self, engine) -> None:
        """Blackmail pattern detection must ESCALATE."""
        obs = _obs(blackmail_pattern_detected=True, trust_score=0.99)
        result = engine.decide(obs)
        assert result.action == DecisionAction.ESCALATE

    def test_counterfactual_failed_forces_escalate(self, engine) -> None:
        """counterfactual_passed=False must ESCALATE (not VERIFY or ABSTAIN)."""
        obs = _obs(counterfactual_passed=False, trust_score=0.99)
        result = engine.decide(obs)
        assert result.action == DecisionAction.ESCALATE, (
            "counterfactual_passed=False must ESCALATE, not be downgraded."
        )


class TestPriorityOrderMutations:
    """Guards against changing the priority order of rules (M_PRIORITY)."""

    def test_adversarial_beats_high_trust(self, engine) -> None:
        """M_PRIORITY: adversarial block must fire BEFORE ordered_high_trust accept."""
        engine_with_threshold = RemoraDecisionEngine(conformal_trust_threshold=0.50)
        obs = _obs(adversarial_detected=True, trust_score=0.99, phase="ordered", risk_tier="low")
        result = engine_with_threshold.decide(obs)
        assert result.action == DecisionAction.ESCALATE, (
            "M_PRIORITY CAUGHT: adversarial block (ESCALATE) must fire before "
            "trust-based ACCEPT. If ACCEPT, the priority order was changed."
        )

    def test_schema_invalid_beats_high_trust(self, engine) -> None:
        """M_PRIORITY: schema_valid=False ESCALATE must fire before trust ACCEPT."""
        obs = _obs(schema_valid=False, trust_score=0.99, phase="ordered", risk_tier="low")
        result = engine.decide(obs)
        assert result.action == DecisionAction.ESCALATE

    def test_tainted_argument_beats_high_trust(self, engine) -> None:
        """M_PRIORITY: argument_tainted VERIFY must fire before ordered_high_trust ACCEPT."""
        obs = _obs(argument_tainted=True, trust_score=0.99, phase="ordered", risk_tier="low")
        result = engine.decide(obs)
        assert result.action == DecisionAction.VERIFY, (
            "M_PRIORITY CAUGHT: argument_tainted=True must VERIFY, not reach ACCEPT. "
            "Priority order: tainted floor fires before trust check."
        )


class TestThresholdMutations:
    """Guards against threshold value mutations (M_TRUST0, M_TRUST1, M_EVCONF, M_ABSTHRESH)."""

    def test_ordered_trust_at_exact_threshold_accepts(self) -> None:
        """M_TRUST1: trust=0.72 exactly must ACCEPT on ordered phase (>= not >)."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            phase="ordered", trust_score=0.72, risk_tier="low",
            counterfactual_passed=True, evidence_contradictions=None,
        )
        result = eng.decide(obs)
        assert result.action == DecisionAction.ACCEPT, (
            "M_TRUST1 CAUGHT: trust=0.72 on ordered phase should ACCEPT "
            "(threshold is >=0.72, not >0.72). If ABSTAIN, threshold was mutated."
        )

    def test_ordered_trust_below_threshold_does_not_accept(self) -> None:
        """M_TRUST0: trust=0.719 must not ACCEPT — catches threshold lowered to 0.0."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            phase="ordered", trust_score=0.719, risk_tier="low",
            counterfactual_passed=True, evidence_contradictions=None,
        )
        result = eng.decide(obs)
        assert result.action != DecisionAction.ACCEPT, (
            "M_TRUST0 CAUGHT: trust=0.719 (just below 0.72) must not ACCEPT. "
            "If ACCEPT, the threshold was mutated downward."
        )

    def test_evidence_confidence_at_threshold_accepts(self) -> None:
        """M_EVCONF: evidence_confidence=0.7 exactly must ACCEPT on ordered phase."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            phase="ordered", trust_score=0.80,
            evidence_action="answer", evidence_confidence=0.7,
            evidence_contradictions=None, counterfactual_passed=True,
            risk_tier="low",
        )
        result = eng.decide(obs)
        assert result.action == DecisionAction.ACCEPT, (
            "M_EVCONF CAUGHT: evidence_confidence=0.7 with answer+ordered must ACCEPT "
            "(threshold >=0.7, not >0.7). If ABSTAIN, threshold was mutated."
        )

    def test_evidence_confidence_below_threshold_no_accept(self) -> None:
        """M_EVCONF: evidence_confidence=0.699 must not ACCEPT."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            phase="ordered", trust_score=0.50,
            evidence_action="answer", evidence_confidence=0.699,
            evidence_contradictions=None, counterfactual_passed=True,
            risk_tier="low",
        )
        result = eng.decide(obs)
        assert result.action != DecisionAction.ACCEPT, (
            "M_EVCONF CAUGHT: evidence_confidence=0.699 must not ACCEPT. "
            "If ACCEPT, the 0.7 threshold was mutated downward."
        )

    def test_abstain_threshold_at_exactly_0_2(self) -> None:
        """M_ABSTHRESH: trust=0.2 must not ABSTAIN (threshold is <0.2, not <=0.2)."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            phase="ordered", trust_score=0.2,
            evidence_action=None, risk_tier="low",
        )
        result = eng.decide(obs)
        # trust=0.2 is NOT < 0.2, so ABSTAIN should NOT fire on this alone
        # (may still ABSTAIN for other reasons, but not the low_trust_abstain path)
        from remora.policy.report import DecisionReason
        assert DecisionReason.LOW_TRUST not in result.reasons, (
            "M_ABSTHRESH CAUGHT: LOW_TRUST should not fire at trust=0.2 "
            "(condition is trust<0.2, not trust<=0.2)."
        )

    def test_abstain_threshold_below_0_2_fires(self) -> None:
        """M_ABSTHRESH: trust=0.199 (below 0.2) should trigger LOW_TRUST abstain."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            phase="ordered", trust_score=0.199,
            evidence_action=None, risk_tier="low",
            evidence_contradictions=None,
        )
        result = eng.decide(obs)
        # Depending on other path conditions, should ABSTAIN or at least have LOW_TRUST reason
        from remora.policy.report import DecisionReason
        assert DecisionReason.LOW_TRUST in result.reasons or result.action == DecisionAction.ABSTAIN, (
            "M_ABSTHRESH CAUGHT: trust=0.199 should trigger LOW_TRUST. "
            "If not triggered, abstain threshold was mutated."
        )


class TestCriticalPathMutations:
    """Guards against mutations in critical/production-write paths (M_CRIT, M_PROD)."""

    def test_critical_phase_critical_risk_escalates(self) -> None:
        """M_CRIT: phase=critical + risk_tier=critical must ESCALATE (not VERIFY)."""
        eng = RemoraDecisionEngine()
        obs = _obs(phase="critical", risk_tier="critical", trust_score=0.99)
        result = eng.decide(obs)
        assert result.action == DecisionAction.ESCALATE, (
            "M_CRIT CAUGHT: phase=critical AND risk_tier=critical must ESCALATE. "
            "If VERIFY, the ESCALATE was mutated to a weaker action."
        )

    def test_critical_phase_high_risk_does_not_escalate_from_crit_gate(self) -> None:
        """M_CRIT: phase=critical AND risk_tier=high must NOT trigger the critical+critical gate."""
        eng = RemoraDecisionEngine()
        obs = _obs(phase="critical", risk_tier="high", trust_score=0.50, evidence_action=None)
        result = eng.decide(obs)
        # high+critical gate fires on risk_tier='critical' only — but high risk with no evidence -> VERIFY
        # Verify the critical+critical ESCALATE path doesn't expand to include 'high'
        from remora.policy.report import DecisionReason
        assert DecisionReason.CRITICAL_PHASE not in [r for r in result.reasons
                                                      if r.value == "critical_phase"
                                                      and result.action == DecisionAction.ESCALATE
                                                      and obs.risk_tier == "high"], (
            "M_CRIT CAUGHT: critical_phase+critical_risk gate should only fire when risk_tier='critical'."
        )

    def test_production_write_critical_risk_escalates(self) -> None:
        """M_PROD: delete to production with critical risk must ESCALATE."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            action_type="delete",
            target_environment="production",
            risk_tier="critical",
            trust_score=0.99,
            evidence_action="answer",
            evidence_confidence=0.99,
        )
        result = eng.decide(obs)
        assert result.action == DecisionAction.ESCALATE, (
            "M_PROD CAUGHT: production write + critical risk must ESCALATE. "
            "If ACCEPT, the production-write matrix was mutated."
        )

    def test_production_write_high_risk_verifies_not_accepts(self) -> None:
        """M_PROD: delete to production with high risk must VERIFY, not ACCEPT."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            action_type="delete",
            target_environment="production",
            risk_tier="high",
            trust_score=0.99,
            evidence_action="answer",
            evidence_confidence=0.99,
        )
        result = eng.decide(obs)
        assert result.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE), (
            "M_PROD CAUGHT: production write + high risk must VERIFY or ESCALATE, not ACCEPT."
        )


class TestContradictionMutations:
    """Guards against mutations in contradiction path (M_CONTRAD)."""

    def test_contradiction_with_cycles_escalates(self) -> None:
        """M_CONTRAD: evidence_contradictions>0 + contradiction_cycles>0 must ESCALATE."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            evidence_contradictions=1,
            contradiction_cycles=1,
            trust_score=0.99,
        )
        result = eng.decide(obs)
        assert result.action == DecisionAction.ESCALATE, (
            "M_CONTRAD CAUGHT: contradiction + cycles>0 must ESCALATE (not ABSTAIN). "
            "If ABSTAIN, the contradiction_cycles>0 branch was mutated to ignore cycles."
        )

    def test_contradiction_without_cycles_abstains(self) -> None:
        """M_CONTRAD: evidence_contradictions>0 + contradiction_cycles=0 must ABSTAIN (not ESCALATE)."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            evidence_contradictions=1,
            contradiction_cycles=0,
            trust_score=0.99,
        )
        result = eng.decide(obs)
        assert result.action == DecisionAction.ABSTAIN, (
            "M_CONTRAD CAUGHT: contradiction without cycles must ABSTAIN. "
            "If ESCALATE, the OR condition was mutated to always escalate."
        )

    def test_zero_contradictions_does_not_block_accept(self) -> None:
        """M_CONTRAD: evidence_contradictions=0 must not trigger contradiction gate."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            evidence_contradictions=0,
            contradiction_cycles=0,
            phase="ordered",
            trust_score=0.99,
            risk_tier="low",
        )
        result = eng.decide(obs)
        from remora.policy.report import DecisionReason
        assert DecisionReason.EVIDENCE_CONTRADICTED not in result.reasons, (
            "M_CONTRAD CAUGHT: evidence_contradictions=0 should not trigger contradiction gate."
        )


class TestSchemaFloorMutations:
    """Guards against mutation that bypasses schema_valid=None floor (M_SCHEMA_NONE)."""

    def test_schema_none_mutating_action_verifies(self) -> None:
        """M_SCHEMA_NONE: schema_valid=None + mutating action_type must VERIFY, not ACCEPT."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            schema_valid=None,
            action_type="write",
            phase="ordered",
            trust_score=0.99,
            risk_tier="low",
            evidence_contradictions=None,
        )
        result = eng.decide(obs)
        assert result.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE), (
            "M_SCHEMA_NONE CAUGHT: schema_valid=None + mutating action must not ACCEPT. "
            "If ACCEPT, the schema_unverified_mutating floor was removed or bypassed."
        )

    def test_schema_none_readonly_action_can_proceed(self) -> None:
        """M_SCHEMA_NONE: schema_valid=None + read action must not be blocked by mutating floor."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            schema_valid=None,
            action_type="read",
            phase="ordered",
            trust_score=0.99,
            risk_tier="low",
            evidence_contradictions=None,
        )
        result = eng.decide(obs)
        from remora.policy.report import DecisionReason
        assert DecisionReason.SCHEMA_UNVERIFIED_VERIFY not in result.reasons, (
            "M_SCHEMA_NONE CAUGHT: schema_valid=None + read action must NOT trigger "
            "SCHEMA_UNVERIFIED_VERIFY (floor only applies to mutating actions)."
        )


class TestSessionRiskMutations:
    """Guards against mutations in session risk thresholds (M_SESSION)."""

    def test_session_risk_above_threshold_verifies(self) -> None:
        """M_SESSION: session_cumulative_risk=0.81 must VERIFY (threshold=0.80)."""
        eng = RemoraDecisionEngine()
        obs = _obs(session_cumulative_risk=0.81, phase="ordered", risk_tier="low")
        result = eng.decide(obs)
        assert result.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE), (
            "M_SESSION CAUGHT: session_cumulative_risk=0.81 must VERIFY. "
            "If ACCEPT, the 0.80 threshold was mutated upward."
        )

    def test_session_risk_at_threshold_does_not_verify(self) -> None:
        """M_SESSION: session_cumulative_risk=0.80 must NOT trigger session_risk_verify (> not >=)."""
        eng = RemoraDecisionEngine()
        obs = _obs(
            session_cumulative_risk=0.80, phase="ordered", trust_score=0.99, risk_tier="low"
        )
        result = eng.decide(obs)
        from remora.policy.report import DecisionReason
        assert DecisionReason.SESSION_RISK_VERIFY not in result.reasons, (
            "M_SESSION CAUGHT: session_cumulative_risk=0.80 must not trigger SESSION_RISK_VERIFY "
            "(condition is >0.80, not >=0.80)."
        )
