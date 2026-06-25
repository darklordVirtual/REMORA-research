"""Unit tests for remora.calibration.trust_calibrator.

These tests verify the mathematical contracts of each metric and the
calibrator workflow. They use only deterministic inputs and have no
dependency on oracle calls or external artifacts.
"""
from __future__ import annotations

import math
import warnings

import pytest

from remora.calibration.trust_calibrator import (
    TrustCalibrator,
    apply_temperature_scaling,
    brier_score,
    expected_calibration_error,
    log_loss,
    reliability_curve,
)


# ── Brier score ──────────────────────────────────────────────────────────────

class TestBrierScore:
    def test_perfect_predictor_is_zero(self) -> None:
        assert brier_score([1.0, 0.0, 1.0], [True, False, True]) == 0.0

    def test_worst_predictor_is_one(self) -> None:
        assert brier_score([0.0, 1.0], [True, False]) == 1.0

    def test_uniform_half_on_balanced(self) -> None:
        result = brier_score([0.5, 0.5], [True, False])
        assert abs(result - 0.25) < 1e-12

    def test_empty_input_returns_zero(self) -> None:
        assert brier_score([], []) == 0.0

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            brier_score([0.5, 0.5], [True])

    def test_range_is_zero_to_one(self) -> None:
        for p in [0.0, 0.25, 0.5, 0.75, 1.0]:
            for y in [True, False]:
                result = brier_score([p], [y])
                assert 0.0 <= result <= 1.0


# ── Log loss ─────────────────────────────────────────────────────────────────

class TestLogLoss:
    def test_perfect_predictor_near_zero(self) -> None:
        result = log_loss([1.0, 0.0], [True, False])
        assert result < 1e-6  # clipping at eps keeps it from being exactly 0

    def test_uniform_half_is_log_two(self) -> None:
        result = log_loss([0.5, 0.5], [True, False])
        assert abs(result - math.log(2)) < 1e-10

    def test_empty_input_returns_zero(self) -> None:
        assert log_loss([], []) == 0.0

    def test_numerical_stability_at_boundary(self) -> None:
        # Should not raise and should return finite value
        result = log_loss([0.0, 1.0], [True, True])  # worst case — clips to eps
        assert math.isfinite(result)

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            log_loss([0.5], [True, False])


# ── Reliability curve ────────────────────────────────────────────────────────

class TestReliabilityCurve:
    def test_perfectly_calibrated_has_zero_gap(self) -> None:
        # Build a perfectly calibrated input: each bin has matching accuracy
        # Use 0.1 for first half and 0.9 for second half.
        probs = [0.1] * 10 + [0.9] * 10
        # 1 correct per 10 low-conf, 9 correct per 10 high-conf
        labels = [False] * 9 + [True] + [True] * 9 + [False]
        curve = reliability_curve(probs, labels, n_bins=10)
        low_bins = [b for b in curve if b["count"] > 0 and b["start"] < 0.2]
        high_bins = [b for b in curve if b["count"] > 0 and b["start"] >= 0.8]
        # Gaps should be small (not required to be 0 exactly due to bin edges)
        for b in low_bins + high_bins:
            assert b["gap"] < 0.15  # some tolerance for binning

    def test_returns_n_bins_dicts(self) -> None:
        curve = reliability_curve([0.3, 0.7], [False, True], n_bins=5)
        assert len(curve) == 5

    def test_empty_bins_have_zero_count(self) -> None:
        # all probs in [0, 0.5) means bins 5-9 are empty
        curve = reliability_curve([0.2, 0.3, 0.4], [True, True, False], n_bins=10)
        empty_bins = [b for b in curve if b["count"] == 0]
        for b in empty_bins:
            assert b["gap"] == 0.0


# ── Expected Calibration Error ────────────────────────────────────────────────

class TestECE:
    def test_perfect_predictor_ece_near_zero(self) -> None:
        # Construct input where each bin's mean_confidence ≈ empirical_accuracy.
        # Use confidence=0.5 on a balanced set: accuracy = 0.5 → gap ≈ 0.
        probs = [0.5] * 20
        labels = [True] * 10 + [False] * 10
        ece = expected_calibration_error(probs, labels, n_bins=10)
        assert ece < 0.01  # all weight in one bin with gap = |0.5 - 0.5| = 0

    def test_worst_case_ece_is_one(self) -> None:
        # Fully reversed: confident and wrong
        probs = [0.99] * 10
        labels = [False] * 10
        ece = expected_calibration_error(probs, labels, n_bins=10)
        assert ece > 0.90

    def test_ece_between_zero_and_one(self) -> None:
        probs = [0.6, 0.4, 0.8, 0.2]
        labels = [True, False, True, False]
        ece = expected_calibration_error(probs, labels)
        assert 0.0 <= ece <= 1.0


