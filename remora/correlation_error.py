# Author: Stian Skogbrott
# License: Apache-2.0
"""Separation helpers for response correlation and error correlation.

REMORA historically used response agreement as an observable proxy. This module
makes the distinction explicit:

- rho_response: agreement in model outputs.
- rho_error: correlation of error indicators against labeled truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


def response_agreement_rate(predictions_a: Sequence[object], predictions_b: Sequence[object]) -> float:
    """Return simple output agreement in [0, 1]."""
    if len(predictions_a) != len(predictions_b):
        raise ValueError("predictions_a and predictions_b must have same length")
    n = len(predictions_a)
    if n == 0:
        return 0.0
    agree = sum(1 for a, b in zip(predictions_a, predictions_b) if a == b)
    return agree / n


def error_indicators(predictions: list[bool], labels: list[bool]) -> list[int]:
    """Map predictions to binary error indicators (1=wrong, 0=correct)."""
    if len(predictions) != len(labels):
        raise ValueError("predictions and labels must have same length")
    return [0 if pred == label else 1 for pred, label in zip(predictions, labels)]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def binary_error_correlation(errors_a: list[int], errors_b: list[int]) -> float:
    """Return Pearson correlation for two binary error series.

    If one series has zero variance, correlation is undefined. This function
    returns 0.0 in that case to keep downstream logic stable.
    """
    if len(errors_a) != len(errors_b):
        raise ValueError("errors_a and errors_b must have same length")
    n = len(errors_a)
    if n == 0:
        return 0.0

    xa = [float(v) for v in errors_a]
    xb = [float(v) for v in errors_b]
    ma = _mean(xa)
    mb = _mean(xb)
    va = _mean([(v - ma) ** 2 for v in xa])
    vb = _mean([(v - mb) ** 2 for v in xb])
    if va <= 1e-12 or vb <= 1e-12:
        return 0.0
    cov = _mean([(a - ma) * (b - mb) for a, b in zip(xa, xb)])
    return cov / ((va ** 0.5) * (vb ** 0.5))


def error_correlation_from_predictions(
    predictions_a: list[bool],
    predictions_b: list[bool],
    labels: list[bool],
) -> float:
    """Compute error-correlation directly from prediction streams and labels."""
    ea = error_indicators(predictions_a, labels)
    eb = error_indicators(predictions_b, labels)
    return binary_error_correlation(ea, eb)


@dataclass(frozen=True)
class CorrelationSeparationReport:
    """Small report object for diagnostics and tests."""

    rho_response: float
    rho_error: float
    n: int


def correlation_separation_report(
    predictions_a: list[bool],
    predictions_b: list[bool],
    labels: list[bool],
) -> CorrelationSeparationReport:
    """Return side-by-side response and error correlation estimates."""
    if not (len(predictions_a) == len(predictions_b) == len(labels)):
        raise ValueError("predictions and labels must have same length")
    return CorrelationSeparationReport(
        rho_response=response_agreement_rate(predictions_a, predictions_b),
        rho_error=error_correlation_from_predictions(predictions_a, predictions_b, labels),
        n=len(labels),
    )
