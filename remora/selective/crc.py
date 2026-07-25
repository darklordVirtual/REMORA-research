# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Weighted empirical selective router (CRC-inspired, NOT a CRC procedure).

External review R3-01 (2026-07-25): this module previously presented itself
as an implementation of Conformal Risk Control (Angelopoulos, Bates, Fisch,
Lei & Schuster 2022, arXiv:2208.02814). It is not, for two structural
reasons, and no wording about weights can repair them:

1. **The threshold rule omits the finite-sample term.** CRC selects
   ``λ̂ = inf{λ : (n/(n+1))·R̂_n(λ) + B/(n+1) ≤ α}``. This selector uses the
   raw weighted empirical constraint ``L̄(λ) ≤ α`` with no ``B/(n+1)``
   correction and no test-point weight ``w_{n+1}`` in the normalisation, so
   it can commit thresholds the CRC procedure would reject.
2. **The selective loss is not monotone.** The controlled quantity here is
   the conditional error rate among ACCEPTED items, which can move in either
   direction as ``λ`` changes. Theorem 1 requires a per-example loss that is
   non-increasing in ``λ``; it does not attach to this loss even with
   correctly specified density-ratio weights.

What this module actually is: a deterministic, importance-weighted empirical
threshold selector — pick the smallest ``λ`` (maximum coverage) whose
weighted empirical error among accepted calibration items stays at or below
``α``, evaluate on a held-out split, and report the plain holdout risk.
Phase weights (1.0 on target-phase match, ``β = 0.10`` otherwise) are a
hand-tuned heuristic, not a density ratio. All quality evidence for this
component is EMPIRICAL (repeated-split holdout results in the committed
artifacts); no distribution-free guarantee is claimed.

``CRCReport.finite_sample_slack`` and ``nominal_risk_bound`` are retained as
informational reference values for comparison with the CRC literature; they
are NOT applicable bounds for this selector.

Naming: the primary class is :class:`WeightedEmpiricalSelectiveRouter`;
``CovariateShiftCRC`` remains as a backward-compatible alias (the historical
name appears in committed artifacts and earlier documents).

Reference (for the framework this is inspired by, not implementing):
Angelopoulos, A. N., Bates, S., Fisch, A., Lei, L., & Schuster, T. (2022).
Conformal risk control. *arXiv:2208.02814*.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from remora.selective.conformal import UNATTAINABLE_THRESHOLD, coverage_at_threshold


# ---------------------------------------------------------------------------
# Core CRC algorithm
# ---------------------------------------------------------------------------


def weighted_conformal_threshold(
    scores: Sequence[float],
    labels: Sequence[bool],
    weights: Sequence[float] | None = None,
    target_risk: float = 0.05,
) -> float:
    """Importance-weighted EMPIRICAL selective threshold (not CRC).

    Finds the smallest threshold ``λ`` (i.e. maximum coverage) such that the
    weighted empirical risk ``L̄(λ) ≤ α``, where::

        L̄(λ) = ∑_i w̃_i · ℓ_i(λ),  w̃_i = w_i / ∑_j w_j

    and ``ℓ_i(λ) = 1{score_i < λ ∧ label_i = False} / 1{score_i ≥ λ}``
    is the miscoverage indicator for item ``i`` at threshold ``λ``.

    This is NOT the CRC selection rule: it applies the raw constraint
    ``L̄(λ) ≤ α`` with no ``B/(n+1)`` finite-sample term and no test-point
    weight, and the accepted-conditional loss is not monotone in ``λ`` (see
    the module docstring). Treat the output as an empirical operating point.

    Parameters
    ----------
    scores:
        Per-item trust scores in ``[0, 1]``.
    labels:
        Per-item correctness flags (``True`` = correct).
    weights:
        Importance weights ``w_i ≥ 0``.  ``None`` uses uniform weights
        (equivalent to standard split-conformal calibration).
    target_risk:
        Tolerated error rate ``α ∈ [0, 1]``.

    Returns
    -------
    float
        Threshold ``λ̂``, or ``UNATTAINABLE_THRESHOLD`` if no threshold
        satisfies the target risk.

    Notes
    -----
    * The algorithm iterates score descending (highest to lowest), accumulating
      weighted accepted items.  A threshold is committed only after all tied
      scores are consumed.
    * Under uniform weights this reduces exactly to
      :func:`~remora.selective.conformal.conformal_threshold`.

    Non-applicability of Theorem 1 (Angelopoulos et al. 2022)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    The theorem's ``E[L(λ̂)] ≤ α + B/(n + 1)`` bound does NOT apply here:
    the selection rule above lacks the ``B/(n+1)`` term and the loss is not
    monotone. Reported results for this selector are empirical only.
    """
    if len(scores) != len(labels):
        raise ValueError("scores and labels must have equal length")
    if not scores:
        return UNATTAINABLE_THRESHOLD
    if not 0.0 <= target_risk <= 1.0:
        raise ValueError("target_risk must be in [0, 1]")

    n = len(scores)
    if weights is None:
        w = [1.0] * n
    else:
        if len(weights) != n:
            raise ValueError("weights must have the same length as scores")
        w = [max(0.0, float(x)) for x in weights]

    total_weight = sum(w)
    if total_weight == 0.0:
        return UNATTAINABLE_THRESHOLD

    # Sort descending by score
    ranked = sorted(zip(scores, labels, w), key=lambda t: t[0], reverse=True)

    accumulated_weight = 0.0
    weighted_wrong = 0.0
    best_threshold = UNATTAINABLE_THRESHOLD
    i = 0

    while i < n:
        # Consume the entire tied block at score ranked[i][0]
        s = ranked[i][0]
        j = i
        while j < n and ranked[j][0] == s:
            accumulated_weight += ranked[j][2]
            if not ranked[j][1]:      # incorrect prediction
                weighted_wrong += ranked[j][2]
            j += 1

        if accumulated_weight > 0.0:
            weighted_risk = weighted_wrong / accumulated_weight
            if weighted_risk <= target_risk:
                best_threshold = float(s)

        i = j

    return best_threshold


