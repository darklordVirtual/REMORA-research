# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Heuristic policy thresholds are named constants with fixed values (Grok 3.3/4.3).

The hand-tuned decision thresholds were promoted from inline magic numbers to
named module constants so their provenance (heuristic, not artifact-calibrated)
is explicit. This test pins each constant to its historical literal value, so
an accidental edit that would silently shift a safety threshold fails CI.
"""
from __future__ import annotations

from remora.policy import decision_engine as de


def test_heuristic_threshold_values_are_unchanged() -> None:
    assert de.ORDERED_HIGH_TRUST_MIN == 0.72
    assert de.EVIDENCE_CONFIDENCE_MIN == 0.7
    assert de.LOW_TRUST_ABSTAIN_MAX == 0.2
    assert de.MINIMAX_AMBIGUITY_WIDTH_MIN == 0.15
    assert de.ENV_CONFIDENCE_MIN == 0.80
    assert de.CLASSIFICATION_CONFIDENCE_MIN == 0.60
    assert de.MISSPECIFICATION_RISK_MAX == 0.60
    assert de.SESSION_CUMULATIVE_RISK_MAX == 0.80
    assert de.SESSION_ACTION_COUNT_MAX == 100
    assert de.POLICY_GENERALIZATION_RISK_MAX == 0.70
    assert de.SIMILAR_ACTION_FLOOD_MAX == 50


def test_calibrated_thresholds_are_injected_not_hardcoded() -> None:
    """Calibrated thresholds must remain constructor-injected (from artifacts),
    never module constants — so they cannot be mistaken for hand-tuned values."""
    eng = de.RemoraDecisionEngine()
    assert eng.temperature_threshold is None
    assert eng.conformal_trust_threshold is None
    assert eng.conformal_phase_thresholds is None
    # The heuristic block must not accidentally define a calibrated name.
    assert not hasattr(de, "TEMPERATURE_THRESHOLD")
    assert not hasattr(de, "CONFORMAL_TRUST_THRESHOLD")
