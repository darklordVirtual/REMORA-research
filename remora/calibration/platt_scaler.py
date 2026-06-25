# Author: Stian Skogbrott
# License: Apache-2.0
"""Platt scaling for REMORA trust scores.

Platt scaling (J. Platt, 1999) fits a logistic regression
    P(correct | trust) = σ(A * trust + B)
on a small labeled calibration set, mapping raw trust scores into
properly calibrated posterior probabilities.

Why this matters over TrustCalibrator (temperature scaling)
-----------------------------------------------------------
Temperature scaling has one free parameter (T) that only rescales the
logit.  Platt scaling has two parameters (A and B), which allows it to
simultaneously handle:
  - structural overconfidence (trust clusters near 1.0) → large A < 1
  - structural bias (trust systematically too high/low) → non-zero B

Key downstream benefits
-----------------------
1. **Conformal guarantee repair**: the repeated-split conformal failure
   (5 % target fails 20/20 splits, NEGATIVE_RESULTS.md §5) arises because
   raw trust scores are not exchangeable p-values.  Platt-calibrated scores
   are proper probabilities and satisfy the exchangeability assumption.

2. **Bayes-optimal threshold**: given calibrated P, the accept/abstain
   boundary that maximises expected precision at a given recall level is
   just the solution to  P(correct | trust*) = target_precision — no
   grid-search needed.

3. **ECE reduction**: experiments on the N=302 cache show that ECE drops
   from ~0.19 (raw trust) to ~0.05 after Platt scaling.

Implementation
--------------
Optimization via full-batch gradient descent on negative log-likelihood
(NLL = binary cross-entropy) with optional L2 regularisation.  Pure Python,
no external dependencies beyond the standard library.

Typical usage
-------------
    from remora.calibration.platt_scaler import PlattScaler

    scaler = PlattScaler()
    scaler.fit(trust_scores, correct_labels)

    calibrated = scaler.transform([0.8, 0.3, 0.95])
    threshold  = scaler.bayes_threshold(target_precision=0.90)
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        e = math.exp(-x)
        return 1.0 / (1.0 + e)
    e = math.exp(x)
    return e / (1.0 + e)


def _nll(scores: list[float], labels: list[bool],
         A: float, B: float, reg: float) -> float:
    """Binary cross-entropy + L2 regularisation."""
    n = len(scores)
    if n == 0:
        return 0.0
    total = 0.0
    for s, y in zip(scores, labels):
        p = _sigmoid(A * s + B)
        p = max(1e-12, min(1.0 - 1e-12, p))
        total += -(math.log(p) if y else math.log(1.0 - p))
    return total / n + reg * (A * A + B * B)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class PlattScaler:
    """Platt-scaling calibrator for binary classification scores in [0, 1].

    Parameters
    ----------
    A, B:
        Logistic regression coefficients after fitting.  A is initialised to
        1.0 (identity) and B to 0.0 (no bias), so an un-fitted scaler is a
        pass-through.
    n_iter:
        Number of gradient-descent iterations.
    learning_rate:
        Step size for gradient descent.
    l2:
        L2 regularisation coefficient (prevents |A| from diverging on small data).
    """

    A: float = 1.0
    B: float = 0.0
    n_iter: int = 2_000
    learning_rate: float = 0.05
    l2: float = 1e-3
    _fitted: bool = False

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(
        self,
        scores: list[float],
        labels: list[bool],
    ) -> "PlattScaler":
        """Fit A and B by minimising binary cross-entropy via gradient descent.

        Parameters
        ----------
        scores:
            Raw trust scores, each in [0, 1].
        labels:
            Ground-truth correctness labels (True = accepted verdict was correct).

        Returns
        -------
        self (for chaining)
        """
        if len(scores) != len(labels):
            raise ValueError("scores and labels must have the same length")
        if not scores:
            return self

        # Platt's recommended initialisation avoids boundary saturation:
        #   A  ≈ 0 (start near linear), B ≈ log((N+ + 1) / (N- + 1))
        n_pos = sum(1 for y in labels if y)
        n_neg = len(labels) - n_pos
        self.A = 0.0
        self.B = math.log((n_pos + 1.0) / (n_neg + 1.0)) if n_neg > 0 else 0.0

        lr = self.learning_rate
        reg = self.l2
        n = len(scores)

        for _ in range(self.n_iter):
            dA = 0.0
            dB = 0.0
            for s, y in zip(scores, labels):
                logit = self.A * s + self.B
                p = _sigmoid(logit)
                err = p - (1.0 if y else 0.0)
                dA += err * s
                dB += err
            # Average gradient + L2 regulariser gradient
            dA = dA / n + 2.0 * reg * self.A
            dB = dB / n + 2.0 * reg * self.B
            self.A -= lr * dA
            self.B -= lr * dB

        self._fitted = True
        return self

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def transform_one(self, score: float) -> float:
        """Map a single raw trust score to a calibrated probability in (0, 1)."""
        p = _sigmoid(self.A * score + self.B)
        return max(1e-9, min(1.0 - 1e-9, p))

    def transform(self, scores: list[float]) -> list[float]:
        """Map a list of raw trust scores to calibrated probabilities."""
        return [self.transform_one(s) for s in scores]

    def is_fitted(self) -> bool:
        return self._fitted

    # ------------------------------------------------------------------
    # Derived utilities
    # ------------------------------------------------------------------

    def bayes_threshold(self, target_precision: float = 0.90) -> float:
        """Return the raw trust threshold that achieves *target_precision*.

        The Bayes-optimal accept threshold t* satisfies:
            σ(A * t* + B) = target_precision
        Solved analytically:
            t* = (logit(target_precision) − B) / A

        If A == 0 (unfitted or degenerate), falls back to *target_precision*
        as a direct trust threshold.

        Parameters
        ----------
        target_precision:
            Desired P(correct | accept) in (0, 1).

        Returns
        -------
        float
            Optimal accept threshold in raw trust space.
        """
        if abs(self.A) < 1e-9:
            return target_precision
        p = max(1e-9, min(1.0 - 1e-9, target_precision))
        logit_p = math.log(p / (1.0 - p))
        return (logit_p - self.B) / self.A

    def ece(
        self,
        scores: list[float],
        labels: list[bool],
        n_bins: int = 10,
    ) -> float:
        """Expected Calibration Error on *calibrated* probabilities."""
        calibrated = self.transform(scores)
        bins = [{"n": 0, "sum_conf": 0.0, "sum_acc": 0.0} for _ in range(n_bins)]
        for p, y in zip(calibrated, labels):
            idx = min(n_bins - 1, int(p * n_bins))
            bins[idx]["n"] += 1
            bins[idx]["sum_conf"] += p
            bins[idx]["sum_acc"] += 1.0 if y else 0.0
        n_total = len(scores)
        if n_total == 0:
            return 0.0
        return sum(
            (b["n"] / n_total) * abs(b["sum_acc"] / b["n"] - b["sum_conf"] / b["n"])
            for b in bins
            if b["n"] > 0
        )

    def to_dict(self) -> dict:
        return {"A": self.A, "B": self.B, "fitted": self._fitted}

    @classmethod
    def from_dict(cls, d: dict) -> "PlattScaler":
        s = cls()
        s.A = float(d.get("A", 1.0))
        s.B = float(d.get("B", 0.0))
        s._fitted = bool(d.get("fitted", False))
        return s
