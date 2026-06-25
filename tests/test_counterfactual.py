# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for the canonical counterfactual module."""
from __future__ import annotations

from remora.counterfactual import (
    ClaimType,
    classify_claim,
    evaluate_causal_response,
    evaluate_invariance,
    generate_counterfactual,
)
from remora.core import Oracle


class MockOracle(Oracle):
    def __init__(self, response_text: str):
        self._resp = response_text

    @property
    def name(self) -> str:
        return "mock"

    def _call(self, prompt: str) -> tuple[str, float, float]:
        return (f'{{"counterfactual_question": "{self._resp}"}}', 0.0, 0.0)


def test_generate_counterfactual_from_canonical_module() -> None:
    oracle = MockOracle("If it rained, is the street dry?")
    result = generate_counterfactual("If it rained, is the street wet?", None, oracle)
    assert result == "If it rained, is the street dry?"


def test_canonical_module_exposes_both_policies() -> None:
    assert classify_claim("A triangle has three sides.") == ClaimType.DEFINITIONAL
    assert evaluate_causal_response(True, False) is True
    assert evaluate_invariance(ClaimType.CAUSAL, True, False) is True
