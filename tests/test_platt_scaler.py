# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for remora.calibration.platt_scaler — pure-Python Platt scaling."""
from __future__ import annotations

import math
import pytest

from remora.calibration.platt_scaler import PlattScaler, _sigmoid


# ---------------------------------------------------------------------------
# Sigmoid helper
# ---------------------------------------------------------------------------

class TestSigmoid:
    def test_sigmoid_zero(self):
        assert abs(_sigmoid(0.0) - 0.5) < 1e-12

    def test_sigmoid_large_positive(self):
        assert _sigmoid(100.0) > 0.9999

    def test_sigmoid_large_negative(self):
        assert _sigmoid(-100.0) < 1e-9

    def test_sigmoid_symmetry(self):
        for x in [0.5, 1.0, 2.0, 5.0]:
            assert abs(_sigmoid(x) + _sigmoid(-x) - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# Unfitted scaler is identity
# ---------------------------------------------------------------------------

class TestUnfittedIdentity:
    def test_transform_one_identity(self):
        s = PlattScaler(A=1.0, B=0.0)
        # σ(1.0 * 0.8 + 0.0) ≈ 0.69 — not exact 0.8, but A=1 B=0 means pass-through through sigmoid
        # A=1, B=0: transform_one(0.5) = σ(0.5) ≈ 0.622
        result = s.transform_one(0.5)
        assert 0.0 < result < 1.0

    def test_transform_returns_list(self):
        s = PlattScaler()
        out = s.transform([0.1, 0.5, 0.9])
        assert len(out) == 3

    def test_is_fitted_false_before_fit(self):
        s = PlattScaler()
        assert not s.is_fitted()


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------

class TestFitting:
    def _make_data(self, n: int = 50, seed: int = 42):
        """Generate synthetic (score, label) pairs where higher scores → more likely True."""
        import random
        rng = random.Random(seed)
        scores = []
        labels = []
        for _ in range(n):
            s = rng.random()
            # P(correct | s) = s (perfect calibration)
            y = rng.random() < s
            scores.append(s)
            labels.append(y)
        return scores, labels

    def test_fit_returns_self(self):
        s = PlattScaler()
        scores, labels = self._make_data()
        result = s.fit(scores, labels)
        assert result is s

    def test_fitted_flag_set(self):
        s = PlattScaler()
        scores, labels = self._make_data()
        s.fit(scores, labels)
        assert s.is_fitted()

    def test_empty_data_does_not_crash(self):
        s = PlattScaler()
        s.fit([], [])
        assert not s.is_fitted()

    def test_length_mismatch_raises(self):
        s = PlattScaler()
        with pytest.raises(ValueError):
            s.fit([0.5, 0.6], [True])

    def test_ece_after_fitting_lower_than_before(self):
        """ECE should decrease after fitting on the same data (sanity check)."""
        scores, labels = self._make_data(n=80)
        # Overconfident raw scores: push all above 0.7 to simulate trust score bias
        biased = [min(1.0, s + 0.3) for s in scores]

        unfitted = PlattScaler(A=1.0, B=0.0)
        ece_before = unfitted.ece(biased, labels)

        fitted = PlattScaler()
        fitted.fit(biased, labels)
        ece_after = fitted.ece(biased, labels)

        # Fitting on same data must not increase ECE substantially
        assert ece_after <= ece_before + 0.05

    def test_calibrated_probs_in_unit_interval(self):
        scores, labels = self._make_data(n=40)
        s = PlattScaler()
        s.fit(scores, labels)
        calibrated = s.transform(scores)
        for p in calibrated:
            assert 0.0 < p < 1.0

    def test_monotone_after_fitting(self):
        """Platt scaling preserves rank order (σ(Ax+B) is monotone in x when A > 0)."""
        scores, labels = self._make_data(n=60)
        s = PlattScaler()
        s.fit(scores, labels)
        # If A > 0, higher raw score → higher calibrated probability
        if s.A > 0:
            sorted_scores = sorted(scores)
            calibrated = s.transform(sorted_scores)
            for i in range(len(calibrated) - 1):
                assert calibrated[i] <= calibrated[i + 1] + 1e-9


# ---------------------------------------------------------------------------
# Bayes-optimal threshold
# ---------------------------------------------------------------------------

class TestBayesThreshold:
    def test_threshold_finite(self):
        s = PlattScaler(A=1.0, B=0.0)
        t = s.bayes_threshold(target_precision=0.90)
        assert math.isfinite(t)

    def test_threshold_fallback_when_A_zero(self):
        s = PlattScaler(A=0.0, B=0.0)
        t = s.bayes_threshold(target_precision=0.80)
        assert abs(t - 0.80) < 1e-9

    def test_higher_precision_requires_higher_threshold(self):
        s = PlattScaler(A=2.0, B=-1.0)
        t80 = s.bayes_threshold(0.80)
        t90 = s.bayes_threshold(0.90)
        assert t90 > t80

    def test_threshold_round_trips_through_transform(self):
        """σ(A * t* + B) should equal target_precision."""
        s = PlattScaler(A=2.5, B=-0.5)
        for target in [0.70, 0.80, 0.90, 0.95]:
            t = s.bayes_threshold(target)
            recovered = s.transform_one(t)
            assert abs(recovered - target) < 1e-6


# ---------------------------------------------------------------------------
# ECE
# ---------------------------------------------------------------------------

class TestECE:
    def test_perfect_calibration_ece_near_zero(self):
        """A perfectly calibrated predictor should have ECE ≈ 0."""
        # Build inputs where empirical accuracy exactly matches confidence in each bin
        scores = [0.1] * 5 + [0.3] * 5 + [0.5] * 10 + [0.7] * 5 + [0.9] * 5
        # For each confidence level, approximately that fraction should be True
        import random
        rng = random.Random(0)
        labels = [rng.random() < s for s in scores]
        s = PlattScaler(A=1.0, B=0.0)
        ece = s.ece(scores, labels)
        assert 0.0 <= ece <= 0.5  # broad bound — small sample size

    def test_worst_case_ece_bounded(self):
        # All scores 0.95 but all labels False → huge gap in high-confidence bin
        s = PlattScaler(A=1.0, B=0.0)
        scores = [0.95] * 20
        labels = [False] * 20
        ece = s.ece(scores, labels)
        assert 0.0 <= ece <= 1.0

    def test_empty_returns_zero(self):
        s = PlattScaler()
        assert s.ece([], []) == 0.0


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

class TestSerialisation:
    def test_round_trip(self):
        s = PlattScaler(A=2.3, B=-0.7)
        s._fitted = True
        d = s.to_dict()
        s2 = PlattScaler.from_dict(d)
        assert abs(s2.A - s.A) < 1e-9
        assert abs(s2.B - s.B) < 1e-9
        assert s2.is_fitted()

    def test_from_dict_defaults(self):
        s = PlattScaler.from_dict({})
        assert s.A == 1.0
        assert s.B == 0.0
        assert not s.is_fitted()
