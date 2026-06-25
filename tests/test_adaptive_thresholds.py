"""Tests for Adaptive Policy Thresholds."""
import time

from remora.policy.adaptive_thresholds import (
    AdaptiveThresholdEngine,
    OutcomeRecord,
    OutcomeType,
)


def _outcome(outcome: OutcomeType, domain: str = "test", risk: str = "medium", ts: float | None = None) -> OutcomeRecord:
    return OutcomeRecord(
        timestamp=ts or time.time(),
        outcome=outcome,
        domain=domain,
        risk_tier=risk,
        confidence_at_decision=0.7,
    )


class TestAdaptiveThresholdEngine:
    def test_register_and_get(self):
        engine = AdaptiveThresholdEngine()
        engine.register_threshold("confidence_min", 0.5, min_value=0.2, max_value=0.95)
        assert engine.get_threshold("confidence_min") == 0.5

    def test_tightens_on_false_accepts(self):
        engine = AdaptiveThresholdEngine(tightening_rate=0.2)
        engine.register_threshold("t", 0.5)
        for _ in range(10):
            engine.record_outcome(_outcome(OutcomeType.FALSE_ACCEPT))
        report = engine.adapt()
        assert report.thresholds_adjusted > 0
        assert engine.get_threshold("t") > 0.5

    def test_tightens_hard_on_safety_violation(self):
        engine = AdaptiveThresholdEngine(tightening_rate=0.2)
        engine.register_threshold("t", 0.5)
        engine.record_outcome(_outcome(OutcomeType.SAFETY_VIOLATION))
        report = engine.adapt()
        assert engine.get_threshold("t") > 0.5
        assert report.safety_violation_count == 1

    def test_relaxes_on_clean_record_with_false_blocks(self):
        engine = AdaptiveThresholdEngine(relaxation_rate=0.1)
        engine.register_threshold("t", 0.5)
        # Start with a tightened threshold
        engine._thresholds["t"].current_value = 0.7
        for _ in range(10):
            engine.record_outcome(_outcome(OutcomeType.FALSE_BLOCK))
        engine.adapt()
        assert engine.get_threshold("t") < 0.7

    def test_no_change_on_empty(self):
        engine = AdaptiveThresholdEngine()
        engine.register_threshold("t", 0.5)
        report = engine.adapt()
        assert report.thresholds_adjusted == 0
        assert engine.get_threshold("t") == 0.5

    def test_locked_threshold_not_adjusted(self):
        engine = AdaptiveThresholdEngine()
        engine.register_threshold("t", 0.5)
        engine.lock_threshold("t")
        for _ in range(10):
            engine.record_outcome(_outcome(OutcomeType.FALSE_ACCEPT))
        engine.adapt()
        assert engine.get_threshold("t") == 0.5

    def test_unlock_allows_adjustment(self):
        engine = AdaptiveThresholdEngine(tightening_rate=0.2)
        engine.register_threshold("t", 0.5)
        engine.lock_threshold("t")
        for _ in range(10):
            engine.record_outcome(_outcome(OutcomeType.FALSE_ACCEPT))
        engine.adapt()
        assert engine.get_threshold("t") == 0.5
        engine.unlock_threshold("t")
        engine.adapt()
        assert engine.get_threshold("t") > 0.5

    def test_clamped_to_max(self):
        engine = AdaptiveThresholdEngine(tightening_rate=0.5)
        engine.register_threshold("t", 0.9, max_value=0.95)
        for _ in range(50):
            engine.record_outcome(_outcome(OutcomeType.FALSE_ACCEPT))
        engine.adapt()
        assert engine.get_threshold("t") <= 0.95

    def test_domain_filtering(self):
        engine = AdaptiveThresholdEngine(tightening_rate=0.2)
        engine.register_threshold("t", 0.5)
        for _ in range(10):
            engine.record_outcome(_outcome(OutcomeType.FALSE_ACCEPT, domain="finance"))
        report = engine.adapt(domain="other_domain")
        assert report.total_outcomes_considered == 0

    def test_report_structure(self):
        engine = AdaptiveThresholdEngine()
        engine.register_threshold("t", 0.5)
        engine.record_outcome(_outcome(OutcomeType.CORRECT_ACCEPT))
        report = engine.adapt()
        d = report.to_dict()
        assert "false_accept_rate" in d
        assert "false_block_rate" in d
        assert "safety_violation_count" in d