@dataclass(frozen=True)
class CRCReport:
    """Summary metrics from :class:`WeightedEmpiricalSelectiveRouter` calibration.

    Attributes
    ----------
    threshold:
        Calibrated threshold ``λ̂``.
    target_risk:
        Requested risk bound ``α``.
    holdout_risk:
        Empirical risk on the held-out test set (unweighted count of wrong
        accepts over accepts), or ``None`` if no items were accepted.
        Renamed from ``weighted_holdout_risk`` (external paper review
        2026-07-24): test-set importance weights were never applied, so the
        old name overstated the computation.
    holdout_coverage:
        Fraction of test items accepted (coverage at ``λ̂``).
    n_calibration:
        Number of items in the calibration split.
    n_test:
        Number of items in the test split.
    total_weight:
        Sum of importance weights on the calibration set.
    finite_sample_slack:
        Upper bound ``1 / (n_calibration + 1)`` on the expected overshoot
        above ``target_risk`` (from Theorem 1 of Angelopoulos et al. 2022).
    nominal_risk_bound:
        ``target_risk + finite_sample_slack``. Renamed from
        ``guaranteed_risk_bound`` (external paper review 2026-07-24): the
        Theorem-1 expected-risk guarantee requires correctly specified
        importance weights (a known/estimated density ratio, Tibshirani et
        al. 2019); the default phase-heuristic weights (1.0 match / β
        mismatch) do not satisfy that condition, so this value is a nominal
        target, not a formal guarantee, unless the caller supplies valid
        density-ratio weights.
    """

    threshold: float
    target_risk: float
    holdout_risk: float | None
    holdout_coverage: float
    n_calibration: int
    n_test: int
    total_weight: float
    finite_sample_slack: float
    nominal_risk_bound: float


# ---------------------------------------------------------------------------
# High-level CRC guardrail
# ---------------------------------------------------------------------------


