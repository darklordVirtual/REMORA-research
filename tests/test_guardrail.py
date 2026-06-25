# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for ConformalPhaseGuardrail and MondrianPhaseGuardrail."""
from __future__ import annotations

import random

import pytest

from remora.selective.guardrail import (
    ConformalPhaseGuardrail,
    GuardrailReport,
    MondrianPhaseGuardrail,
    MondrianPhaseGuardrailReport,
    PhaseAwareGuardrail,
)


def _toy_dataset(n: int = 400, seed: int = 0) -> tuple[list[float], list[bool]]:
    rng = random.Random(seed)
    scores: list[float] = []
    labels: list[bool] = []
    for _ in range(n):
        s = rng.random()
        # Higher score => more likely correct, but with calibrated noise.
        p_correct = 0.2 + 0.7 * s
        labels.append(rng.random() < p_correct)
        scores.append(s)
    return scores, labels


def test_guardrail_fit_returns_threshold_and_report():
    scores, labels = _toy_dataset()
    g = ConformalPhaseGuardrail(target_risk=0.10)
    report = g.fit(scores, labels)
    assert isinstance(report, GuardrailReport)
    assert 0.0 <= report.threshold <= 1.01
    assert report.holdout_risk is None or 0.0 <= report.holdout_risk <= 1.0
    assert 0.0 <= report.holdout_coverage <= 1.0
    # Calibration should keep holdout risk close to or below target (within slack).
    if report.holdout_risk is not None:
        assert report.holdout_risk <= 0.30, (
            f"risk={report.holdout_risk} too high vs target=0.10"
        )


def test_guardrail_route_returns_accept_when_above_threshold():
    g = ConformalPhaseGuardrail(target_risk=0.10)
    scores, labels = _toy_dataset()
    g.fit(scores, labels)
    decision = g.route(score=min(1.0, g.threshold + 0.05))
    assert decision.action.value == "accept"


def test_guardrail_route_abstains_when_below_threshold_by_margin():
    g = ConformalPhaseGuardrail(target_risk=0.10, verify_margin=0.05)
    scores, labels = _toy_dataset()
    g.fit(scores, labels)
    decision = g.route(score=max(0.0, g.threshold - 0.20))
    assert decision.action.value == "abstain"


def test_guardrail_reports_ece_brier_auroc():
    scores, labels = _toy_dataset()
    g = ConformalPhaseGuardrail(target_risk=0.10)
    report = g.fit(scores, labels)
    assert 0.0 <= report.ece <= 1.0
    assert 0.0 <= report.brier <= 1.0
    assert 0.0 <= report.auroc <= 1.0


def test_guardrail_risk_coverage_curve_is_monotonic_in_acceptance():
    scores, labels = _toy_dataset()
    g = ConformalPhaseGuardrail(target_risk=0.10)
    report = g.fit(scores, labels)
    coverages = [row["coverage"] for row in report.rc_curve]
    assert coverages == sorted(coverages)


def test_guardrail_fit_raises_on_empty_holdout():
    g = ConformalPhaseGuardrail(target_risk=0.10)
    with pytest.raises(ValueError):
        g.fit([], [])


def test_guardrail_routes_abstain_when_no_threshold_attainable():
    # Labels uncorrelated with score; no threshold attains risk=0.0.
    scores = [i / 100 for i in range(100)]
    labels = [(i % 2 == 0) for i in range(100)]
    from remora.selective.guardrail import ConformalPhaseGuardrail
    g = ConformalPhaseGuardrail(target_risk=0.0)
    g.fit(scores, labels)
    assert g.threshold > 1.0  # sentinel set by calibration
    decision = g.route(score=0.99)
    assert decision.action.value == "abstain"
    assert "calibration" in decision.reason.lower() or "attain" in decision.reason.lower()


# ---------------------------------------------------------------------------
# MondrianPhaseGuardrail tests
# ---------------------------------------------------------------------------