# ── Temperature scaling ───────────────────────────────────────────────────────

class TestTemperatureScaling:
    def test_temperature_one_is_identity(self) -> None:
        probs = [0.2, 0.5, 0.8]
        scaled = apply_temperature_scaling(probs, temperature=1.0)
        for original, result in zip(probs, scaled):
            assert abs(result - original) < 1e-10

    def test_high_temperature_shrinks_toward_half(self) -> None:
        # At T→∞, logit/T → 0, sigmoid(0) = 0.5
        probs = [0.1, 0.9]
        scaled = apply_temperature_scaling(probs, temperature=1000.0)
        for s in scaled:
            assert abs(s - 0.5) < 0.01

    def test_low_temperature_sharpens(self) -> None:
        # At T→0, overconfident probabilities should move away from 0.5
        p = 0.6
        original = apply_temperature_scaling([p], temperature=1.0)[0]
        sharpened = apply_temperature_scaling([p], temperature=0.5)[0]
        assert sharpened > original  # p > 0.5, so sharpening moves further toward 1

    def test_output_in_unit_interval(self) -> None:
        probs = [0.0, 0.25, 0.5, 0.75, 1.0]
        for t in [0.5, 1.0, 2.0]:
            scaled = apply_temperature_scaling(probs, t)
            for s in scaled:
                assert 0.0 <= s <= 1.0


# ── TrustCalibrator ───────────────────────────────────────────────────────────

class TestTrustCalibrator:
    def _shifted_scores(self) -> tuple[list[float], list[bool]]:
        """Scores shifted high (overconfident); calibrator should find T > 1."""
        probs = [0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50]
        labels = [True, True, True, True, True, False, False, False, False, False]
        return probs, labels

    def test_fit_returns_temperature(self) -> None:
        probs, labels = self._shifted_scores()
        cal = TrustCalibrator()
        t = cal.fit(probs, labels)
        assert isinstance(t, float)
        assert 0.25 <= t <= 8.0

    def test_overconfident_scores_get_t_above_one(self) -> None:
        # Overconfident scores (all high) on balanced labels → T > 1 to shrink
        _probs = [0.99] * 5 + [0.01] * 5  # noqa: F841
        # Labels match perfectly — calibrator might leave T near 1 or increase it
        # but for truly overconfident scores against balanced labels:
        probs2 = [0.95] * 10
        labels2 = [True] * 6 + [False] * 4  # 60% correct at 95% confidence
        cal = TrustCalibrator()
        t = cal.fit(probs2, labels2)
        assert t > 1.0  # must reduce overconfidence

    def test_fit_improves_log_loss(self) -> None:
        probs, labels = self._shifted_scores()
        cal = TrustCalibrator()
        cal.fit(probs, labels)
        raw_nll = log_loss(probs, labels)
        calibrated_nll = cal.evaluate(probs, labels).nll
        assert calibrated_nll <= raw_nll + 1e-9  # calibrated should not be worse

    def test_evaluate_returns_calibration_metrics(self) -> None:
        probs, labels = self._shifted_scores()
        cal = TrustCalibrator()
        cal.fit(probs, labels)
        metrics = cal.evaluate(probs, labels)
        assert hasattr(metrics, "brier")
        assert hasattr(metrics, "nll")
        assert hasattr(metrics, "ece")
        assert 0.0 <= metrics.brier <= 1.0
        assert metrics.nll >= 0.0
        assert 0.0 <= metrics.ece <= 1.0

    def test_empty_input_uses_default_temperature(self) -> None:
        cal = TrustCalibrator()
        t = cal.fit([], [])
        assert t == 1.0

    def test_boundary_warning_emitted_at_t_max(self) -> None:
        # Force temperature to hit the ceiling by using severely bimodal scores
        # and a t_max of 0.5 so any reasonable t lands at the boundary
        probs = [0.99] * 20
        labels = [False] * 20  # all wrong despite high confidence
        cal = TrustCalibrator()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cal.fit(probs, labels, t_min=0.25, t_max=0.5, t_steps=10)
            boundary_warnings = [x for x in w if "ceiling" in str(x.message)]
            assert len(boundary_warnings) >= 1, "Expected a boundary warning when t_max is hit"
