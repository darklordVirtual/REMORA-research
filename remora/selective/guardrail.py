# Author: Stian Skogbrott
# License: Apache-2.0
"""ConformalPhaseGuardrail — split-conformal selective router.

Layers on top of:
- remora.selective.conformal.split_calibration / conformal_threshold
- remora.selective.risk_coverage.risk_coverage_curve / SelectiveAction / RouteDecision
- remora.calibration.trust_calibrator.brier_score / expected_calibration_error

Reports: threshold, holdout_risk, holdout_coverage, ECE, Brier, AUROC, AUPRC,
risk-coverage curve. AUROC/AUPRC are computed without numpy to keep core
dependency-free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from remora.selective.drift_detector import PromptDriftDetector
from remora.calibration.trust_calibrator import (
    brier_score,
    expected_calibration_error,
)
from remora.selective.conformal import (
    UNATTAINABLE_THRESHOLD,
    conformal_threshold,
    coverage_at_threshold,
    split_calibration,
)
from remora.selective.binomial_bounds import risk_upper_confidence_bound
from remora.selective.risk_coverage import (
    RouteDecision,
    SelectiveAction,
    risk_coverage_curve,
)


@dataclass(frozen=True)
class GuardrailReport:
    threshold: float
    target_risk: float
    holdout_risk: float | None
    holdout_coverage: float
    ece: float
    brier: float
    auroc: float
    auprc: float
    holdout_accepted: int = 0
    rc_curve: list[dict] = field(default_factory=list)
    holdout_wrong: int | None = None
    holdout_risk_upper_95: float | None = None
    target_risk_met_by_point_estimate: bool | None = None
    target_risk_met_by_upper_bound: bool | None = None


def _auroc(scores: Sequence[float], labels: Sequence[bool]) -> float:
    """Area under the ROC curve via the Mann-Whitney U statistic."""
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return 0.5
    wins = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(pos) * len(neg))


def _auprc(scores: Sequence[float], labels: Sequence[bool]) -> float:
    """Average precision (area under precision-recall curve)."""
    if not scores:
        return 0.0
    pairs = sorted(zip(scores, labels), key=lambda x: x[0], reverse=True)
    total_pos = sum(1 for _, y in pairs if y)
    if total_pos == 0:
        return 0.0
    tp = 0
    fp = 0
    last_recall = 0.0
    ap = 0.0
    for _, y in pairs:
        if y:
            tp += 1
        else:
            fp += 1
        precision = tp / (tp + fp)
        recall = tp / total_pos
        if recall > last_recall:
            ap += precision * (recall - last_recall)
            last_recall = recall
    return ap


@dataclass
class ConformalPhaseGuardrail:
    """Split-conformal guardrail with calibrated accept/verify/abstain routing."""

    target_risk: float = 0.05
    cal_fraction: float = 0.6
    verify_margin: float = 0.05
    seed: int | None = 0
    threshold: float = UNATTAINABLE_THRESHOLD

    def fit(
        self,
        scores: Sequence[float],
        labels: Sequence[bool],
    ) -> GuardrailReport:
        if len(scores) != len(labels):
            raise ValueError("scores and labels must have same length")
        if not scores:
            raise ValueError("cannot fit on empty holdout")
        cal, test = split_calibration(
            scores, labels, cal_fraction=self.cal_fraction, seed=self.seed
        )
        cal_scores, cal_labels = cal
        test_scores, test_labels = test
        self.threshold = conformal_threshold(
            cal_scores, cal_labels, target_risk=self.target_risk
        )
        # Evaluate on held-out test split.
        accepted = [
            (s, y) for s, y in zip(test_scores, test_labels) if s >= self.threshold
        ]
        if accepted:
            wrong = sum(1 for _, y in accepted if not y)
            holdout_risk: float | None = wrong / len(accepted)
        else:
            # No items cleared the threshold; risk is undefined (0/0), not zero.
            wrong = 0
            holdout_risk = None
        n_accepted = len(accepted)
        holdout_coverage = coverage_at_threshold(test_scores, self.threshold)
        curve = risk_coverage_curve(list(test_scores), list(test_labels))
        holdout_risk_upper_95 = risk_upper_confidence_bound(wrong, n_accepted, alpha=0.05)
        target_risk_met_by_point_estimate = (
            holdout_risk is not None and holdout_risk <= self.target_risk
        )
        target_risk_met_by_upper_bound = (
            holdout_risk_upper_95 is not None
            and holdout_risk_upper_95 <= self.target_risk
        )
        return GuardrailReport(
            threshold=self.threshold,
            target_risk=self.target_risk,
            holdout_risk=holdout_risk,
            holdout_coverage=holdout_coverage,
            ece=expected_calibration_error(list(test_scores), list(test_labels)),
            brier=brier_score(list(test_scores), list(test_labels)),
            auroc=_auroc(test_scores, test_labels),
            auprc=_auprc(test_scores, test_labels),
            holdout_accepted=n_accepted,
            rc_curve=curve,
            holdout_wrong=wrong,
            holdout_risk_upper_95=holdout_risk_upper_95,
            target_risk_met_by_point_estimate=target_risk_met_by_point_estimate,
            target_risk_met_by_upper_bound=target_risk_met_by_upper_bound,
        )

    def route(self, score: float) -> RouteDecision:
        s = float(score)
        if self.threshold >= UNATTAINABLE_THRESHOLD:
            return RouteDecision(
                action=SelectiveAction.ABSTAIN,
                threshold=self.threshold,
                score=s,
                target_risk=self.target_risk,
                reason="Calibration failed to attain target risk; no acceptance possible.",
            )
        if s >= self.threshold:
            return RouteDecision(
                action=SelectiveAction.ACCEPT,
                threshold=self.threshold,
                score=s,
                target_risk=self.target_risk,
                reason="Above conformal threshold.",
            )
        if s >= max(0.0, self.threshold - self.verify_margin):
            return RouteDecision(
                action=SelectiveAction.VERIFY,
                threshold=self.threshold,
                score=s,
                target_risk=self.target_risk,
                reason="Within verify margin of conformal threshold.",
            )
        return RouteDecision(
            action=SelectiveAction.ABSTAIN,
            threshold=self.threshold,
            score=s,
            target_risk=self.target_risk,
            reason="Below conformal threshold by more than verify_margin.",
        )


# ---------------------------------------------------------------------------
# Mondrian (phase-stratified) conformal guardrail
# ---------------------------------------------------------------------------

_KNOWN_PHASES = ("ordered", "critical", "disordered")


@dataclass
class MondrianPhaseGuardrailReport:
    """Per-phase calibration thresholds and holdout metrics."""

    target_risk: float
    thresholds: dict[str, float]
    holdout_risk_per_phase: dict[str, float | None]
    holdout_coverage_per_phase: dict[str, float]
    n_calibration_per_phase: dict[str, int]
    n_test_per_phase: dict[str, int]


@dataclass
class MondrianPhaseGuardrail:
    """Phase-stratified (Mondrian) conformal guardrail.

    Unlike :class:`ConformalPhaseGuardrail` which calibrates a single global
    threshold, this class calibrates *one threshold per consensus phase*
    (ordered / critical / disordered).  This makes the coverage guarantee
    hold **conditionally within each phase** rather than only on average,
    significantly reducing the split-variance problem documented in
    NEGATIVE_RESULTS.md §5.

    The Mondrian coverage guarantee holds under the standard exchangeability
    assumption *within each stratum* — distribution shift across phases does
    not invalidate the guarantee for the phase the query is routed to.

    Parameters
    ----------
    target_risk:
        Per-phase risk target (default 0.05 = 5 % error among accepted items).
    cal_fraction:
        Fraction of data per phase used for calibration; remainder is held out
        for the report metrics.
    seed:
        RNG seed for the per-phase split.

    Usage
    -----
    ::

        guardrail = MondrianPhaseGuardrail(target_risk=0.05)
        report = guardrail.fit(scores, labels, phases)
        decision = guardrail.route(score=0.83, phase="ordered")

    """

    target_risk: float = 0.05
    cal_fraction: float = 0.6
    seed: int | None = 0
    drift_detector: PromptDriftDetector | None = None
    _thresholds: dict[str, float] = field(default_factory=dict)
    _fitted: bool = False

    def fit(
        self,
        scores: Sequence[float],
        labels: Sequence[bool],
        phases: Sequence[str],
    ) -> MondrianPhaseGuardrailReport:
        """Calibrate one conformal threshold per phase.

        Parameters
        ----------
        scores:
            Trust scores (higher = more confident) for each item.
        labels:
            Ground-truth correctness flags (True = correct).
        phases:
            Consensus phase string for each item
            (``"ordered"`` / ``"critical"`` / ``"disordered"``).
        """
        if not (len(scores) == len(labels) == len(phases)):
            raise ValueError("scores, labels, and phases must have equal length")

        thresholds: dict[str, float] = {}
        holdout_risk: dict[str, float | None] = {}
        holdout_coverage: dict[str, float] = {}
        n_cal: dict[str, int] = {}
        n_test: dict[str, int] = {}

        for phase in _KNOWN_PHASES:
            indices = [i for i, p in enumerate(phases) if p == phase]
            if len(indices) < 4:
                # Too few samples to calibrate reliably; fall back to UNATTAINABLE
                thresholds[phase] = UNATTAINABLE_THRESHOLD
                holdout_risk[phase] = None
                holdout_coverage[phase] = 0.0
                n_cal[phase] = 0
                n_test[phase] = len(indices)
                continue

            phase_scores = [scores[i] for i in indices]
            phase_labels = [labels[i] for i in indices]

            cal, test = split_calibration(
                phase_scores, phase_labels,
                cal_fraction=self.cal_fraction,
                seed=self.seed,
            )
            cal_s, cal_l = cal
            test_s, test_l = test

            thresh = conformal_threshold(cal_s, cal_l, target_risk=self.target_risk)
            thresholds[phase] = thresh
            n_cal[phase] = len(cal_s)
            n_test[phase] = len(test_s)

            accepted = [(s, y) for s, y in zip(test_s, test_l) if s >= thresh]
            if accepted:
                wrong = sum(1 for _, y in accepted if not y)
                holdout_risk[phase] = wrong / len(accepted)
            else:
                holdout_risk[phase] = None

            holdout_coverage[phase] = coverage_at_threshold(test_s, thresh)

        self._thresholds = thresholds
        self._fitted = True

        return MondrianPhaseGuardrailReport(
            target_risk=self.target_risk,
            thresholds=dict(thresholds),
            holdout_risk_per_phase=holdout_risk,
            holdout_coverage_per_phase=holdout_coverage,
            n_calibration_per_phase=n_cal,
            n_test_per_phase=n_test,
        )

    def threshold_for(self, phase: str) -> float:
        """Return the calibrated threshold for a given phase (post-fit)."""
        if not self._fitted:
            raise RuntimeError("MondrianPhaseGuardrail must be fitted before use.")
        return self._thresholds.get(phase, UNATTAINABLE_THRESHOLD)

    def is_safe(self, score: float, phase: str) -> bool:
        """Return True if *score* meets the per-phase conformal threshold."""
        return float(score) >= self.threshold_for(phase)

    def route(self, score: float, phase: str, prompt: str | None = None) -> RouteDecision:
        """Route a single item to ACCEPT / ABSTAIN based on its phase threshold.

        Parameters
        ----------
        score:
            Trust score for the item.
        phase:
            Consensus phase string (``"ordered"`` / ``"critical"`` / ``"disordered"``).
        prompt:
            Optional raw prompt text.  When a :attr:`drift_detector` is
            attached and *prompt* is provided, distribution shift is checked
            before conformal routing.  If shift is detected the item is
            routed to ABSTAIN regardless of the trust score, because the
            exchangeability assumption underlying the conformal guarantee
            may no longer hold.
        """
        if prompt is not None and self.drift_detector is not None:
            if self.drift_detector.detect(prompt):
                _thresh = (
                    self._thresholds.get(phase, UNATTAINABLE_THRESHOLD)
                    if self._fitted
                    else UNATTAINABLE_THRESHOLD
                )
                return RouteDecision(
                    action=SelectiveAction.ABSTAIN,
                    threshold=_thresh,
                    score=float(score),
                    target_risk=self.target_risk,
                    reason=(
                        "Distribution shift detected: conformal exchangeability "
                        "assumption may not hold. Manual review required."
                    ),
                )
        thresh = self.threshold_for(phase)
        s = float(score)
        if thresh >= UNATTAINABLE_THRESHOLD:
            return RouteDecision(
                action=SelectiveAction.ABSTAIN,
                threshold=thresh,
                score=s,
                target_risk=self.target_risk,
                reason=f"No calibration data for phase '{phase}'; cannot accept.",
            )
        if s >= thresh:
            return RouteDecision(
                action=SelectiveAction.ACCEPT,
                threshold=thresh,
                score=s,
                target_risk=self.target_risk,
                reason=f"Above Mondrian threshold for phase '{phase}'.",
            )
        return RouteDecision(
            action=SelectiveAction.ABSTAIN,
            threshold=thresh,
            score=s,
            target_risk=self.target_risk,
            reason=f"Below Mondrian threshold for phase '{phase}'.",
        )


# ---------------------------------------------------------------------------
# Phase-aware guardrail with critical-phase inversion
# ---------------------------------------------------------------------------


@dataclass
class PhaseAwareGuardrail:
    """Selective router that exploits critical-phase trust-score inversion.

    In the critical phase, trust scores *anti-correlate* with correctness
    (high-tau critical items: ~27-38% accurate; low-tau: ~71-75% accurate).
    Standard conformal calibration fails here because it assumes a monotonic
    accuracy-score relationship.

    This guardrail handles this by applying an *inverted* score for the
    critical phase: ``effective_score = 1 - trust_score``.  Items with low
    trust (high inverted score) are selected; the conformal threshold is
    calibrated on the inverted signal so the coverage guarantee still holds
    within the phase.

    Operating points — empirical flat-phase policy, N=544 benchmark
    (see results/phase_aware_guardrail_n544_results.json for full artifact):
    - Ordered only (18.2%): 86.9% accuracy  [78.8%, 92.2%]
    - + inverted critical, tau<0.10 (22.1%): 85.0% accuracy  [77.5%, 90.3%]

    Note: these are empirical figures from accepting *all* phase-qualified items
    (no conformal threshold applied). With conformal target_risk=0.05 the ordered
    threshold is unattainable (N=99 ordered items, 13.1% error > 5% target).
    At target_risk=0.13 the conformal guarantee holds with coverage ≈ 18.8%.

    Parameters
    ----------
    target_risk:
        Per-phase error rate target (default 0.05).
    cal_fraction:
        Fraction of each phase used for calibration; remainder is test set.
    max_critical_tau:
        Hard ceiling on trust score for critical-phase acceptance.  Items
        with tau >= this value are excluded regardless of the conformal
        threshold (they are the groupthink-high-confidence errors).
        Default 0.10 matches the empirical inversion boundary.
    include_disordered:
        Whether to apply conformal selection on disordered items (default
        False — disordered accuracy is too low to be useful at any threshold).
    seed:
        RNG seed for calibration/test splits.
    """

    target_risk: float = 0.05
    cal_fraction: float = 0.6
    max_critical_tau: float = 0.10
    include_disordered: bool = False
    seed: int | None = 0

    _ordered_threshold: float = field(default=UNATTAINABLE_THRESHOLD, init=False)
    _critical_inv_threshold: float = field(default=UNATTAINABLE_THRESHOLD, init=False)
    _fitted: bool = field(default=False, init=False)

    def fit(
        self,
        scores: Sequence[float],
        labels: Sequence[bool],
        phases: Sequence[str],
    ) -> dict:
        """Calibrate phase-specific thresholds.

        Returns a summary dict with per-phase threshold and holdout metrics.
        """
        if not (len(scores) == len(labels) == len(phases)):
            raise ValueError("scores, labels, and phases must have equal length")

        summary: dict = {}

        # Ordered phase: standard conformal on trust score
        ord_idx = [i for i, p in enumerate(phases) if p == "ordered"]
        if len(ord_idx) >= 4:
            ord_s = [scores[i] for i in ord_idx]
            ord_l = [labels[i] for i in ord_idx]
            (cal_s, cal_l), (test_s, test_l) = split_calibration(
                ord_s, ord_l, cal_fraction=self.cal_fraction, seed=self.seed
            )
            self._ordered_threshold = conformal_threshold(
                cal_s, cal_l, target_risk=self.target_risk
            )
            accepted = [(s, y) for s, y in zip(test_s, test_l) if s >= self._ordered_threshold]
            summary["ordered"] = {
                "threshold": self._ordered_threshold,
                "n_cal": len(cal_s),
                "n_test": len(test_s),
                "holdout_coverage": coverage_at_threshold(test_s, self._ordered_threshold),
                "holdout_risk": (
                    sum(1 for _, y in accepted if not y) / len(accepted)
                    if accepted else None
                ),
            }

        # Critical phase: calibrate on *inverted* score (1 - tau) after hard
        # filtering out high-tau items (the groupthink errors)
        crit_idx = [i for i, p in enumerate(phases) if p == "critical"]
        low_tau_crit = [i for i in crit_idx if scores[i] < self.max_critical_tau]
        if len(low_tau_crit) >= 4:
            crit_s_inv = [1.0 - scores[i] for i in low_tau_crit]
            crit_l = [labels[i] for i in low_tau_crit]
            (cal_s, cal_l), (test_s, test_l) = split_calibration(
                crit_s_inv, crit_l, cal_fraction=self.cal_fraction, seed=self.seed
            )
            self._critical_inv_threshold = conformal_threshold(
                cal_s, cal_l, target_risk=self.target_risk
            )
            accepted = [(s, y) for s, y in zip(test_s, test_l) if s >= self._critical_inv_threshold]
            summary["critical"] = {
                "threshold_inverted": self._critical_inv_threshold,
                "threshold_tau_max": 1.0 - self._critical_inv_threshold,
                "max_critical_tau": self.max_critical_tau,
                "n_cal": len(cal_s),
                "n_test": len(test_s),
                "holdout_coverage": coverage_at_threshold(test_s, self._critical_inv_threshold),
                "holdout_risk": (
                    sum(1 for _, y in accepted if not y) / len(accepted)
                    if accepted else None
                ),
            }

        self._fitted = True
        return summary

    def route(self, score: float, phase: str) -> RouteDecision:
        """Route one item using phase-aware thresholding."""
        if not self._fitted:
            raise RuntimeError("PhaseAwareGuardrail must be fitted before use.")

        s = float(score)

        if phase == "ordered":
            thresh = self._ordered_threshold
            if thresh >= UNATTAINABLE_THRESHOLD:
                return RouteDecision(
                    action=SelectiveAction.ABSTAIN,
                    threshold=thresh,
                    score=s,
                    target_risk=self.target_risk,
                    reason="Ordered phase: calibration failed.",
                )
            if s >= thresh:
                return RouteDecision(
                    action=SelectiveAction.ACCEPT,
                    threshold=thresh,
                    score=s,
                    target_risk=self.target_risk,
                    reason="Ordered phase: above conformal threshold.",
                )
            return RouteDecision(
                action=SelectiveAction.ABSTAIN,
                threshold=thresh,
                score=s,
                target_risk=self.target_risk,
                reason="Ordered phase: below conformal threshold.",
            )

        if phase == "critical":
            # Hard gate: reject high-tau items (the groupthink errors)
            if s >= self.max_critical_tau:
                return RouteDecision(
                    action=SelectiveAction.ABSTAIN,
                    threshold=self._critical_inv_threshold,
                    score=s,
                    target_risk=self.target_risk,
                    reason=(
                        f"Critical phase: tau={s:.3f} >= max_critical_tau="
                        f"{self.max_critical_tau:.2f}. High-tau critical items "
                        "exhibit trust inversion (groupthink) and are excluded."
                    ),
                )
            # Inverted conformal selection for low-tau critical items
            inv_s = 1.0 - s
            thresh = self._critical_inv_threshold
            if thresh >= UNATTAINABLE_THRESHOLD:
                return RouteDecision(
                    action=SelectiveAction.ABSTAIN,
                    threshold=thresh,
                    score=s,
                    target_risk=self.target_risk,
                    reason="Critical phase: inverted calibration failed.",
                )
            if inv_s >= thresh:
                return RouteDecision(
                    action=SelectiveAction.ACCEPT,
                    threshold=thresh,
                    score=s,
                    target_risk=self.target_risk,
                    reason=(
                        f"Critical phase: inverted score {inv_s:.3f} >= "
                        f"threshold {thresh:.3f} (exploiting trust inversion)."
                    ),
                )
            return RouteDecision(
                action=SelectiveAction.ABSTAIN,
                threshold=thresh,
                score=s,
                target_risk=self.target_risk,
                reason="Critical phase: inverted score below threshold.",
            )

        # Disordered phase
        if self.include_disordered:
            # Fallback to standard ordered threshold as a conservative bound
            thresh = self._ordered_threshold
            if thresh < UNATTAINABLE_THRESHOLD and s >= thresh:
                return RouteDecision(
                    action=SelectiveAction.ACCEPT,
                    threshold=thresh,
                    score=s,
                    target_risk=self.target_risk,
                    reason="Disordered phase: accepted via ordered threshold (conservative).",
                )
        return RouteDecision(
            action=SelectiveAction.ABSTAIN,
            threshold=UNATTAINABLE_THRESHOLD,
            score=s,
            target_risk=self.target_risk,
            reason="Disordered phase: excluded (accuracy too low for safe routing).",
        )

