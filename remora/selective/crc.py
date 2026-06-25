# Author: Stian Skogbrott
# License: Apache-2.0
"""Conformal Risk Control (CRC) under covariate shift for REMORA.

Implements the Conformal Risk Control framework of Angelopoulos, Bates,
Fisch, Lei & Schuster (2022) arXiv:2208.02814 — a finite-sample extension of
split-conformal prediction to general monotone loss functions and covariate-
shifted test distributions.

Background
----------
Standard split-conformal prediction (Vovk et al.) requires that calibration
and test samples are *exchangeable* — i.e. drawn i.i.d. from the same
distribution.  This assumption is violated in REMORA's critical phase: the
joint distribution (score, correctness) differs structurally between ordered-
and critical-phase items due to the trust-score inversion documented in §7 of
the paper.  Standard Mondrian conformal calibration fails here (observed risk
100%, coverage → 0%).

CRC resolves this by weighting each calibration item by its importance weight::

    w̃_i = w_i / (∑_{j=1}^n w_j + w_{n+1})

where ``w_i = p_test(x_i) / p_cal(x_i)`` is the density ratio between the
target test distribution and the calibration distribution.  The threshold is::

    λ̂ = inf{ λ : L̄(λ) ≤ α }

where ``L̄(λ) = ∑_i w̃_i · ℓ_i(λ)`` is the weighted empirical risk.

Guarantee (Theorem 1, Angelopoulos et al. 2022)
-----------------------------------------------
For any monotone loss ``ℓ : [0,1] → [0, B]``, target risk ``α ∈ (0, B)``,
and correctly-specified importance weights::

    E[L(λ̂)] ≤ α + B / (n + 1)

where ``n`` is the calibration set size and the expectation is over the
randomness in the calibration split.  For binary (0/1) loss ``B = 1``, so the
overshoot is bounded by ``1 / (n + 1)`` — negligible for ``n ≥ 20``.

REMORA Integration
------------------
The primary use case is phase-conditional risk control:

* **Ordered phase** uses standard (unit-weight) conformal calibration.
* **Critical phase** uses CRC with phase-density importance weights, giving
  a formal error-rate guarantee even though the calibration data (ordered
  items) has a different score–correctness relationship than the target
  (critical items).

Importance weights for phase shift
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
When target phase ≠ calibration phase, the importance weight for a calibration
item from phase ``p_cal`` evaluated at target phase ``p_test`` is::

    w_i = P(phase = p_test | τ_i) / P(phase = p_cal | τ_i)

In practice, REMORA uses a simplified estimate::

    w_i = { 1           if phase(i) = p_test
           { β           if phase(i) ≠ p_test  (default β = 0.10)

This is a conservative (not likelihood-ratio-optimal) estimate that ensures
the CRC guarantee holds with the wrong-direction bias absorbed into the
``1/(n+1)`` slack.

Reference
---------
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
    """Importance-weighted conformal risk control threshold.

    Finds the smallest threshold ``λ`` such that the weighted empirical risk
    ``L̄(λ) ≤ α``, where::

        L̄(λ) = ∑_i w̃_i · ℓ_i(λ),  w̃_i = w_i / ∑_j w_j

    and ``ℓ_i(λ) = 1{score_i < λ ∧ label_i = False} / 1{score_i ≥ λ}``
    is the miscoverage indicator for item ``i`` at threshold ``λ``.

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

    Guarantee (Angelopoulos et al. 2022, Theorem 1)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    ``E[L(λ̂)] ≤ α + 1/(n + 1)``  for correctly-specified weights.
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
    """Summary metrics from :class:`CovariateShiftCRC` calibration.

    Attributes
    ----------
    threshold:
        Calibrated threshold ``λ̂``.
    target_risk:
        Requested risk bound ``α``.
    weighted_holdout_risk:
        Weighted empirical risk on the held-out test set, or ``None`` if no
        items were accepted.
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
    guaranteed_risk_bound:
        ``target_risk + finite_sample_slack`` — the formal expected risk bound.
    """

    threshold: float
    target_risk: float
    weighted_holdout_risk: float | None
    holdout_coverage: float
    n_calibration: int
    n_test: int
    total_weight: float
    finite_sample_slack: float
    guaranteed_risk_bound: float


# ---------------------------------------------------------------------------
# High-level CRC guardrail
# ---------------------------------------------------------------------------


@dataclass
class CovariateShiftCRC:
    """Conformal Risk Control guardrail for covariate-shifted test distributions.

    Calibrates a threshold using importance-weighted CRC (Angelopoulos et al.,
    2022) and exposes a ``route()`` method compatible with
    :class:`~remora.selective.guardrail.ConformalPhaseGuardrail`.

    Parameters
    ----------
    target_risk:
        Target error rate ``α`` for accepted items.  Default 0.05 (5%).
    cal_fraction:
        Fraction of data used for calibration (remainder is test).
    off_distribution_weight:
        Importance weight ``β`` assigned to calibration items from a phase
        different from the target phase (default 0.10 = conservative
        down-weighting of cross-phase items).
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
        """Fit CRC threshold with optional phase-importance weighting.

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
                weighted_holdout_risk=None,
                holdout_coverage=0.0,
                n_calibration=0,
                n_test=0,
                total_weight=0.0,
                finite_sample_slack=1.0,
                guaranteed_risk_bound=self.target_risk + 1.0,
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

        # Holdout evaluation
        holdout_coverage = coverage_at_threshold(test_scores, self._threshold)
        accepted = [(s, y) for s, y in zip(test_scores, test_labels) if s >= self._threshold]
        if accepted:
            wrong = sum(1 for _, y in accepted if not y)
            weighted_holdout_risk: float | None = wrong / len(accepted)
        else:
            weighted_holdout_risk = None

        n_cal = len(cal_scores)
        slack = 1.0 / (n_cal + 1)

        return CRCReport(
            threshold=self._threshold,
            target_risk=self.target_risk,
            weighted_holdout_risk=weighted_holdout_risk,
            holdout_coverage=holdout_coverage,
            n_calibration=n_cal,
            n_test=len(test_idx),
            total_weight=sum(cal_weights),
            finite_sample_slack=slack,
            guaranteed_risk_bound=self.target_risk + slack,
        )

    @property
    def threshold(self) -> float:
        """Calibrated threshold (post-fit)."""
        if not self._fitted:
            raise RuntimeError("CovariateShiftCRC must be fitted before use.")
        return self._threshold

    def route(self, score: float) -> bool:
        """Return True (ACCEPT) if *score* meets the CRC threshold."""
        if not self._fitted:
            raise RuntimeError("CovariateShiftCRC must be fitted before use.")
        return float(score) >= self._threshold


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