@dataclass
class WeightedEmpiricalSelectiveRouter:
    """Weighted empirical selective router for phase-shifted test slices.

    Calibrates an importance-weighted EMPIRICAL threshold (see the module
    docstring: this is not the CRC procedure and carries no distribution-free
    guarantee) and exposes a ``route()`` method compatible with
    :class:`~remora.selective.guardrail.ConformalPhaseGuardrail`.

    Renamed from ``CovariateShiftCRC`` (external review R3-01, 2026-07-25);
    the old name remains available as an alias.

    Parameters
    ----------
    target_risk:
        Target empirical error rate ``α`` for accepted items. Default 0.05.
    cal_fraction:
        Fraction of data used for calibration (remainder is test).
    off_distribution_weight:
        Heuristic weight ``β`` assigned to calibration items from a phase
        different from the target phase (default 0.10; hand-tuned, not a
        density ratio).
    seed:
        RNG seed for the calibration/test split.
    """

    target_risk: float = 0.05
    cal_fraction: float = 0.6
    off_distribution_weight: float = 0.10
    seed: int | None = 0

    _threshold: float = field(default=UNATTAINABLE_THRESHOLD, init=False)
    _fitted: bool = field(default=False, init=False)

    def fit(
        self,
        scores: Sequence[float],
        labels: Sequence[bool],
        phases: Sequence[str] | None = None,
        target_phase: str | None = None,
    ) -> CRCReport:
        """Fit the empirical threshold with optional phase-importance weighting.

        Parameters
        ----------
        scores:
            Per-item trust scores.
        labels:
            Per-item correctness flags.
        phases:
            Phase label for each item (``"ordered"``/``"critical"``/
            ``"disordered"``).  When combined with *target_phase*, items
            not matching *target_phase* receive weight
            ``off_distribution_weight``.
        target_phase:
            The phase at test time.  Items in *phases* matching this value
            receive weight 1.0; mismatching items receive
            ``self.off_distribution_weight``.

        Returns
        -------
        CRCReport
        """

        n = len(scores)
        if n != len(labels):
            raise ValueError("scores and labels must have equal length")
        if phases is not None and len(phases) != n:
            raise ValueError("phases must have the same length as scores")
        if not scores:
            self._threshold = UNATTAINABLE_THRESHOLD
            self._fitted = True
            return CRCReport(
                threshold=UNATTAINABLE_THRESHOLD,
                target_risk=self.target_risk,
                holdout_risk=None,
                holdout_coverage=0.0,
                n_calibration=0,
                n_test=0,
                total_weight=0.0,
                finite_sample_slack=1.0,
                nominal_risk_bound=self.target_risk + 1.0,
            )

        # Build per-item importance weights
        if phases is not None and target_phase is not None:
            weights_all = [
                1.0 if p == target_phase else self.off_distribution_weight
                for p in phases
            ]
        else:
            weights_all = [1.0] * n

        # Calibration/test split (preserves weight alignment)
        import random
        rng = random.Random(self.seed)
        idx = list(range(n))
        rng.shuffle(idx)
        cut = int(round(n * self.cal_fraction))
        cal_idx = idx[:cut]
        test_idx = idx[cut:]

        cal_scores = [scores[i] for i in cal_idx]
        cal_labels = [labels[i] for i in cal_idx]
        cal_weights = [weights_all[i] for i in cal_idx]
        test_scores = [scores[i] for i in test_idx]
        test_labels = [labels[i] for i in test_idx]

        self._threshold = weighted_conformal_threshold(
            cal_scores, cal_labels, cal_weights, target_risk=self.target_risk
        )
        self._fitted = True

        # Holdout evaluation. Plain (unweighted) empirical risk: test-set
        # importance weights are deliberately NOT applied here, and the
        # field name says so (external paper review 2026-07-24).
        holdout_coverage = coverage_at_threshold(test_scores, self._threshold)
        accepted = [(s, y) for s, y in zip(test_scores, test_labels) if s >= self._threshold]
        if accepted:
            wrong = sum(1 for _, y in accepted if not y)
            holdout_risk: float | None = wrong / len(accepted)
        else:
            holdout_risk = None

        n_cal = len(cal_scores)
        slack = 1.0 / (n_cal + 1)

        return CRCReport(
            threshold=self._threshold,
            target_risk=self.target_risk,
            holdout_risk=holdout_risk,
            holdout_coverage=holdout_coverage,
            n_calibration=n_cal,
            n_test=len(test_idx),
            total_weight=sum(cal_weights),
            finite_sample_slack=slack,
            # Nominal (not guaranteed): the phase-heuristic weights are not a
            # density ratio, so the Theorem-1 expected-risk guarantee does not
            # attach unless the caller supplies valid likelihood-ratio weights.
            nominal_risk_bound=self.target_risk + slack,
        )

    @property
    def threshold(self) -> float:
        """Calibrated threshold (post-fit)."""
        if not self._fitted:
            raise RuntimeError("WeightedEmpiricalSelectiveRouter must be fitted before use.")
        return self._threshold

    def route(self, score: float) -> bool:
        """Return True (ACCEPT) if *score* meets the calibrated threshold."""
        if not self._fitted:
            raise RuntimeError("WeightedEmpiricalSelectiveRouter must be fitted before use.")
        return float(score) >= self._threshold


# Backward-compatible alias: the historical name appears in committed
# artifacts, earlier paper versions, and downstream imports (R3-01 rename).
CovariateShiftCRC = WeightedEmpiricalSelectiveRouter


# ---------------------------------------------------------------------------
# Phase importance weighter (utility)
# ---------------------------------------------------------------------------


def phase_importance_weights(
    phases: Sequence[str],
    target_phase: str,
    off_weight: float = 0.10,
) -> list[float]:
    """Compute per-item importance weights for phase-shift CRC.

    Items in *target_phase* receive weight 1.0 (in-distribution).
    All other items receive *off_weight* (out-of-distribution).

    This is a conservative estimate of the true density ratio
    ``p_test(x) / p_cal(x)`` — conservative in the sense that it
    underweights cross-phase items, biasing the threshold toward caution.

    Parameters
    ----------
    phases:
        Phase label per item (``"ordered"`` / ``"critical"`` / ``"disordered"``).
    target_phase:
        The phase at test time.
    off_weight:
        Weight for items from phases other than *target_phase*.

    Returns
    -------
    list[float]
        Importance weights in the same order as *phases*.
    """
    return [1.0 if p == target_phase else off_weight for p in phases]


def crc_risk_bound(n_calibration: int, target_risk: float) -> float:
    """Return the formal CRC expected-risk upper bound for given calibration size.

    ``E[L(λ̂)] ≤ target_risk + 1 / (n_calibration + 1)``

    This is the finite-sample slack from Theorem 1 of Angelopoulos et al.
    (2022).  For ``n_calibration = 19``, the slack is 5 pp; for
    ``n_calibration = 99``, the slack is 1 pp.

    Parameters
    ----------
    n_calibration:
        Number of items in the calibration set.
    target_risk:
        Target risk ``α``.

    Returns
    -------
    float
        Expected risk upper bound.
    """
    return target_risk + 1.0 / (n_calibration + 1)
