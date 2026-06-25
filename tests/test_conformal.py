# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for split-conformal calibration primitives."""
from __future__ import annotations

import random

import pytest

from remora.selective.conformal import (
    conformal_threshold,
    split_calibration,
    coverage_at_threshold,
)


def test_split_calibration_partitions_with_expected_sizes():
    rng = random.Random(0)
    scores = [rng.random() for _ in range(100)]
    labels = [rng.random() < 0.7 for _ in scores]
    cal, test = split_calibration(scores, labels, cal_fraction=0.6, seed=0)
    assert len(cal[0]) == 60
    assert len(test[0]) == 40
    # Disjointness: combined sorted values equal original sorted values.
    assert len(cal[0]) + len(test[0]) == len(scores)
    assert sorted(cal[0] + test[0]) == sorted(scores)


def test_conformal_threshold_satisfies_target_risk_on_calibration():
    scores = [i / 100 for i in range(100)]
    labels = [s > 0.30 for s in scores]
    tau = conformal_threshold(scores, labels, target_risk=0.10)
    # Empirical risk at the returned threshold must be <= target on calibration.
    accepted = [(s, y) for s, y in zip(scores, labels) if s >= tau]
    if accepted:
        wrong = sum(1 for _, y in accepted if not y)
        assert wrong / len(accepted) <= 0.10 + 1e-9


def test_conformal_threshold_returns_above_one_when_unattainable():
    # Labels are uncorrelated with score; no threshold can hit 0% risk.
    scores = [i / 100 for i in range(100)]
    labels = [(i % 2 == 0) for i in range(100)]
    tau = conformal_threshold(scores, labels, target_risk=0.0)
    assert tau > 1.0


def test_coverage_at_threshold_matches_naive_count():
    scores = [0.1, 0.4, 0.7, 0.9]
    _labels = [False, True, True, True]  # noqa: F841
    cov = coverage_at_threshold(scores, 0.5)
    assert cov == pytest.approx(0.5)


def test_conformal_threshold_handles_tied_scores_safely():
    # 10 items at score=0.5, 4 wrong; risk at full acceptance is 0.4.
    # target=0.10 should reject the entire tied block (not pick threshold=0.5).
    scores = [0.5] * 10 + [0.9] * 5  # 5 high-score items, all correct
    labels = [True, True, True, True, True, True, False, False, False, False,
              True, True, True, True, True]
    from remora.selective.conformal import conformal_threshold
    tau = conformal_threshold(scores, labels, target_risk=0.10)
    # Accept only items with s >= tau; realized risk must be <= 0.10.
    accepted = [(s, y) for s, y in zip(scores, labels) if s >= tau]
    if accepted:
        wrong = sum(1 for _, y in accepted if not y)
        assert wrong / len(accepted) <= 0.10 + 1e-9, (
            f"Realized risk {wrong/len(accepted)} exceeds target 0.10; tau={tau}"
        )


def test_conformal_threshold_does_not_guarantee_shifted_test_risk():
    calibration_scores = [0.95, 0.94, 0.93, 0.30, 0.20, 0.10]
    calibration_labels = [True, True, True, False, False, False]
    tau = conformal_threshold(calibration_scores, calibration_labels, target_risk=0.0)

    shifted_scores = [0.95, 0.94, 0.93, 0.30, 0.20, 0.10]
    shifted_labels = [False, False, False, True, True, True]
    accepted = [(score, label) for score, label in zip(shifted_scores, shifted_labels) if score >= tau]
    wrong = sum(1 for _, label in accepted if not label)

    assert tau <= 0.95
    assert accepted
    assert wrong / len(accepted) == 1.0
