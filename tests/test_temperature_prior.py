"""Tests for estimate_temperature_prior() in remora.thermodynamics."""
from __future__ import annotations

import inspect

import pytest

from remora.thermodynamics import estimate_temperature_prior


class TestEstimateTemperaturePriorReturnRange:
    def test_empty_prompt_returns_uninformative_prior(self) -> None:
        result = estimate_temperature_prior("")
        assert result == pytest.approx(0.50)

    def test_result_at_least_minimum(self) -> None:
        result = estimate_temperature_prior("x")
        assert result >= 0.05

    def test_result_at_most_maximum(self) -> None:
        # Very long string hits density/length ceiling — must stay ≤ 2.0
        result = estimate_temperature_prior("x" * 100_000)
        assert result <= 2.0

    def test_returns_float(self) -> None:
        assert isinstance(estimate_temperature_prior("hello"), float)

    def test_bounded_for_short_prompt(self) -> None:
        result = estimate_temperature_prior("yes")
        assert 0.05 <= result <= 2.0

    def test_bounded_for_long_diverse_prompt(self) -> None:
        prompt = "".join(chr(65 + i % 26) for i in range(500))
        result = estimate_temperature_prior(prompt)
        assert 0.05 <= result <= 2.0


class TestEstimateTemperaturePriorStructuralSignals:
    def test_high_density_raises_temperature(self) -> None:
        # Two prompts of equal length: one highly compressible, one information-dense.
        # Same length → length_factor is identical → density alone drives the difference.
        compressible = "a" * 200
        diverse = "".join(chr(33 + i % 90) for i in range(200))  # 90 distinct printable chars
        t_comp = estimate_temperature_prior(compressible)
        t_dense = estimate_temperature_prior(diverse)
        assert t_dense > t_comp

    def test_very_long_prompt_within_bounds(self) -> None:
        long_prompt = "explain the thermodynamic implications of entropy " * 100
        result = estimate_temperature_prior(long_prompt)
        assert 0.05 <= result <= 2.0

    def test_single_char_within_bounds(self) -> None:
        assert 0.05 <= estimate_temperature_prior("?") <= 2.0


class TestEstimateTemperaturePriorIndependenceFromD:
    def test_accepts_only_prompt_argument(self) -> None:
        sig = inspect.signature(estimate_temperature_prior)
        assert list(sig.parameters.keys()) == ["prompt"]

    def test_deterministic(self) -> None:
        prompt = "Is §9-6 of the HSE Act applicable to this installation?"
        assert estimate_temperature_prior(prompt) == estimate_temperature_prior(prompt)

    def test_different_prompts_give_different_results(self) -> None:
        t1 = estimate_temperature_prior("a" * 200)
        t2 = estimate_temperature_prior("".join(chr(33 + i % 90) for i in range(200)))
        assert t1 != t2
