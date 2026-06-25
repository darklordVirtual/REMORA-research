# Author: Stian Skogbrott
# License: Apache-2.0
"""Risk/coverage selective routing primitives.

The core idea is to sort by confidence and measure empirical risk as coverage
increases. This provides a stable control surface for accept/abstain decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


def risk_coverage_curve(scores: list[float], labels: list[bool]) -> list[dict]:
    """Return a monotonic coverage sweep with empirical risk.

    `scores` should represent confidence where higher is safer.
    `labels` should represent correctness (True=correct).
    """
    if len(scores) != len(labels):
        raise ValueError("scores and labels must have same length")
    n = len(scores)
    if n == 0:
        return []
    ranked = sorted(zip(scores, labels), key=lambda x: x[0], reverse=True)
    accepted = 0
    correct = 0
    out: list[dict] = []
    for score, is_correct in ranked:
        accepted += 1
        correct += 1 if is_correct else 0
        coverage = accepted / n
        accuracy = correct / accepted
        risk = 1.0 - accuracy
        out.append(
            {
                "threshold": float(score),
                "accepted": accepted,
                "coverage": coverage,
                "accuracy": accuracy,
                "risk": risk,
            }
        )
    return out


def threshold_for_target_risk(scores: list[float], labels: list[bool], target_risk: float) -> float:
    """Find the lowest threshold that satisfies empirical risk <= target_risk.

    If no threshold satisfies the target, return >1.0 to force abstention.
    """
    curve = risk_coverage_curve(scores, labels)
    eligible = [row for row in curve if row["risk"] <= target_risk]
    if not eligible:
        return 1.01
    return min(row["threshold"] for row in eligible)


class SelectiveAction(Enum):
    ACCEPT = "accept"
    VERIFY = "verify"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class RouteDecision:
    action: SelectiveAction
    threshold: float
    score: float
    target_risk: float
    reason: str


@dataclass
class SelectiveRouter:
    """Simple target-risk router for confidence scores in [0, 1]."""

    target_risk: float = 0.05
    threshold: float = 0.5
    verify_margin: float = 0.05

    def fit(self, calibration_scores: list[float], calibration_labels: list[bool]) -> float:
        self.threshold = threshold_for_target_risk(
            calibration_scores,
            calibration_labels,
            target_risk=self.target_risk,
        )
        return self.threshold

    def route(self, score: float) -> RouteDecision:
        s = float(score)
        if s >= self.threshold:
            return RouteDecision(
                action=SelectiveAction.ACCEPT,
                threshold=self.threshold,
                score=s,
                target_risk=self.target_risk,
                reason="Score above calibrated target-risk threshold.",
            )
        if s >= max(0.0, self.threshold - self.verify_margin):
            return RouteDecision(
                action=SelectiveAction.VERIFY,
                threshold=self.threshold,
                score=s,
                target_risk=self.target_risk,
                reason="Near threshold; requires verification.",
            )
        return RouteDecision(
            action=SelectiveAction.ABSTAIN,
            threshold=self.threshold,
            score=s,
            target_risk=self.target_risk,
            reason="Below threshold; abstain or escalate.",
        )
