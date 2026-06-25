# Author: Stian Skogbrott
# License: Apache-2.0
"""Regression tests for response-correlation vs error-correlation separation."""
from __future__ import annotations

from remora.calibration.trust_calibrator import TrustCalibrator, brier_score
from remora.correlation_error import correlation_separation_report
from remora.selective.risk_coverage import SelectiveAction, SelectiveRouter, risk_coverage_curve


def test_response_agreement_is_not_error_correlation_by_definition():
    labels = [True, False, True, False, True, False, True, False]
    preds_a = [True, False, True, False, True, False, True, False]  # perfect
    preds_b = [True, False, True, False, False, False, True, True]

    report = correlation_separation_report(preds_a, preds_b, labels)
    assert report.rho_response > 0.70
    assert report.rho_error == 0.0


def test_temperature_calibrator_improves_nll_on_simple_shifted_case():
    raw_scores = [0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50, 0.45]
    labels = [True, True, False, False, False, False, False, False]

    calibrator = TrustCalibrator()
    calibrator.fit(raw_scores, labels)
    calibrated = calibrator.calibrate(raw_scores)

    assert 0.25 <= calibrator.temperature < 8.0
    assert brier_score(calibrated, labels) <= brier_score(raw_scores, labels)


def test_selective_router_target_risk_produces_abstention_region():
    scores = [0.99, 0.95, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40]
    labels = [True, True, True, True, False, False, False, False]

    curve = risk_coverage_curve(scores, labels)
    assert curve[0]["coverage"] < curve[-1]["coverage"]
    assert curve[0]["risk"] <= curve[-1]["risk"]

    router = SelectiveRouter(target_risk=0.10, verify_margin=0.05)
    router.fit(scores, labels)

    high = router.route(0.95)
    low = router.route(0.30)
    assert high.action in {SelectiveAction.ACCEPT, SelectiveAction.VERIFY}
    assert low.action in {SelectiveAction.ABSTAIN, SelectiveAction.ESCALATE}
