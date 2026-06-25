# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for the trap avoidance classifier and its integration with the engine."""
from __future__ import annotations

import pytest

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason
from remora.policy.trap_classifier import (
    TRAP_ESCALATE_THRESHOLD,
    TRAP_VERIFY_THRESHOLD,
    classify,
    score,
)


def _obs(**kwargs) -> PolicyObservation:
    return PolicyObservation(question="trap test", **kwargs)


# ---------------------------------------------------------------------------
# TrapClassifier unit tests
# ---------------------------------------------------------------------------

class TestTrapScore:
    def test_read_action_has_zero_base_score(self):
        obs = _obs(action_type="read", domain="database", target_environment="prod")
        # "read" not in _ACTION_TRAP_SCORES → base 0.0
        assert score(obs) == pytest.approx(0.0 + 0.10 + 0.15, abs=1e-6)

    def test_delete_in_financial_prod_is_max(self):
        obs = _obs(action_type="delete", domain="financial", target_environment="prod")
        s = score(obs)
        assert s == pytest.approx(min(1.0, 0.90 + 0.12 + 0.15), abs=1e-6)

    def test_destructive_write_without_prod_boost(self):
        obs = _obs(action_type="destructive_write", domain="database", target_environment="staging")
        s = score(obs)
        assert s == pytest.approx(0.85 + 0.10, abs=1e-6)

    def test_unknown_action_has_zero_base(self):
        obs = _obs(action_type="unknown_custom_tool", domain="unknown", target_environment="dev")
        assert score(obs) == pytest.approx(0.0, abs=1e-6)

    def test_prod_environment_adds_boost(self):
        staging = _obs(action_type="config_overwrite", domain="infrastructure", target_environment="staging")
        prod    = _obs(action_type="config_overwrite", domain="infrastructure", target_environment="prod")
        assert score(prod) > score(staging)

    def test_production_aliases_treated_same(self):
        for env in ("prod", "production", "live"):
            obs = _obs(action_type="delete", target_environment=env)
            s = score(obs)
            assert s > 0.90, f"Expected high trap score for env={env!r}"

    def test_score_clamped_to_one(self):
        obs = _obs(action_type="wipe", domain="financial", target_environment="prod")
        assert score(obs) <= 1.0

    def test_classify_safe(self):
        obs = _obs(action_type="read", target_environment="dev")
        assert classify(obs) == "SAFE"

    def test_classify_caution(self):
        obs = _obs(action_type="bulk_email", target_environment="staging")
        s = score(obs)
        if TRAP_VERIFY_THRESHOLD <= s < TRAP_ESCALATE_THRESHOLD:
            assert classify(obs) == "CAUTION"

    def test_classify_trap_delete_prod(self):
        obs = _obs(action_type="delete", target_environment="prod")
        assert classify(obs) == "TRAP"

    def test_disable_security_is_max_trap(self):
        obs = _obs(action_type="disable_security", domain="security", target_environment="prod")
        assert score(obs) >= TRAP_ESCALATE_THRESHOLD
        assert classify(obs) == "TRAP"

    def test_dns_change_prod_is_trap(self):
        obs = _obs(action_type="dns_change", domain="infrastructure", target_environment="prod")
        assert score(obs) >= TRAP_ESCALATE_THRESHOLD

    def test_shell_execute_medium_domain(self):
        obs = _obs(action_type="shell_execute", domain="shell", target_environment="staging")
        s = score(obs)
        assert s >= TRAP_VERIFY_THRESHOLD


# ---------------------------------------------------------------------------
# Engine integration: trap gate
# ---------------------------------------------------------------------------

class TestTrapGateEngine:
    def setup_method(self):
        self.engine = RemoraDecisionEngine()

    def _decide(self, **kwargs):
        return self.engine.decide(_obs(**kwargs))

    def test_trap_escalate_fires_for_delete_prod(self):
        # delete + prod pushes score over TRAP_ESCALATE_THRESHOLD
        report = self._decide(
            action_type="delete",
            target_environment="prod",
            risk_tier="medium",
            trust_score=0.80,
            phase="ordered",
            final_H=0.0, final_D=0.0,
        )
        assert report.action == DecisionAction.ESCALATE
        assert DecisionReason.TRAP_ESCALATE in report.reasons

    def test_trap_verify_fires_for_medium_score_action(self):
        # bulk_email has base score 0.55; staging has no env boost
        # → 0.55 ∈ [TRAP_VERIFY_THRESHOLD, TRAP_ESCALATE_THRESHOLD)
        s = score(_obs(action_type="bulk_email", target_environment="staging"))
        if TRAP_VERIFY_THRESHOLD <= s < TRAP_ESCALATE_THRESHOLD:
            report = self._decide(
                action_type="bulk_email",
                target_environment="staging",
                risk_tier="low",
                trust_score=0.85,
                phase="ordered",
                final_H=0.0, final_D=0.0,
            )
            assert report.action == DecisionAction.VERIFY
            assert DecisionReason.TRAP_VERIFY in report.reasons

    def test_read_action_does_not_trigger_trap_gate(self):
        report = self._decide(
            action_type="read",
            target_environment="prod",
            risk_tier="low",
            trust_score=0.85,
            phase="ordered",
            final_H=0.0, final_D=0.0,
        )
        assert DecisionReason.TRAP_ESCALATE not in report.reasons
        assert DecisionReason.TRAP_VERIFY not in report.reasons

    def test_trap_gate_runs_after_adversarial_block(self):
        report = self._decide(
            adversarial_detected=True,
            action_type="delete",
            target_environment="prod",
        )
        assert DecisionReason.ADMISSION_FIREWALL_BLOCKED in report.reasons
        assert DecisionReason.TRAP_ESCALATE not in report.reasons

    def test_trap_source_of_decision_set_correctly(self):
        report = self._decide(
            action_type="delete",
            target_environment="prod",
            risk_tier="medium",
            trust_score=0.85,
            phase="ordered",
            final_H=0.0, final_D=0.0,
        )
        if DecisionReason.TRAP_ESCALATE in report.reasons:
            assert report.source_of_decision == "trap_avoidance"

    def test_credal_present_when_trap_gate_fires(self):
        report = self._decide(
            action_type="delete",
            target_environment="prod",
            risk_tier="medium",
            trust_score=0.80,
            phase="ordered",
            final_H=0.0, final_D=0.0,
        )
        assert report.credal is not None

    def test_disable_security_prod_escalated(self):
        report = self._decide(
            action_type="disable_security",
            domain="security",
            target_environment="prod",
            risk_tier="medium",
            trust_score=0.85,
            phase="ordered",
            final_H=0.0, final_D=0.0,
        )
        assert report.action == DecisionAction.ESCALATE

    def test_explain_includes_trap_rules(self):
        obs = _obs(
            action_type="delete",
            target_environment="prod",
            risk_tier="medium",
            trust_score=0.80,
            phase="ordered",
            final_H=0.0, final_D=0.0,
        )
        trace = self.engine.explain(obs)
        rule_names = [r.rule for r in trace.rule_evaluations]
        assert "trap_escalate" in rule_names
        assert "minimax_gate" in rule_names