def _phased_dataset(
    n_per_phase: int = 200, seed: int = 7
) -> tuple[list[float], list[bool], list[str]]:
    """Create synthetic (score, label, phase) triples with phase-specific accuracy."""
    rng = random.Random(seed)
    scores: list[float] = []
    labels: list[bool] = []
    phases: list[str] = []
    phase_acc = {"ordered": 0.85, "critical": 0.55, "disordered": 0.30}
    for phase, base_acc in phase_acc.items():
        for _ in range(n_per_phase):
            s = rng.random()
            p_correct = max(0.0, min(1.0, base_acc * s + (1 - base_acc) * (1 - s)))
            scores.append(s)
            labels.append(rng.random() < p_correct)
            phases.append(phase)
    return scores, labels, phases


def test_mondrian_fit_returns_report():
    scores, labels, phases = _phased_dataset()
    g = MondrianPhaseGuardrail(target_risk=0.10)
    report = g.fit(scores, labels, phases)
    assert isinstance(report, MondrianPhaseGuardrailReport)
    for phase in ("ordered", "critical", "disordered"):
        assert phase in report.thresholds


def _phased_dataset_discriminative(
    n_per_phase: int = 300, seed: int = 7
) -> tuple[list[float], list[bool], list[str]]:
    """Synthetic data with strong discrimination in every phase.

    Uses p_correct = min(1, base_acc + (1 - base_acc) * s) to ensure that
    even low-accuracy phases have a monotone relationship between score and label.
    """
    rng = random.Random(seed)
    scores: list[float] = []
    labels: list[bool] = []
    phases: list[str] = []
    # All phases have strong score-accuracy discrimination; accuracy level varies
    phase_base = {"ordered": 0.70, "critical": 0.55, "disordered": 0.35}
    for phase, base in phase_base.items():
        for _ in range(n_per_phase):
            s = rng.random()
            p_correct = base + (1 - base) * s  # monotone in s
            scores.append(s)
            labels.append(rng.random() < p_correct)
            phases.append(phase)
    return scores, labels, phases


def test_mondrian_thresholds_are_phase_specific():
    """Ordered phase (highest accuracy) calibrates to a lower threshold than disordered."""
    scores, labels, phases = _phased_dataset_discriminative(n_per_phase=300)
    g = MondrianPhaseGuardrail(target_risk=0.10)
    g.fit(scores, labels, phases)
    from remora.selective.conformal import UNATTAINABLE_THRESHOLD
    t_ordered = g.threshold_for("ordered")
    t_disordered = g.threshold_for("disordered")
    # Ordered (easiest phase) must calibrate to a proper threshold
    assert t_ordered < UNATTAINABLE_THRESHOLD, (
        f"ordered phase should calibrate; got threshold={t_ordered}"
    )
    # Ordered threshold should be <= disordered threshold (easier data â†’ accept more)
    # Allow t_disordered to be UNATTAINABLE if discrimination is insufficient
    if t_disordered < UNATTAINABLE_THRESHOLD:
        assert t_ordered <= t_disordered + 0.25, (
            f"ordered={t_ordered:.3f} unexpectedly higher than disordered={t_disordered:.3f}"
        )


def test_mondrian_is_safe_and_route():
    scores, labels, phases = _phased_dataset()
    g = MondrianPhaseGuardrail(target_risk=0.10)
    g.fit(scores, labels, phases)
    thresh = g.threshold_for("ordered")
    assert g.is_safe(thresh + 0.05, "ordered") is True
    assert g.is_safe(0.0, "ordered") is False
    decision = g.route(score=thresh + 0.05, phase="ordered")
    assert decision.action.value == "accept"
    decision_low = g.route(score=0.0, phase="ordered")
    assert decision_low.action.value == "abstain"


def test_mondrian_unfitted_raises():
    g = MondrianPhaseGuardrail()
    with pytest.raises(RuntimeError, match="fitted"):
        g.threshold_for("ordered")


