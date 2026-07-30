# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for finite-sample selective risk control (SGR / CRC / LTT).

References under test:
- Geifman & El-Yaniv (2017), "Selective Classification for Deep Neural
  Networks" — selection with guaranteed risk via binomial tail inversion.
- Angelopoulos, Bates, Fisch, Lei, Schuster (2024), "Conformal Risk
  Control" — (n/(n+1))*Rhat_n + B/(n+1) <= alpha.
- Angelopoulos et al. (2021), "Learn then Test" — threshold calibration as
  fixed-sequence multiple hypothesis testing.
"""
from __future__ import annotations

import math

import pytest

from remora.selective.risk_control import (
    clopper_pearson_upper,
    crc_threshold,
    sgr_threshold,
)


# ── Clopper-Pearson upper bound ────────────────────────────────────────────

def test_cp_upper_zero_errors_closed_form() -> None:
    # With k=0 the CP upper limit has the closed form 1 - delta**(1/n).
    n, delta = 18, 0.05
    expected = 1.0 - delta ** (1.0 / n)
    assert clopper_pearson_upper(0, n, delta) == pytest.approx(expected, abs=1e-6)


def test_cp_upper_monotone_in_errors_and_valid_range() -> None:
    prev = 0.0
    for k in range(0, 11):
        u = clopper_pearson_upper(k, 10, 0.05)
        assert 0.0 <= u <= 1.0
        assert u >= prev
        prev = u
    assert clopper_pearson_upper(10, 10, 0.05) == 1.0


def test_cp_upper_covers_empirical_rate() -> None:
    # The upper bound must sit at or above the point estimate.
    assert clopper_pearson_upper(3, 20, 0.1) >= 3 / 20


def test_cp_upper_degenerate_n_zero_fails_closed() -> None:
    assert clopper_pearson_upper(0, 0, 0.05) == 1.0


# ── SGR / LTT fixed-sequence certification ─────────────────────────────────

def _separable(n_good: int = 50, n_bad: int = 50):
    """Scores perfectly separate correct (high score) from wrong (low)."""
    scores = [1.0 - i * 0.001 for i in range(n_good)] + [
        0.4 - i * 0.001 for i in range(n_bad)
    ]
    losses = [0] * n_good + [1] * n_bad
    return scores, losses


def test_sgr_certifies_clean_prefix_on_separable_data() -> None:
    scores, losses = _separable()
    res = sgr_threshold(scores, losses, target_risk=0.10, delta=0.10)
    assert res.certified
    # Everything accepted must come from the loss-free prefix.
    accepted = [ls for s, ls in zip(scores, losses) if s >= res.threshold]
    assert sum(accepted) == 0
    assert res.risk_bound <= 0.10
    assert 0 < res.coverage <= 0.5


def test_sgr_refuses_unreachable_target() -> None:
    # 50% base error and a tiny target with high confidence: nothing certifiable.
    scores, losses = _separable(5, 5)
    res = sgr_threshold(scores, losses, target_risk=0.01, delta=0.01)
    assert not res.certified
    assert res.coverage == 0.0


def test_sgr_bound_holds_at_reported_threshold() -> None:
    scores, losses = _separable(30, 70)
    res = sgr_threshold(scores, losses, target_risk=0.15, delta=0.05)
    if res.certified:
        acc = [ls for s, ls in zip(scores, losses) if s >= res.threshold]
        k_err, n_acc = sum(acc), len(acc)
        assert clopper_pearson_upper(k_err, n_acc, res.delta_spent) <= 0.15 + 1e-12


def test_sgr_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        sgr_threshold([0.1], [0, 1], target_risk=0.1, delta=0.1)
    with pytest.raises(ValueError):
        sgr_threshold([], [], target_risk=0.1, delta=0.1)


# ── Conformal Risk Control ─────────────────────────────────────────────────

def test_crc_criterion_hand_case() -> None:
    # n=9 calibration points; accepting all gives 1 error -> Rhat = 1/9.
    # Criterion: (n/(n+1))*Rhat + B/(n+1) = (9/10)*(1/9) + 1/10 = 0.2 <= alpha.
    scores = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]
    losses = [0, 0, 0, 0, 0, 0, 0, 0, 1]
    res = crc_threshold(scores, losses, alpha=0.20)
    assert res.certified
    assert res.coverage == 1.0
    assert res.risk_bound == pytest.approx(0.2, abs=1e-9)


def test_crc_small_n_floor_fails_closed() -> None:
    # With n=3, B/(n+1) = 0.25 alone exceeds alpha=0.2: nothing certifiable.
    res = crc_threshold([0.9, 0.5, 0.1], [0, 0, 0], alpha=0.20)
    assert not res.certified
    assert res.coverage == 0.0


def test_crc_coverage_monotone_in_alpha() -> None:
    scores, losses = _separable(40, 60)
    cov = [
        crc_threshold(scores, losses, alpha=a).coverage
        for a in (0.05, 0.15, 0.30, 0.60)
    ]
    assert cov == sorted(cov)


def test_crc_unconditional_loss_semantics() -> None:
    # CRC controls accepted-and-wrong over ALL items (unconditional). It MAY
    # therefore admit wrong items as long as the loss budget holds — assert
    # the criterion at the returned threshold, not zero errors.
    scores, losses = _separable(10, 10)
    res = crc_threshold(scores, losses, alpha=0.10)
    assert res.certified
    accepted = [ls for s, ls in zip(scores, losses) if s >= res.threshold]
    n = len(scores)
    criterion = (n / (n + 1)) * (sum(accepted) / n) + 1.0 / (n + 1)
    assert criterion <= 0.10 + 1e-12
    assert res.coverage >= 0.5  # the loss-free half is certifiable at this alpha


def test_no_nan_and_threshold_from_calibration_scores() -> None:
    scores, losses = _separable(20, 20)
    for fn, kw in ((sgr_threshold, {"target_risk": 0.2, "delta": 0.1}),
                   (crc_threshold, {"alpha": 0.2})):
        res = fn(scores, losses, **kw)
        assert not math.isnan(res.risk_bound)
        if res.certified:
            assert res.threshold in scores


# ---------------------------------------------------------------------------
# External review 2026-07-29 F-07 (issue #85): SGR is not "largest set",
# and the rejected path must report the BEST evaluated bound.
# ---------------------------------------------------------------------------


def test_sgr_binary_search_can_miss_larger_passing_set_documented():
    """Erlend's counterexample: four correct points, target 0.6, delta 0.1.

    The full-coverage cut (CP upper bound ~0.5727 <= 0.6) would pass, but the
    binary-search walk never evaluates it and returns certified=False. This
    pins the DOCUMENTED behavior: the procedure's guarantee holds over the
    evaluated candidates only - certified=False means "the pre-registered SGR
    procedure returned zero certified coverage", not "no coverage is
    certifiable".
    """
    from remora.selective.risk_control import (
        clopper_pearson_upper,
        sgr_threshold,
    )

    scores = [0.9, 0.8, 0.7, 0.6]
    losses = [0, 0, 0, 0]
    result = sgr_threshold(scores, losses, target_risk=0.6, delta=0.1)

    # The globally-largest set WOULD pass under the same per-test level...
    full_bound = clopper_pearson_upper(0, 4, result.delta_spent)
    assert full_bound <= 0.6
    # ...yet the walk rejects (documented non-optimality, guarantee intact).
    assert result.certified is False
    assert result.coverage == 0.0


def test_sgr_rejected_path_reports_best_evaluated_bound():
    """risk_bound on certified=False must be the BEST (smallest) evaluated
    bound, not the last one visited - the last-visited bound made SAP v3
    report 0.99 when the best evaluated was ~0.0844 (F-07)."""
    from remora.selective.risk_control import (
        clopper_pearson_upper,
        sgr_threshold,
    )

    scores = [0.9, 0.8, 0.7, 0.6]
    losses = [0, 0, 0, 0]
    result = sgr_threshold(scores, losses, target_risk=0.6, delta=0.1)

    # Walk evaluates the n=2 cut first (bound ~0.8175), then n=1 (~0.9667).
    best_evaluated = clopper_pearson_upper(0, 2, result.delta_spent)
    last_evaluated = clopper_pearson_upper(0, 1, result.delta_spent)
    assert result.risk_bound == pytest.approx(best_evaluated, abs=1e-9)
    assert result.risk_bound < last_evaluated
