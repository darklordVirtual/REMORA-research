"""Tests for TrustScoreDriftDetector and DistributionDriftWarning."""
from __future__ import annotations

import warnings

import pytest

from remora.selective.drift_detector import (
    DistributionDriftWarning,
    TrustScoreDriftDetector,
)


def _make_detector(
    cal_scores: list[float] | None = None,
    window_size: int = 10,
    alpha: float = 0.05,
) -> TrustScoreDriftDetector:
    if cal_scores is None:
        cal_scores = [0.85] * 50 + [0.90] * 50
    return TrustScoreDriftDetector(cal_scores, window_size=window_size, alpha=alpha)


class TestDistributionDriftWarning:
    def test_is_user_warning_subclass(self) -> None:
        assert issubclass(DistributionDriftWarning, UserWarning)

    def test_can_be_raised(self) -> None:
        with pytest.raises(DistributionDriftWarning):
            raise DistributionDriftWarning("test")


class TestTrustScoreDriftDetectorInit:
    def test_raises_on_empty_cal(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            TrustScoreDriftDetector([])

    def test_valid_construction(self) -> None:
        det = TrustScoreDriftDetector([0.8, 0.9, 0.7], window_size=5)
        assert det._window_size == 5

    def test_buffer_starts_empty(self) -> None:
        det = _make_detector()
        assert len(det._buffer) == 0


class TestUpdateBehavior:
    def test_no_drift_below_window(self) -> None:
        det = _make_detector(window_size=10)
        for _ in range(9):
            result = det.update(0.88)
        assert result is False  # window not yet full

    def test_returns_false_on_identical_distribution(self) -> None:
        # Calibration and runtime are identical → KS p-value = 1.0 → no drift
        cal = [0.85] * 200
        det = TrustScoreDriftDetector(cal, window_size=10, alpha=0.05)
        for _ in range(10):
            result = det.update(0.85)
        assert result is False

    def test_returns_true_on_shifted_distribution(self) -> None:
        cal = [0.85] * 100
        det = TrustScoreDriftDetector(cal, window_size=10, alpha=0.05)
        results = []
        with pytest.warns(DistributionDriftWarning, match="distribution drift"):
            for _ in range(10):
                results.append(det.update(0.05))  # completely different distribution
        assert any(results)

    def test_warns_on_drift(self) -> None:
        cal = [0.85] * 100
        det = TrustScoreDriftDetector(cal, window_size=10, alpha=0.05)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            for _ in range(10):
                det.update(0.05)
        drift_warnings = [x for x in w if issubclass(x.category, DistributionDriftWarning)]
        assert len(drift_warnings) >= 1

    def test_buffer_rolling_eviction(self) -> None:
        det = _make_detector(window_size=5)
        with pytest.warns(DistributionDriftWarning, match="distribution drift"):
            for i in range(10):
                det.update(float(i) * 0.1)
        assert len(det._buffer) == 5


class TestTestDrift:
    def test_returns_false_before_window_full(self) -> None:
        det = _make_detector(window_size=50)
        det.update(0.8)
        detected, p = det.test_drift()
        assert detected is False
        assert p == 1.0

    def test_p_value_in_zero_one(self) -> None:
        cal = [0.85] * 100
        det = TrustScoreDriftDetector(cal, window_size=10, alpha=0.05)
        for _ in range(10):
            det.update(0.85)
        _, p = det.test_drift()
        assert 0.0 <= p <= 1.0

    def test_high_pvalue_when_no_drift(self) -> None:
        cal = [0.85] * 200
        det = TrustScoreDriftDetector(cal, window_size=10, alpha=0.05)
        for _ in range(10):
            det.update(0.85)
        detected, p = det.test_drift()
        assert p > 0.05
        assert detected is False
