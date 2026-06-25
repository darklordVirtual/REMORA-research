# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for remora.selective.crc â€” Conformal Risk Control under Covariate Shift.

Covers:
  - weighted_conformal_threshold: edge cases, uniform weights, importance weighting,
    tied scores, risk bounds
  - CovariateShiftCRC: fit/route, phase weighting, CRCReport fields, finite-sample slack
  - phase_importance_weights: in-distribution vs off-distribution
  - crc_risk_bound: formula verification

Mathematical guarantee (Angelopoulos et al. 2022, Theorem 1):
  E[L(Î»Ì‚)] â‰¤ target_risk + 1 / (n_calibration + 1)
"""
from __future__ import annotations


import pytest

from remora.selective.crc import (
    CRCReport,
    CovariateShiftCRC,
    crc_risk_bound,
    phase_importance_weights,
    weighted_conformal_threshold,
)
from remora.selective.conformal import UNATTAINABLE_THRESHOLD


# ---------------------------------------------------------------------------
# weighted_conformal_threshold â€” edge cases
# ---------------------------------------------------------------------------


def test_empty_scores_returns_unattainable():
    assert weighted_conformal_threshold([], []) == UNATTAINABLE_THRESHOLD


def test_mismatched_lengths_raises():
    with pytest.raises(ValueError, match="equal length"):
        weighted_conformal_threshold([0.5], [True, False])


def test_invalid_target_risk_raises():
    with pytest.raises(ValueError, match="target_risk"):
        weighted_conformal_threshold([0.5], [True], target_risk=1.5)

    with pytest.raises(ValueError, match="target_risk"):
        weighted_conformal_threshold([0.5], [True], target_risk=-0.1)


def test_zero_weights_returns_unattainable():
    assert (
        weighted_conformal_threshold(
            [0.9, 0.8], [True, True], weights=[0.0, 0.0]
        )
        == UNATTAINABLE_THRESHOLD
    )


def test_wrong_weights_length_raises():
    with pytest.raises(ValueError, match="same length"):
        weighted_conformal_threshold([0.5, 0.8], [True, True], weights=[1.0])


# ---------------------------------------------------------------------------
# weighted_conformal_threshold â€” uniform weights (standard conformal baseline)
# ---------------------------------------------------------------------------


def test_uniform_weights_all_correct():
    """All correct predictions â†’ any threshold at or below min score is valid."""
    scores = [0.9, 0.8, 0.7, 0.6]
    labels = [True, True, True, True]
    threshold = weighted_conformal_threshold(scores, labels, target_risk=0.05)
    # No wrong predictions, so risk = 0 â‰¤ 0.05; threshold should be a valid score
    assert threshold != UNATTAINABLE_THRESHOLD
    assert threshold >= 0.0


def test_uniform_weights_all_wrong():
    """All wrong predictions â†’ risk â‰¥ 1.0 at every threshold â†’ unattainable."""
    scores = [0.9, 0.8, 0.7]
    labels = [False, False, False]
    threshold = weighted_conformal_threshold(scores, labels, target_risk=0.05)
    assert threshold == UNATTAINABLE_THRESHOLD


def test_uniform_weights_risk_control():
    """50% items wrong; target_risk=0.60 should find a threshold accepting some items."""
    scores = [0.9, 0.8, 0.7, 0.6]
    labels = [True, False, True, False]
    threshold = weighted_conformal_threshold(scores, labels, target_risk=0.60)
    assert threshold != UNATTAINABLE_THRESHOLD


def test_uniform_weights_tight_risk_unattainable():
    # Cumulative risk at each tier: 1/1=1.0, 2/2=1.0, 2/3>0.10, 2/4=0.5>0.10
    scores = [0.9, 0.8, 0.7, 0.6]
    labels = [False, False, True, True]
    threshold = weighted_conformal_threshold(scores, labels, target_risk=0.10)
    assert threshold == UNATTAINABLE_THRESHOLD


def test_uniform_risk_zero_target():
    """target_risk=0.0 requires zero errors; only achievable if all accepted are correct."""
    scores = [0.9, 0.8, 0.7]
    labels = [True, True, False]
    # If we include only score 0.9 (correct) or 0.8 (correct), risk=0
    # If we include 0.7 (wrong), risk=1/3 > 0
    threshold = weighted_conformal_threshold(scores, labels, target_risk=0.0)
    assert threshold != UNATTAINABLE_THRESHOLD
    # Should not include the wrong item (score=0.7)
    assert threshold > 0.7


# ---------------------------------------------------------------------------
# weighted_conformal_threshold â€” importance weighting
# ---------------------------------------------------------------------------


def test_importance_weights_down_weight_wrong():
    """Down-weighting wrong items makes higher risk appear lower â†’ looser threshold."""
    scores = [0.9, 0.8, 0.7]
    labels = [True, False, True]

    threshold_uniform = weighted_conformal_threshold(
        scores, labels, weights=None, target_risk=0.20
    )
    threshold_downweighted = weighted_conformal_threshold(
        scores, labels, weights=[1.0, 0.01, 1.0], target_risk=0.20
    )
    # Down-weighting the wrong item (0.8) allows a looser threshold
    assert threshold_downweighted <= threshold_uniform


def test_importance_weights_up_weight_wrong():
    """Up-weighting wrong items â†’ stricter threshold."""
    scores = [0.9, 0.8, 0.7]
    labels = [True, False, True]

    threshold_uniform = weighted_conformal_threshold(
        scores, labels, weights=None, target_risk=0.40
    )
    threshold_upweighted = weighted_conformal_threshold(
        scores, labels, weights=[1.0, 100.0, 1.0], target_risk=0.40
    )
    # Up-weighting the wrong item â†’ either unattainable or threshold â‰¥ uniform
    assert (
        threshold_upweighted >= threshold_uniform
        or threshold_upweighted == UNATTAINABLE_THRESHOLD
    )


def test_negative_weights_clamped_to_zero():
    """Negative weights are clamped to 0; treated like zero-weight items."""
    scores = [0.9, 0.5]
    labels = [True, True]
    # Negative weights should not error, just clamp
    threshold = weighted_conformal_threshold(scores, labels, weights=[-1.0, 1.0])
    assert threshold != UNATTAINABLE_THRESHOLD


# ---------------------------------------------------------------------------
# weighted_conformal_threshold â€” tied scores
# ---------------------------------------------------------------------------


def test_tied_scores_all_correct():
    """Tied scores, all correct â†’ threshold should equal the tied score."""
    scores = [0.8, 0.8, 0.8]
    labels = [True, True, True]
    threshold = weighted_conformal_threshold(scores, labels, target_risk=0.05)
    assert threshold == pytest.approx(0.8)


def test_tied_scores_mixed():
    """Tied scores with one wrong item: risk = 1/3 at that tier.
    If target_risk â‰¥ 1/3, the threshold should be set at 0.8.
    """
    scores = [0.8, 0.8, 0.8]
    labels = [True, True, False]
    threshold_permissive = weighted_conformal_threshold(
        scores, labels, target_risk=0.40
    )
    threshold_strict = weighted_conformal_threshold(
        scores, labels, target_risk=0.10
    )
    assert threshold_permissive == pytest.approx(0.8)
    assert threshold_strict == UNATTAINABLE_THRESHOLD


def test_tied_scores_committed_atomically():
    """All items at the same score are consumed before a threshold is committed."""
    # Score 0.9: 2 correct, 1 wrong â†’ risk = 1/3 at this tier
    # Score 0.5: 1 correct â†’ if we could split, we'd prefer 0.9-only
    # But all 0.9 items are in the same block, so risk = 1/3 for block
    scores = [0.9, 0.9, 0.9, 0.5]
    labels = [True, True, False, True]
    threshold = weighted_conformal_threshold(scores, labels, target_risk=0.30)
    # With risk=1/3â‰ˆ0.333 > 0.30 at the 0.9 block alone,
    # only the 0.5 block (1 correct, 0 wrong â†’ risk=0) satisfies the target
    # But risk is computed cumulatively, so when 0.5 is added: 2/4 correct... wait
    # Actually: sorted desc by score, accumulate. At block {0.9,0.9,0.9}: 2 correct,
    # 1 wrong â†’ weighted_risk = 1/3 > 0.30. At block {0.5}: accumulated = 4 items,
    # 3 correct, 1 wrong â†’ risk = 1/4 = 0.25 â‰¤ 0.30.
    # So threshold should be 0.5 (the lowest score that satisfies the risk)
    assert threshold == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# CovariateShiftCRC â€” fit and route
# ---------------------------------------------------------------------------


def _make_data(n: int, accuracy: float, seed: int = 42):
    """Generate synthetic (score, label) pairs with given accuracy."""
    import random
    rng = random.Random(seed)
    scores = [round(rng.uniform(0.3, 1.0), 3) for _ in range(n)]
    labels = [rng.random() < accuracy for _ in range(n)]
    # Sort so higher score â†’ more likely correct
    pairs = sorted(zip(scores, labels), key=lambda x: x[0], reverse=True)
    halfway = len(pairs) // 2
    for i in range(halfway):
        s, _ = pairs[i]
        pairs[i] = (s, True if rng.random() < accuracy else False)
    scores = [p[0] for p in pairs]
    labels = [p[1] for p in pairs]
    return scores, labels


def test_fit_returns_crcreport():
    scores, labels = _make_data(50, 0.85)
    crc = CovariateShiftCRC(target_risk=0.05, seed=0)
    report = crc.fit(scores, labels)
    assert isinstance(report, CRCReport)


def test_fit_report_fields_consistent():
    scores, labels = _make_data(100, 0.90)
    crc = CovariateShiftCRC(target_risk=0.10, cal_fraction=0.7, seed=1)
    report = crc.fit(scores, labels)

    assert report.target_risk == pytest.approx(0.10)
    assert report.n_calibration + report.n_test == 100
    assert report.n_calibration == pytest.approx(round(100 * 0.7), abs=1)
    assert 0.0 < report.total_weight <= report.n_calibration
    assert report.finite_sample_slack == pytest.approx(1.0 / (report.n_calibration + 1))
    assert report.guaranteed_risk_bound == pytest.approx(
        report.target_risk + report.finite_sample_slack
    )


def test_fit_report_holdout_coverage_in_unit_interval():
    scores, labels = _make_data(80, 0.80)
    crc = CovariateShiftCRC(target_risk=0.10, seed=2)
    report = crc.fit(scores, labels)
    assert 0.0 <= report.holdout_coverage <= 1.0


def test_fit_no_items_accepted():
    """If threshold is unattainable, coverage=0 and holdout_risk=None."""
    # All wrong predictions â†’ no threshold achieves 5% risk
    scores = [0.9, 0.8, 0.7, 0.6, 0.5]
    labels = [False] * 5
    crc = CovariateShiftCRC(target_risk=0.05, seed=0)
    report = crc.fit(scores, labels)
    assert report.threshold == UNATTAINABLE_THRESHOLD
    assert report.weighted_holdout_risk is None
    assert report.holdout_coverage == 0.0


def test_fit_empty_input():
    crc = CovariateShiftCRC(seed=0)
    report = crc.fit([], [])
    assert report.threshold == UNATTAINABLE_THRESHOLD
    assert report.n_calibration == 0
    assert report.n_test == 0
    assert report.weighted_holdout_risk is None
    assert report.guaranteed_risk_bound == crc.target_risk + 1.0


def test_route_accept_above_threshold():
    scores, labels = _make_data(100, 0.95)
    crc = CovariateShiftCRC(target_risk=0.10, seed=0)
    report = crc.fit(scores, labels)
    if report.threshold != UNATTAINABLE_THRESHOLD:
        assert crc.route(report.threshold + 0.01) is True
        assert crc.route(report.threshold) is True


def test_route_abstain_below_threshold():
    scores, labels = _make_data(100, 0.95)
    crc = CovariateShiftCRC(target_risk=0.10, seed=0)
    report = crc.fit(scores, labels)
    if report.threshold != UNATTAINABLE_THRESHOLD and report.threshold > 0.0:
        assert crc.route(report.threshold - 0.01) is False


def test_route_unfitted_raises():
    crc = CovariateShiftCRC()
    with pytest.raises(RuntimeError, match="fitted"):
        crc.route(0.5)


def test_threshold_property_unfitted_raises():
    crc = CovariateShiftCRC()
    with pytest.raises(RuntimeError, match="fitted"):
        _ = crc.threshold


def test_threshold_property_after_fit():
    scores, labels = _make_data(60, 0.85)
    crc = CovariateShiftCRC(seed=0)
    report = crc.fit(scores, labels)
    assert crc.threshold == report.threshold


# ---------------------------------------------------------------------------
# CovariateShiftCRC â€” phase importance weighting
# ---------------------------------------------------------------------------


def test_phase_weights_applied_correctly():
    # All 20 items tied at score=0.8: 10 ordered (correct), 10 critical (wrong).
    # target=ordered: correct w=1.0, wrong w=0.10
    #   weighted_risk = (10*0.10)/(10*1.0+10*0.10) = 1/11 ~ 0.091 <= 0.10 -> attainable
    # target=critical: wrong w=1.0, correct w=0.10
    #   weighted_risk = (10*1.0)/(10*0.10+10*1.0) = 10/11 ~ 0.91 > 0.10 -> unattainable
    phases = ["ordered"] * 10 + ["critical"] * 10
    scores = [0.8] * 20
    labels = [True] * 10 + [False] * 10

    crc_ordered = CovariateShiftCRC(
        target_risk=0.10, cal_fraction=1.0, off_distribution_weight=0.10, seed=0
    )
    report_ordered = crc_ordered.fit(scores, labels, phases=phases, target_phase="ordered")
    assert report_ordered.threshold != UNATTAINABLE_THRESHOLD

    crc_critical = CovariateShiftCRC(
        target_risk=0.10, cal_fraction=1.0, off_distribution_weight=0.10, seed=0
    )
    report_critical = crc_critical.fit(scores, labels, phases=phases, target_phase="critical")
    assert report_critical.threshold == UNATTAINABLE_THRESHOLD


def test_phase_weights_total_weight_matches():
    """total_weight should reflect calibration split with importance weights."""
    n = 50
    phases = ["ordered"] * 25 + ["critical"] * 25
    scores, labels = _make_data(n, 0.90, seed=7)
    crc = CovariateShiftCRC(
        target_risk=0.10, cal_fraction=0.6, off_distribution_weight=0.20, seed=0
    )
    report = crc.fit(scores, labels, phases=phases, target_phase="ordered")
    # total_weight = (n_cal_ordered * 1.0) + (n_cal_critical * 0.20)
    # We can't know the exact split but verify it's positive
    assert report.total_weight > 0.0


def test_no_phase_arg_uses_unit_weights():
    """Without phases/target_phase, behaviour matches uniform-weight CRC."""
    scores, labels = _make_data(60, 0.85, seed=3)
    crc_no_phase = CovariateShiftCRC(target_risk=0.10, seed=42)
    report_no_phase = crc_no_phase.fit(scores, labels)
    # total_weight = n_calibration (all weights=1)
    assert report_no_phase.total_weight == pytest.approx(report_no_phase.n_calibration)


def test_mismatched_phases_raises():
    scores, labels = _make_data(30, 0.85)
    crc = CovariateShiftCRC()
    with pytest.raises(ValueError, match="same length"):
        crc.fit(scores, labels, phases=["ordered"] * 10)


# ---------------------------------------------------------------------------
# CovariateShiftCRC â€” finite-sample slack (Theorem 1 guarantee)
# ---------------------------------------------------------------------------


def test_finite_sample_slack_decreases_with_n():
    """Larger calibration set â†’ smaller finite-sample slack."""
    scores_small, labels_small = _make_data(20, 0.90, seed=0)
    scores_large, labels_large = _make_data(200, 0.90, seed=1)

    crc_small = CovariateShiftCRC(target_risk=0.05, seed=0)
    crc_large = CovariateShiftCRC(target_risk=0.05, seed=0)

    report_small = crc_small.fit(scores_small, labels_small)
    report_large = crc_large.fit(scores_large, labels_large)

    assert report_small.finite_sample_slack > report_large.finite_sample_slack


def test_guaranteed_risk_bound_formula():
    """guaranteed_risk_bound must equal target_risk + 1/(n_cal+1)."""
    scores, labels = _make_data(100, 0.90, seed=5)
    for alpha in [0.05, 0.10, 0.20]:
        crc = CovariateShiftCRC(target_risk=alpha, seed=0)
        r = crc.fit(scores, labels)
        expected_slack = 1.0 / (r.n_calibration + 1)
        assert r.finite_sample_slack == pytest.approx(expected_slack, rel=1e-9)
        assert r.guaranteed_risk_bound == pytest.approx(alpha + expected_slack, rel=1e-9)


def test_guaranteed_risk_bound_is_conservative():
    """Formal bound must always be â‰¥ target_risk."""
    scores, labels = _make_data(50, 0.85, seed=9)
    crc = CovariateShiftCRC(target_risk=0.10, seed=0)
    report = crc.fit(scores, labels)
    assert report.guaranteed_risk_bound >= report.target_risk


# ---------------------------------------------------------------------------
# phase_importance_weights
# ---------------------------------------------------------------------------


def test_phase_weights_in_distribution():
    phases = ["ordered", "ordered", "critical"]
    weights = phase_importance_weights(phases, target_phase="ordered")
    assert weights == [1.0, 1.0, 0.10]


def test_phase_weights_all_off():
    phases = ["ordered", "ordered"]
    weights = phase_importance_weights(phases, target_phase="critical", off_weight=0.20)
    assert weights == [0.20, 0.20]


def test_phase_weights_all_in():
    phases = ["critical", "critical", "critical"]
    weights = phase_importance_weights(phases, target_phase="critical")
    assert all(w == 1.0 for w in weights)


def test_phase_weights_custom_off_weight():
    phases = ["ordered", "critical", "disordered"]
    weights = phase_importance_weights(phases, target_phase="critical", off_weight=0.05)
    assert weights[0] == pytest.approx(0.05)
    assert weights[1] == pytest.approx(1.0)
    assert weights[2] == pytest.approx(0.05)


def test_phase_weights_length():
    phases = ["a", "b", "c", "d", "e"]
    weights = phase_importance_weights(phases, target_phase="a")
    assert len(weights) == 5


# ---------------------------------------------------------------------------
# crc_risk_bound â€” formula verification
# ---------------------------------------------------------------------------


def test_crc_risk_bound_n_19():
    """n=19 â†’ slack = 1/20 = 0.05 (5 pp)."""
    bound = crc_risk_bound(19, target_risk=0.05)
    assert bound == pytest.approx(0.05 + 1 / 20, rel=1e-9)


def test_crc_risk_bound_n_99():
    """n=99 â†’ slack = 1/100 = 0.01 (1 pp)."""
    bound = crc_risk_bound(99, target_risk=0.05)
    assert bound == pytest.approx(0.05 + 0.01, rel=1e-9)


def test_crc_risk_bound_decreasing_in_n():
    """Larger n â†’ tighter bound."""
    bounds = [crc_risk_bound(n, 0.05) for n in [9, 19, 49, 99, 199]]
    assert bounds == sorted(bounds, reverse=True)


def test_crc_risk_bound_monotone_in_alpha():
    """Higher target_risk â†’ higher bound."""
    bounds = [crc_risk_bound(50, alpha) for alpha in [0.01, 0.05, 0.10, 0.20]]
    assert bounds == sorted(bounds)


def test_crc_risk_bound_n_zero():
    """n=0 â†’ slack = 1.0 (maximum uncertainty)."""
    bound = crc_risk_bound(0, target_risk=0.05)
    assert bound == pytest.approx(1.05)


# ---------------------------------------------------------------------------
# Integration: selective module import
# ---------------------------------------------------------------------------


def test_import_from_selective():
    """CovariateShiftCRC and helpers must be importable from remora.selective."""
    from remora.selective import (  # noqa: F401
        CovariateShiftCRC,
        CRCReport,
        crc_risk_bound,
        phase_importance_weights,
        weighted_conformal_threshold,
    )

