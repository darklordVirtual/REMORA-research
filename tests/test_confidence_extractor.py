"""Tests for remora.confidence.extractor — verbalized confidence extraction."""
import pytest
from remora.confidence.extractor import extract_confidence, extract_confidence_from_json


class TestExtractConfidence:
    def test_explicit_percentage_before_keyword(self):
        assert extract_confidence("I am 85% confident this is correct.") == pytest.approx(0.85)

    def test_explicit_percentage_after_keyword(self):
        assert extract_confidence("I'm confident, about 90% sure.") == pytest.approx(0.90)

    def test_json_field_in_text(self):
        text = '{"answer": "yes", "confidence": 0.92, "reasoning": "clear"}'
        assert extract_confidence(text) == pytest.approx(0.92)

    def test_json_field_as_percentage_in_text(self):
        text = '"confidence": 87'
        result = extract_confidence(text)
        assert result == pytest.approx(0.87)

    def test_decimal_field(self):
        assert extract_confidence("confidence: 0.78") == pytest.approx(0.78)
        assert extract_confidence("Confidence = 0.55") == pytest.approx(0.55)

    def test_probability_field(self):
        assert extract_confidence("P(correct) = 0.95") == pytest.approx(0.95)

    def test_hedging_definitely(self):
        result = extract_confidence("Definitely, the answer is Paris.")
        assert result is not None
        assert result >= 0.80

    def test_hedging_not_sure(self):
        result = extract_confidence("I'm not sure, but I think it might be true.")
        assert result is not None
        assert result <= 0.50

    def test_hedging_no_idea(self):
        result = extract_confidence("I have no idea what the answer is.")
        assert result is not None
        assert result <= 0.30

    def test_hedging_confident(self):
        result = extract_confidence("I am confident the capital is Paris.")
        assert result is not None
        assert 0.65 <= result <= 0.90

    def test_empty_string_returns_none(self):
        assert extract_confidence("") is None

    def test_no_signal_returns_none(self):
        assert extract_confidence("The sky is blue.") is None

    def test_clamps_to_one(self):
        assert extract_confidence("I am 110% confident.") == pytest.approx(1.0)

    def test_negative_confidence_in_text_returns_none(self):
        # Negative values in raw text cannot be parsed as confidence (regex only matches digits).
        assert extract_confidence('"confidence": -0.1') is None


class TestExtractConfidenceFromJson:
    def test_decimal_confidence(self):
        assert extract_confidence_from_json({"confidence": 0.85}) == pytest.approx(0.85)

    def test_percentage_as_integer(self):
        assert extract_confidence_from_json({"confidence": 85}) == pytest.approx(0.85)

    def test_missing_key_returns_none(self):
        assert extract_confidence_from_json({"answer": True}) is None

    def test_none_value_returns_none(self):
        assert extract_confidence_from_json({"confidence": None}) is None

    def test_string_float_parsed(self):
        assert extract_confidence_from_json({"confidence": "0.72"}) == pytest.approx(0.72)

    def test_clamps_above_one(self):
        assert extract_confidence_from_json({"confidence": 1.5}) == pytest.approx(1.0)
