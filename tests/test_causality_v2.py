# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for claim-type-aware counterfactual invariance."""
from __future__ import annotations

from remora.counterfactual import (
    ClaimType,
    classify_claim,
    expected_under_intervention,
    evaluate_invariance,
)


def test_classify_definitional_claim():
    assert classify_claim("A triangle has three sides.") == ClaimType.DEFINITIONAL


def test_classify_causal_claim():
    assert classify_claim("Smoking causes lung cancer.") == ClaimType.CAUSAL


def test_classify_observational_claim():
    assert classify_claim("Mount Everest is in Nepal.") == ClaimType.OBSERVATIONAL


def test_expected_under_intervention_causal_flips():
    expected = expected_under_intervention(ClaimType.CAUSAL, original_polarity=True)
    assert expected == "flip"


def test_expected_under_intervention_definitional_invariant():
    expected = expected_under_intervention(ClaimType.DEFINITIONAL, original_polarity=True)
    assert expected == "invariant"


def test_evaluate_invariance_causal_pass_on_flip():
    # Causal claim should flip polarity under do(~X).
    assert evaluate_invariance(
        claim_type=ClaimType.CAUSAL,
        original_polarity=True,
        counterfactual_polarity=False,
    ) is True


def test_evaluate_invariance_causal_fail_on_no_flip():
    assert evaluate_invariance(
        claim_type=ClaimType.CAUSAL,
        original_polarity=True,
        counterfactual_polarity=True,
    ) is False


def test_evaluate_invariance_definitional_pass_when_unchanged():
    assert evaluate_invariance(
        claim_type=ClaimType.DEFINITIONAL,
        original_polarity=True,
        counterfactual_polarity=True,
    ) is True


def test_evaluate_invariance_definitional_fail_when_flipped():
    assert evaluate_invariance(
        claim_type=ClaimType.DEFINITIONAL,
        original_polarity=True,
        counterfactual_polarity=False,
    ) is False


def test_classify_statistical_claim():
    assert classify_claim("70% of cases respond to treatment.") == ClaimType.STATISTICAL


def test_classify_unknown_claim():
    # Imperative sentence with no matching patterns
    assert classify_claim("Run the experiment tomorrow.") == ClaimType.UNKNOWN


def test_evaluate_invariance_none_polarity_returns_true():
    assert evaluate_invariance(ClaimType.CAUSAL, None, None) is True


def test_evaluate_invariance_statistical_always_passes():
    assert evaluate_invariance(ClaimType.STATISTICAL, True, True) is True
    assert evaluate_invariance(ClaimType.STATISTICAL, True, False) is True
