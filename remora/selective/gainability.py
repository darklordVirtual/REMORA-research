# Author: Stian Skogbrott
# License: Apache-2.0
"""GainabilityClassifier — predict when REMORA can recover from a wrong majority.

Inputs: REMORA observables (trust_score, order_parameter, susceptibility,
hallucination_bound, dissensus, rho_response_agreement, phase).
Target: majority_wrong AND some-alternative-branch_right.

Implementation: stdlib-only logistic regression via gradient descent on the
binary cross-entropy loss with L2 regularisation. Deterministic given a seed.

Feature ordering is fixed and load-bearing — a future P7 integration relies on
the exact field order. Do not reorder without updating the consumers.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Sequence


_PHASES = ("ordered", "critical", "disordered")


def extract_features(item: dict) -> list[float]:
    """Map a REMORA per-item observation into a fixed-length feature vector.

    Order (load-bearing): trust_score, order_parameter, susceptibility,
    hallucination_bound, dissensus, rho_response_agreement, phase_ordered,
    phase_critical, phase_disordered.
    """
    def f(key: str, default: float = 0.0) -> float:
        try:
            return float(item.get(key, default))
        except (TypeError, ValueError):
            return default

    base = [
        f("trust_score"),
        f("order_parameter"),
        f("susceptibility"),
        f("hallucination_bound"),
        f("dissensus"),
        f("rho_response_agreement"),
    ]
    phase = str(item.get("phase", "")).lower()
    one_hot = [1.0 if phase == p else 0.0 for p in _PHASES]
    return base + one_hot


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


@dataclass
class GainabilityClassifier:
    """Stdlib-only L2-regularised logistic regression."""

    lr: float = 0.1
    epochs: int = 500
    l2: float = 1e-3
    seed: int = 0
    weights: list[float] = field(default_factory=list)
    bias: float = 0.0

    def _init_weights(self, d: int) -> None:
        rng = random.Random(self.seed)
        self.weights = [rng.gauss(0.0, 0.01) for _ in range(d)]
        self.bias = 0.0

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[bool]) -> None:
        if len(X) != len(y):
            raise ValueError("X and y must have same length")
        if not X:
            raise ValueError("cannot fit on empty data")
        d = len(X[0])
        self._init_weights(d)
        n = len(X)
        for _ in range(self.epochs):
            grad_w = [0.0] * d
            grad_b = 0.0
            for xi, yi in zip(X, y):
                logit = self.bias + sum(w * x for w, x in zip(self.weights, xi))
                p = _sigmoid(logit)
                error = p - (1.0 if yi else 0.0)
                for j in range(d):
                    grad_w[j] += error * xi[j]
                grad_b += error
            for j in range(d):
                grad_w[j] = grad_w[j] / n + self.l2 * self.weights[j]
                self.weights[j] -= self.lr * grad_w[j]
            self.bias -= self.lr * (grad_b / n)

    def predict_proba(self, x: Sequence[float]) -> float:
        if not self.weights:
            raise RuntimeError("classifier not fit")
        logit = self.bias + sum(w * xi for w, xi in zip(self.weights, x))
        return _sigmoid(logit)
