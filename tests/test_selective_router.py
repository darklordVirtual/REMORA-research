"""Unit tests for remora.selective.risk_coverage.

Verifies mathematical contracts: monotonicity, threshold arithmetic,
and router action transitions. No oracle calls, no artifacts.
"""
from __future__ import annotations

import pytest

from remora.selective.risk_coverage import (
    SelectiveAction,
    SelectiveRouter,
    risk_coverage_curve,
    threshold_for_target_risk,
)


# ── risk_coverage_curve ───────────────────────────────────────────────────────

class TestRiskCoverageCurve:
    def test_coverage_is_monotonically_increasing(self) -> None:
        scores = [0.9, 0.7, 0.5, 0.3]
        labels = [True, True, False, False]
        curve = risk_coverage_curve(scores, labels)
        coverages = [row["coverage"] for row in curve]
        assert coverages == sorted(coverages)

    def test_perfect_scores_have_zero_risk(self) -> None:
        scores = [0.9, 0.8, 0.7]
        labels = [True, True, True]
        curve = risk_coverage_curve(scores, labels)
        for row in curve:
            assert row["risk"] == pytest.approx(0.0)

    def test_worst_scores_have_full_risk(self) -> None:
        scores = [0.9, 0.8, 0.7]
        labels = [False, False, False]
        curve = risk_coverage_curve(scores, labels)
        for row in curve:
            assert row["risk"] == pytest.approx(1.0)

    def test_empty_input_returns_empty(self) -> None:
        assert risk_coverage_curve([], []) == []

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            risk_coverage_curve([0.5], [True, False])

    def test_sorted_by_score_descending(self) -> None:
        # First row should be the highest-score item
        scores = [0.3, 0.9, 0.6]
        labels = [False, True, True]
        curve = risk_coverage_curve(scores, labels)
        assert curve[0]["threshold"] == pytest.approx(0.9)

    def test_final_coverage_is_one(self) -> None:
        scores = [0.9, 0.5, 0.1]
        labels = [True, False, True]
        curve = risk_coverage_curve(scores, labels)
        assert curve[-1]["coverage"] == pytest.approx(1.0)

    def test_risk_accuracy_sum_to_one(self) -> None:
        scores = [0.8, 0.6, 0.4, 0.2]
        labels = [True, True, False, False]
        curve = risk_coverage_curve(scores, labels)
        for row in curve:
            assert abs(row["risk"] + row["accuracy"] - 1.0) < 1e-12

    def test_returns_correct_fields(self) -> None:
        curve = risk_coverage_curve([0.5], [True])
        required = {"threshold", "accepted", "coverage", "accuracy", "risk"}
        assert required.issubset(curve[0].keys())


# ── threshold_for_target_risk ─────────────────────────────────────────────────

class TestThresholdForTargetRisk:
    def test_impossible_target_returns_above_one(self) -> None:
        # All items wrong — no threshold can achieve risk=0.0
        scores = [0.9, 0.7]
        labels = [False, False]
        t = threshold_for_target_risk(scores, labels, target_risk=0.0)
        assert t > 1.0

    def test_trivial_target_full_coverage(self) -> None:
        # target_risk=1.0 is always achievable
        scores = [0.9, 0.7, 0.3]
        labels = [True, False, True]
        t = threshold_for_target_risk(scores, labels, target_risk=1.0)
        assert t <= 1.0

    def test_threshold_is_a_score_in_the_input(self) -> None:
        scores = [0.9, 0.7, 0.5, 0.3]
        labels = [True, True, False, False]
        t = threshold_for_target_risk(scores, labels, target_risk=0.2)
        # Threshold should come from the coverage curve, which uses input scores
        assert any(abs(t - s) < 1e-9 for s in scores) or t > 1.0


# ── SelectiveRouter ───────────────────────────────────────────────────────────

class TestSelectiveRouter:
    def _balanced_calibration(self) -> tuple[list[float], list[bool]]:
        """Calibration set where high scores are correct, low scores wrong."""
        scores = [0.95, 0.90, 0.85, 0.80, 0.20, 0.15, 0.10, 0.05]
        labels = [True,  True,  True,  True,  False, False, False, False]
        return scores, labels

    def test_fit_returns_threshold(self) -> None:
        scores, labels = self._balanced_calibration()
        router = SelectiveRouter(target_risk=0.1)
        t = router.fit(scores, labels)
        assert isinstance(t, float)

    def test_high_score_is_accepted(self) -> None:
        scores, labels = self._balanced_calibration()
        router = SelectiveRouter(target_risk=0.1)
        router.fit(scores, labels)
        decision = router.route(0.95)
        assert decision.action in (SelectiveAction.ACCEPT, SelectiveAction.VERIFY)

    def test_low_score_is_abstained(self) -> None:
        scores, labels = self._balanced_calibration()
        router = SelectiveRouter(target_risk=0.05)
        router.fit(scores, labels)
        decision = router.route(0.0)
        assert decision.action in (SelectiveAction.ABSTAIN, SelectiveAction.ESCALATE)

    def test_impossible_threshold_routes_all_to_abstain(self) -> None:
        # All items wrong — threshold >1.0 → every score below threshold
        scores = [0.9, 0.7]
        labels = [False, False]
        router = SelectiveRouter(target_risk=0.0)
        router.fit(scores, labels)
        for s in [0.9, 0.7, 0.5, 0.1]:
            d = router.route(s)
            assert d.action in (SelectiveAction.ABSTAIN, SelectiveAction.ESCALATE)

    def test_route_decision_contains_required_fields(self) -> None:
        scores, labels = self._balanced_calibration()
        router = SelectiveRouter(target_risk=0.1)
        router.fit(scores, labels)
        d = router.route(0.8)
        assert hasattr(d, "action")
        assert hasattr(d, "threshold")
        assert hasattr(d, "score")
        assert hasattr(d, "target_risk")
        assert hasattr(d, "reason")

    def test_score_attribute_matches_input(self) -> None:
        scores, labels = self._balanced_calibration()
        router = SelectiveRouter(target_risk=0.1)
        router.fit(scores, labels)
        d = router.route(0.42)
        assert d.score == pytest.approx(0.42)

    def test_target_risk_in_decision_matches_constructor(self) -> None:
        scores, labels = self._balanced_calibration()
        target = 0.07
        router = SelectiveRouter(target_risk=target)
        router.fit(scores, labels)
        d = router.route(0.5)
        assert d.target_risk == pytest.approx(target)

    def test_verify_zone_is_between_abstain_and_accept(self) -> None:
        scores, labels = self._balanced_calibration()
        router = SelectiveRouter(target_risk=0.1, verify_margin=0.10)
        router.fit(scores, labels)
        thr = router.threshold
        # Score just below threshold but within margin should be VERIFY
        if thr > 0.10 and thr <= 1.0:
            near_threshold = thr - (router.verify_margin / 2)
            d = router.route(near_threshold)
            assert d.action == SelectiveAction.VERIFY
