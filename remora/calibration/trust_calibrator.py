# Author: Stian Skogbrott
# License: Apache-2.0
"""Trust-score calibration utilities.

This module provides:

- core calibration metrics (Brier, log loss, ECE),
- reliability curve bins,
- a lightweight temperature-scaling calibrator for trust scores.

The calibrator is intentionally dependency-free and deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


def _clip_prob(p: float, eps: float = 1e-9) -> float:
    return min(1.0 - eps, max(eps, float(p)))


def brier_score(probabilities: list[float], labels: list[bool]) -> float:
    if len(probabilities) != len(labels):
        raise ValueError("probabilities and labels must have same length")
    if not probabilities:
        return 0.0
    return sum((float(p) - (1.0 if y else 0.0)) ** 2 for p, y in zip(probabilities, labels)) / len(probabilities)


def log_loss(probabilities: list[float], labels: list[bool], eps: float = 1e-9) -> float:
    if len(probabilities) != len(labels):
        raise ValueError("probabilities and labels must have same length")
    if not probabilities:
        return 0.0
    total = 0.0
    for p, y in zip(probabilities, labels):
        q = _clip_prob(p, eps)
        total += -math.log(q) if y else -math.log(1.0 - q)
    return total / len(probabilities)


def reliability_curve(probabilities: list[float], labels: list[bool], n_bins: int = 10) -> list[dict]:
    if len(probabilities) != len(labels):
        raise ValueError("probabilities and labels must have same length")
    if n_bins <= 0:
        raise ValueError("n_bins must be positive")
    bins = [{"count": 0, "sum_conf": 0.0, "sum_acc": 0.0} for _ in range(n_bins)]
    for p, y in zip(probabilities, labels):
        q = max(0.0, min(1.0, float(p)))
        idx = min(n_bins - 1, int(q * n_bins))
        bins[idx]["count"] += 1
        bins[idx]["sum_conf"] += q
        bins[idx]["sum_acc"] += 1.0 if y else 0.0
    out = []
    for i, bucket in enumerate(bins):
        count = bucket["count"]
        conf = (bucket["sum_conf"] / count) if count else 0.0
        acc = (bucket["sum_acc"] / count) if count else 0.0
        out.append(
            {
                "bin": i,
                "start": i / n_bins,
                "end": (i + 1) / n_bins,
                "count": count,
                "mean_confidence": conf,
                "empirical_accuracy": acc,
                "gap": abs(acc - conf),
            }
        )
    return out


def expected_calibration_error(probabilities: list[float], labels: list[bool], n_bins: int = 10) -> float:
    curve = reliability_curve(probabilities, labels, n_bins=n_bins)
    n = len(probabilities)
    if n == 0:
        return 0.0
    return sum((bucket["count"] / n) * bucket["gap"] for bucket in curve)


def _logit(p: float) -> float:
    q = _clip_prob(p)
    return math.log(q / (1.0 - q))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def apply_temperature_scaling(probabilities: list[float], temperature: float) -> list[float]:
    t = max(float(temperature), 1e-6)
    return [_sigmoid(_logit(p) / t) for p in probabilities]


@dataclass(frozen=True)
class CalibrationMetrics:
    brier: float
    nll: float
    ece: float


@dataclass
class TrustCalibrator:
    """Temperature-scaling calibrator for trust scores in [0, 1]."""

    temperature: float = 1.0
    n_bins: int = 10

    def fit(
        self,
        probabilities: list[float],
        labels: list[bool],
        t_min: float = 0.25,
        t_max: float = 8.0,
        t_steps: int = 200,
        boundary_tolerance: float = 0.02,
    ) -> float:
        if len(probabilities) != len(labels):
            raise ValueError("probabilities and labels must have same length")
        if not probabilities:
            self.temperature = 1.0
            return self.temperature
        best_t = 1.0
        best_loss = float("inf")
        for i in range(t_steps + 1):
            t = t_min + (t_max - t_min) * (i / max(1, t_steps))
            scaled = apply_temperature_scaling(probabilities, t)
            loss = log_loss(scaled, labels)
            if loss < best_loss:
                best_loss = loss
                best_t = t
        self.temperature = best_t
        # Warn when the best temperature is within boundary_tolerance of the
        # search ceiling — this indicates structural overconfidence in the raw
        # scores and the caller should extend t_max or inspect score distribution.
        if (t_max - best_t) / t_max < boundary_tolerance:
            import warnings
            warnings.warn(
                f"TrustCalibrator: best_t={best_t:.3f} is at the t_max={t_max:.1f} "
                "ceiling. Trust scores may be bimodal or structurally overconfident. "
                "Consider extending t_max or inspecting raw score distribution.",
                stacklevel=2,
            )
        return self.temperature

    def calibrate(self, probabilities: list[float]) -> list[float]:
        return apply_temperature_scaling(probabilities, self.temperature)

    def evaluate(self, probabilities: list[float], labels: list[bool]) -> CalibrationMetrics:
        calibrated = self.calibrate(probabilities)
        return CalibrationMetrics(
            brier=brier_score(calibrated, labels),
            nll=log_loss(calibrated, labels),
            ece=expected_calibration_error(calibrated, labels, n_bins=self.n_bins),
        )
