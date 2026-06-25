# Author: Stian Skogbrott
# License: Apache-2.0
"""Platt scaling calibration for verbalized confidence scores.

Maps raw verbalized confidence (poorly calibrated) to calibrated P(correct)
using a sigmoid fit: p_cal = sigmoid(a * p_raw + b).

Fitting is via gradient descent on binary cross-entropy.  For production use,
fit on a held-out split of your benchmark; the default identity (a=1, b=0)
passes raw confidence through unchanged.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PlattCalibrator:
    """Sigmoid (Platt) calibration for scalar confidence scores.

    The calibration function is: p_cal = 1 / (1 + exp(a * p_raw + b))
    After fitting, *lower* raw scores map to lower p_cal (monotone by design
    as long as a < 0 — the default a=−4 satisfies this; setting a > 0 would
    invert the mapping).

    Default a=−4, b=2 is a mild compression that moves extreme raw scores
    (0.0 and 1.0) off the boundaries — better than the identity for overconfident
    verbalized outputs from LLMs.
    """

    a: float = -4.0
    b: float = 2.0
    is_fitted: bool = False

    def calibrate(self, raw: float) -> float:
        """Map raw confidence to calibrated probability."""
        return 1.0 / (1.0 + math.exp(self.a * max(0.0, min(1.0, raw)) + self.b))

    def fit(
        self,
        raw_scores: list[float],
        labels: list[int],
        lr: float = 0.05,
        steps: int = 500,
    ) -> None:
        """Fit via gradient descent on binary cross-entropy.

        Args:
            raw_scores: verbalized confidence values in [0, 1].
            labels:     ground-truth correctness (1 = correct, 0 = wrong).
            lr:         learning rate.
            steps:      gradient descent iterations.
        """
        if not raw_scores or len(raw_scores) != len(labels):
            return
        a, b = self.a, self.b
        n = len(raw_scores)
        for _ in range(steps):
            da = db = 0.0
            for x, y in zip(raw_scores, labels):
                x = max(0.0, min(1.0, x))
                p = 1.0 / (1.0 + math.exp(a * x + b))
                err = p - y
                # sigmoid form is 1/(1+exp(ax+b)), so ∂L/∂a = (y-p)*x
                da -= err * x
                db -= err
            a -= lr * da / n
            b -= lr * db / n
        self.a = a
        self.b = b
        self.is_fitted = True

    def expected_calibration_error(
        self,
        raw_scores: list[float],
        labels: list[int],
        n_bins: int = 10,
    ) -> float:
        """Compute ECE over equal-width bins on the calibrated scores."""
        if not raw_scores:
            return float("nan")
        total = len(raw_scores)
        bin_width = 1.0 / n_bins
        ece = 0.0
        for b_idx in range(n_bins):
            lo = b_idx * bin_width
            hi = lo + bin_width
            indices = [i for i, r in enumerate(raw_scores) if lo <= self.calibrate(r) < hi]
            if not indices:
                continue
            frac_correct = sum(labels[i] for i in indices) / len(indices)
            mean_conf = sum(self.calibrate(raw_scores[i]) for i in indices) / len(indices)
            ece += (len(indices) / total) * abs(mean_conf - frac_correct)
        return ece

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({"a": self.a, "b": self.b, "is_fitted": self.is_fitted}))

    @classmethod
    def load(cls, path: str | Path) -> "PlattCalibrator":
        data = json.loads(Path(path).read_text())
        return cls(a=data["a"], b=data["b"], is_fitted=data.get("is_fitted", True))
