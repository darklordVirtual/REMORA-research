"""Tests for DomainClassifier and auto-classification in estimate_structural_temperature."""
from __future__ import annotations

import pytest

from remora.thermodynamics import DomainClassifier, estimate_structural_temperature


class TestDomainClassifier:
    def test_factoid_true_or_false(self) -> None:
        assert DomainClassifier.classify("True or false: the sky is blue?") == "factoid"

    def test_factoid_yes_or_no(self) -> None:
        assert DomainClassifier.classify("Yes or no: is water H2O?") == "factoid"

    def test_factoid_who_is(self) -> None:
        assert DomainClassifier.classify("Who is the CEO of Equinor?") == "factoid"

    def test_factoid_what_is(self) -> None:
        assert DomainClassifier.classify("What is the boiling point of water?") == "factoid"

    def test_factoid_when_did(self) -> None:
        assert DomainClassifier.classify("When did Norway discover oil?") == "factoid"

    def test_reasoning_calculate(self) -> None:
        assert DomainClassifier.classify("Calculate the net present value of this project.") == "reasoning"

    def test_reasoning_explain_why(self) -> None:
        assert DomainClassifier.classify("Explain why the pressure drops in the separator.") == "reasoning"

    def test_reasoning_step_by_step(self) -> None:
        assert DomainClassifier.classify("Solve this step by step: 3x + 7 = 22") == "reasoning"

    def test_reasoning_analyze(self) -> None:
        assert DomainClassifier.classify("Analyze the risk exposure of this portfolio.") == "reasoning"

    def test_reasoning_compare(self) -> None:
        assert DomainClassifier.classify("Compare the two contract structures.") == "reasoning"

    def test_creative_write_a(self) -> None:
        assert DomainClassifier.classify("Write a summary of the incident report.") == "creative"

    def test_creative_generate_a(self) -> None:
        assert DomainClassifier.classify("Generate a Python script for data ingestion.") == "creative"

    def test_creative_compose(self) -> None:
        assert DomainClassifier.classify("Compose an email to the client.") == "creative"

    def test_creative_imagine(self) -> None:
        assert DomainClassifier.classify("Imagine you are a safety officer.") == "creative"

    def test_creative_story(self) -> None:
        assert DomainClassifier.classify("Tell me a story about the offshore platform.") == "creative"

    def test_adversarial_everyone_knows(self) -> None:
        assert DomainClassifier.classify("Everyone knows that AI cannot be trusted.") == "adversarial"

    def test_adversarial_paradox(self) -> None:
        assert DomainClassifier.classify("This sentence is a paradox.") == "adversarial"

    def test_adversarial_you_are_wrong(self) -> None:
        assert DomainClassifier.classify("You're wrong about this interpretation.") == "adversarial"

    def test_adversarial_beats_creative(self) -> None:
        assert DomainClassifier.classify(
            "Write a paradox about infinite regress."
        ) == "adversarial"

    def test_adversarial_beats_reasoning(self) -> None:
        assert DomainClassifier.classify(
            "Prove that this statement is a contradiction."
        ) == "adversarial"

    def test_unknown_prompt_defaults_to_reasoning(self) -> None:
        assert DomainClassifier.classify("blaggity blaggity fnord") == "reasoning"

    def test_empty_string_defaults_to_reasoning(self) -> None:
        assert DomainClassifier.classify("") == "reasoning"

    def test_case_insensitive(self) -> None:
        assert DomainClassifier.classify("CALCULATE THE NPV") == "reasoning"


class TestEstimateStructuralTemperatureAutoClassify:
    def test_auto_classify_factoid_lower_temperature(self) -> None:
        factoid_T = estimate_structural_temperature("Is the sky blue? Yes or no.")
        reasoning_T = estimate_structural_temperature("Analyze the causal chain of this event.")
        assert factoid_T < reasoning_T

    def test_auto_classify_adversarial_highest_temperature(self) -> None:
        adversarial_T = estimate_structural_temperature("Everyone knows this is a paradox.")
        factoid_T = estimate_structural_temperature("Who is the Prime Minister of Norway?")
        assert adversarial_T > factoid_T

    def test_explicit_category_overrides_classifier(self) -> None:
        prompt = "Calculate the sum of 1 + 1."
        T_auto = estimate_structural_temperature(prompt)
        T_explicit_creative = estimate_structural_temperature(prompt, category="creative")
        assert T_explicit_creative > T_auto

    def test_temperature_in_valid_range(self) -> None:
        for prompt in [
            "Yes or no?",
            "Calculate x.",
            "Write a poem.",
            "Everyone knows AI is wrong.",
            "x" * 5000,
        ]:
            T = estimate_structural_temperature(prompt)
            assert 0.05 <= T <= 2.0, f"Out of range for: {prompt[:50]!r}"

    def test_empty_prompt_returns_prior(self) -> None:
        T = estimate_structural_temperature("")
        assert T == pytest.approx(0.85)

    def test_auto_classify_does_not_change_explicit_category_behaviour(self) -> None:
        T_with_category = estimate_structural_temperature("dummy", category="factoid")
        assert T_with_category == pytest.approx(
            estimate_structural_temperature("dummy", category="factoid")
        )