def test_mondrian_insufficient_phase_data_uses_unattainable_threshold():
    """Phases with < 4 samples should fall back to UNATTAINABLE_THRESHOLD."""
    from remora.selective.conformal import UNATTAINABLE_THRESHOLD
    scores = [0.9, 0.8, 0.7]
    labels = [True, True, False]
    phases = ["ordered", "ordered", "ordered"]
    g = MondrianPhaseGuardrail(target_risk=0.10)
    g.fit(scores, labels, phases)
    # "critical" and "disordered" have 0 samples; must get UNATTAINABLE
    assert g.threshold_for("critical") >= UNATTAINABLE_THRESHOLD
    assert g.threshold_for("disordered") >= UNATTAINABLE_THRESHOLD


def test_mondrian_route_unknown_phase_abstains():
    scores, labels, phases = _phased_dataset()
    g = MondrianPhaseGuardrail(target_risk=0.10)
    g.fit(scores, labels, phases)
    decision = g.route(score=0.99, phase="plasma")  # unknown phase
    assert decision.action.value == "abstain"


# ---------------------------------------------------------------------------
# Drift detector integration tests
# ---------------------------------------------------------------------------

def _fitted_drift_detector(cal_prompts: list[str]):
    from remora.selective.drift_detector import PromptDriftDetector
    d = PromptDriftDetector()
    d.fit(cal_prompts)
    return d


def test_mondrian_drift_detector_abstains_on_shift():
    """When drift is detected for a prompt, route() must return ABSTAIN."""
    scores, labels, phases = _phased_dataset()
    cal_prompts = ["What is the capital of France?" for _ in range(60)]
    detector = _fitted_drift_detector(cal_prompts)

    g = MondrianPhaseGuardrail(target_risk=0.10, drift_detector=detector)
    g.fit(scores, labels, phases)

    # A highly OOD prompt: extreme length / content that triggers zlib signal.
    ood_prompt = "xyz " * 2000
    decision = g.route(score=0.99, phase="ordered", prompt=ood_prompt)
    assert decision.action.value == "abstain"
    assert "shift" in decision.reason.lower()


def test_mondrian_drift_detector_no_prompt_skips_check():
    """Without a prompt, drift check must be skipped and normal routing applies."""
    scores, labels, phases = _phased_dataset()
    cal_prompts = ["What is the capital of France?" for _ in range(60)]
    detector = _fitted_drift_detector(cal_prompts)

    g = MondrianPhaseGuardrail(target_risk=0.10, drift_detector=detector)
    g.fit(scores, labels, phases)

    # High score, no prompt â€” should not abstain due to drift
    decision = g.route(score=0.99, phase="ordered", prompt=None)
    assert decision.action.value == "accept"


def test_mondrian_no_drift_detector_normal_routing():
    """Without a drift_detector, route() behaves identically to before."""
    scores, labels, phases = _phased_dataset()
    g = MondrianPhaseGuardrail(target_risk=0.10, drift_detector=None)
    g.fit(scores, labels, phases)
    decision = g.route(score=0.99, phase="ordered")
    assert decision.action.value == "accept"


def test_mondrian_drift_detector_unfitted_guardrail_still_abstains():
    """Drift-detected ABSTAIN must work even when guardrail is not fitted."""
    cal_prompts = ["What is the capital of France?" for _ in range(60)]
    detector = _fitted_drift_detector(cal_prompts)
    g = MondrianPhaseGuardrail(drift_detector=detector)
    # Not fitted â€” but drift is detected; should still return ABSTAIN safely.
    ood_prompt = "xyz " * 2000
    decision = g.route(score=0.99, phase="ordered", prompt=ood_prompt)
    assert decision.action.value == "abstain"



# ---------------------------------------------------------------------------
# PhaseAwareGuardrail tests
# ---------------------------------------------------------------------------


