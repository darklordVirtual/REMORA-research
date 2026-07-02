"""Tests for the anytime-valid Bernoulli confidence sequence.

Covers correctness (closed-form agreement, monotonicity), the time-uniform
validity guarantee (seeded simulation of the *whole monitoring trajectory*,
which is exactly the property Wilson intervals lack), and the honest-cost
property (wider than Wilson at fixed N — asserted, not hidden).
"""
from __future__ import annotations

import math
import random

import pytest

from remora.selective.confidence_sequence import (
    bernoulli_upper_confidence_sequence,
    closed_form_upper_k0,
    far_monitoring_report,
    log_mixture_martingale,
)


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------

def test_no_data_returns_trivial_bound() -> None:
    assert bernoulli_upper_confidence_sequence(0, 0) == 1.0


@pytest.mark.parametrize("n", [1, 10, 168, 700, 5000])
def test_k0_matches_closed_form(n: int) -> None:
    """Bisection must agree with the analytic k=0 solution."""
    numeric = bernoulli_upper_confidence_sequence(0, n, alpha=0.05)
    analytic = closed_form_upper_k0(n, alpha=0.05)
    assert numeric == pytest.approx(analytic, abs=1e-8)


def test_bound_shrinks_with_more_clean_data() -> None:
    bounds = [bernoulli_upper_confidence_sequence(0, n) for n in (10, 50, 168, 700)]
    assert bounds == sorted(bounds, reverse=True)
    assert bounds[-1] < 0.02  # 0/700 → tight bound


def test_bound_grows_with_events() -> None:
    b0 = bernoulli_upper_confidence_sequence(0, 200)
    b3 = bernoulli_upper_confidence_sequence(3, 200)
    b10 = bernoulli_upper_confidence_sequence(10, 200)
    assert b0 < b3 < b10


def test_bound_contains_empirical_rate() -> None:
    for k, n in [(0, 50), (5, 100), (50, 100), (99, 100)]:
        upper = bernoulli_upper_confidence_sequence(k, n)
        assert upper >= k / n


def test_smaller_alpha_gives_wider_bound() -> None:
    tight = bernoulli_upper_confidence_sequence(2, 300, alpha=0.10)
    wide = bernoulli_upper_confidence_sequence(2, 300, alpha=0.01)
    assert wide > tight


def test_martingale_is_one_at_no_data() -> None:
    assert log_mixture_martingale(0, 0, 0.3) == pytest.approx(0.0)


def test_input_validation() -> None:
    with pytest.raises(ValueError):
        bernoulli_upper_confidence_sequence(-1, 10)
    with pytest.raises(ValueError):
        bernoulli_upper_confidence_sequence(11, 10)
    with pytest.raises(ValueError):
        bernoulli_upper_confidence_sequence(0, 10, alpha=0.0)
    with pytest.raises(ValueError):
        log_mixture_martingale(0, 10, 0.0)
    with pytest.raises(ValueError):
        log_mixture_martingale(0, 10, 0.5, prior_a=0.0)


# ---------------------------------------------------------------------------
# The property that matters: time-uniform validity under monitoring
# ---------------------------------------------------------------------------

def test_time_uniform_coverage_under_continuous_monitoring() -> None:
    """The true rate must stay below the bound at EVERY step of a monitored
    trajectory, with failure probability ≤ alpha over the whole horizon.

    This is the guarantee fixed-N intervals do not provide. Seeded and
    deterministic: 400 trajectories of 300 Bernoulli(0.05) draws, alpha=0.05.
    Ville's inequality guarantees expected miscoverage ≤ 5%; we assert the
    seeded empirical rate stays under 6% (slack for simulation noise).
    """
    rng = random.Random(42)
    p_true, alpha, horizon, trajectories = 0.05, 0.05, 300, 400
    violations = 0
    for _ in range(trajectories):
        k = 0
        violated = False
        for n in range(1, horizon + 1):
            if rng.random() < p_true:
                k += 1
            if bernoulli_upper_confidence_sequence(k, n, alpha) < p_true:
                violated = True
                break
        violations += violated
    assert violations / trajectories <= 0.06


def test_wilson_style_fixed_n_interval_fails_under_monitoring() -> None:
    """Contrast case documenting WHY the sequence is needed: the same
    monitoring loop with a per-step Wilson upper bound violates its nominal
    5% level by a wide margin, because each step's guarantee is only
    pointwise. This is the peeking problem REM-020 is exposed to today.
    """

    def wilson_upper(k: int, n: int, z: float = 1.6449) -> float:  # one-sided 95%
        if n == 0:
            return 1.0
        phat = k / n
        denom = 1 + z * z / n
        center = phat + z * z / (2 * n)
        margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
        return (center + margin) / denom

    rng = random.Random(42)
    p_true, horizon, trajectories = 0.05, 300, 400
    violations = 0
    for _ in range(trajectories):
        k = 0
        violated = False
        for n in range(1, horizon + 1):
            if rng.random() < p_true:
                k += 1
            if wilson_upper(k, n) < p_true:
                violated = True
                break
        violations += violated
    # Pointwise-valid interval, monitored continuously → far above 5%.
    assert violations / trajectories > 0.15


def test_sequence_wider_than_wilson_at_fixed_n() -> None:
    """The honest cost: at any single fixed N the sequence is looser than
    Wilson. This must hold (and be reported), or the construction is wrong.
    """
    k, n, z = 0, 168, 1.6449
    phat = k / n
    denom = 1 + z * z / n
    center = phat + z * z / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    wilson = (center + margin) / denom
    cs = bernoulli_upper_confidence_sequence(k, n, alpha=0.05)
    assert cs > wilson


# ---------------------------------------------------------------------------
# Gate report
# ---------------------------------------------------------------------------

def test_far_monitoring_report_fields() -> None:
    report = far_monitoring_report(0, 168, alpha=0.05, threshold=0.05)
    assert report["k_events"] == 0
    assert report["n_trials"] == 168
    assert report["empirical_rate"] == 0.0
    assert 0.0 < report["time_uniform_upper_bound"] < 0.06
    assert report["upper_bound_below_threshold"] is True
    assert "anytime-valid" in report["validity"].lower() or "Time-uniform" in report["validity"]


def test_far_monitoring_report_threshold_breach() -> None:
    report = far_monitoring_report(5, 20, alpha=0.05, threshold=0.05)
    assert report["upper_bound_below_threshold"] is False