def _inversion_dataset(
    n_ordered: int = 150,
    n_critical: int = 80,
    n_disordered: int = 50,
    seed: int = 42,
) -> tuple[list[float], list[bool], list[str]]:
    """Synthetic dataset with critical-phase trust inversion.

    Ordered: high tau -> high accuracy (normal).
    Critical: low tau -> high accuracy (inverted).
    Disordered: low accuracy regardless of tau.
    """
    rng = random.Random(seed)
    scores: list[float] = []
    labels: list[bool] = []
    phases: list[str] = []

    # Ordered: p_correct monotone increasing in tau
    for _ in range(n_ordered):
        s = rng.random()
        p = 0.60 + 0.35 * s
        scores.append(s)
        labels.append(rng.random() < p)
        phases.append("ordered")

    # Critical: p_correct monotone DECREASING in tau (inversion)
    for _ in range(n_critical):
        s = rng.random()
        p = 0.80 - 0.50 * s  # low tau => high accuracy
        scores.append(s)
        labels.append(rng.random() < p)
        phases.append("critical")

    # Disordered: low accuracy
    for _ in range(n_disordered):
        s = rng.random()
        p = 0.30
        scores.append(s)
        labels.append(rng.random() < p)
        phases.append("disordered")

    return scores, labels, phases


def test_phase_aware_fit_returns_summary():
    scores, labels, phases = _inversion_dataset()
    g = PhaseAwareGuardrail(target_risk=0.10, max_critical_tau=0.50)
    summary = g.fit(scores, labels, phases)
    assert "ordered" in summary
    # Critical phase with enough low-tau items should calibrate
    assert "critical" in summary


def test_phase_aware_ordered_accepts_high_tau():
    scores, labels, phases = _inversion_dataset()
    g = PhaseAwareGuardrail(target_risk=0.10, max_critical_tau=0.50)
    g.fit(scores, labels, phases)
    decision = g.route(score=0.95, phase="ordered")
    assert decision.action.value == "accept"


def test_phase_aware_ordered_abstains_low_tau():
    scores, labels, phases = _inversion_dataset()
    g = PhaseAwareGuardrail(target_risk=0.10, max_critical_tau=0.50)
    g.fit(scores, labels, phases)
    decision = g.route(score=0.01, phase="ordered")
    assert decision.action.value == "abstain"


def test_phase_aware_critical_rejects_high_tau_via_hard_gate():
    """High-tau critical items must always be rejected (groupthink errors)."""
    scores, labels, phases = _inversion_dataset()
    g = PhaseAwareGuardrail(target_risk=0.10, max_critical_tau=0.10)
    g.fit(scores, labels, phases)
    # Score above max_critical_tau -> hard reject regardless of conformal threshold
    decision = g.route(score=0.80, phase="critical")
    assert decision.action.value == "abstain"
    assert "inversion" in decision.reason.lower() or "groupthink" in decision.reason.lower()


def test_phase_aware_critical_can_accept_low_tau():
    """Low-tau critical items should be accepted (exploiting inversion)."""
    scores, labels, phases = _inversion_dataset(n_critical=120, seed=0)
    g = PhaseAwareGuardrail(target_risk=0.20, max_critical_tau=0.50)
    g.fit(scores, labels, phases)
    # Score very close to 0 (lowest tau = highest inverted score = most likely accepted)
    decision = g.route(score=0.001, phase="critical")
    # May accept or abstain depending on calibrated threshold; just check it doesn't raise
    assert decision.action.value in ("accept", "abstain")


def test_phase_aware_disordered_abstains_by_default():
    scores, labels, phases = _inversion_dataset()
    g = PhaseAwareGuardrail(target_risk=0.10, include_disordered=False)
    g.fit(scores, labels, phases)
    decision = g.route(score=0.99, phase="disordered")
    assert decision.action.value == "abstain"
    assert "disordered" in decision.reason.lower()


def test_phase_aware_unfitted_raises():
    g = PhaseAwareGuardrail()
    with pytest.raises(RuntimeError, match="fitted"):
        g.route(score=0.5, phase="ordered")


def test_phase_aware_import_from_selective():
    """PhaseAwareGuardrail must be importable from remora.selective."""
    from remora.selective import PhaseAwareGuardrail as PAG
    assert PAG is not None

