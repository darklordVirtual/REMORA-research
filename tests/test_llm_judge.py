"""Tests for remora.verifier.llm_judge — LLM-as-judge verifier."""
import json
import pytest
from remora.verifier.llm_judge import LLMJudge, JudgeOutcome, JudgeVerdict, _parse_verdict
from remora.core import Oracle


class _FixedOracle(Oracle):
    """Oracle that returns a predetermined JSON response."""

    def __init__(self, payload: dict, name: str = "fixed"):
        self._payload = payload
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def _call(self, prompt: str) -> tuple[str, float, float]:
        return json.dumps(self._payload), 0.0, 1.0


class TestParseVerdict:
    def test_supported_clean_json(self):
        raw = '{"verdict": "supported", "confidence": 0.95, "critique": "Accurate."}'
        v = _parse_verdict(raw)
        assert v.outcome == JudgeOutcome.SUPPORTED
        assert v.confidence == pytest.approx(0.95)
        assert v.critique == "Accurate."

    def test_refuted_clean_json(self):
        raw = '{"verdict": "refuted", "confidence": 0.88, "critique": "Wrong."}'
        v = _parse_verdict(raw)
        assert v.outcome == JudgeOutcome.REFUTED

    def test_challenged_clean_json(self):
        raw = '{"verdict": "challenged", "confidence": 0.60, "critique": "Incomplete."}'
        v = _parse_verdict(raw)
        assert v.outcome == JudgeOutcome.CHALLENGED

    def test_json_embedded_in_prose(self):
        raw = 'Here is my evaluation: {"verdict": "supported", "confidence": 0.82, "critique": "Good."} That is all.'
        v = _parse_verdict(raw)
        assert v.outcome == JudgeOutcome.SUPPORTED

    def test_verdict_keyword_fallback(self):
        raw = "After careful consideration, I believe this answer is supported by the evidence."
        v = _parse_verdict(raw)
        assert v.outcome == JudgeOutcome.SUPPORTED

    def test_empty_response_parse_error(self):
        v = _parse_verdict("")
        assert v.outcome == JudgeOutcome.PARSE_ERROR
        assert v.confidence == 0.0

    def test_confidence_clamped_above_one(self):
        raw = '{"verdict": "supported", "confidence": 1.5, "critique": "ok"}'
        v = _parse_verdict(raw)
        assert v.confidence == pytest.approx(1.0)

    def test_confidence_clamped_below_zero(self):
        raw = '{"verdict": "challenged", "confidence": -0.1, "critique": "err"}'
        v = _parse_verdict(raw)
        assert v.confidence == pytest.approx(0.0)


class TestLLMJudge:
    def test_supported_verdict(self):
        oracle = _FixedOracle({"verdict": "supported", "confidence": 0.93, "critique": "Correct."})
        judge = LLMJudge(oracle)
        v = judge.evaluate("Is water H2O?", "Yes, water is H2O.")
        assert v.outcome == JudgeOutcome.SUPPORTED
        assert v.is_trustworthy

    def test_refuted_verdict(self):
        oracle = _FixedOracle({"verdict": "refuted", "confidence": 0.90, "critique": "Wrong element."})
        judge = LLMJudge(oracle)
        v = judge.evaluate("Is water H2O?", "Water is made of carbon.")
        assert v.outcome == JudgeOutcome.REFUTED
        assert v.is_refuted
        assert not v.is_trustworthy

    def test_challenged_verdict(self):
        oracle = _FixedOracle({"verdict": "challenged", "confidence": 0.55, "critique": "Vague."})
        judge = LLMJudge(oracle)
        v = judge.evaluate("What is the capital?", "A large city.")
        assert v.outcome == JudgeOutcome.CHALLENGED
        assert not v.is_trustworthy

    def test_with_evidence(self):
        oracle = _FixedOracle({"verdict": "supported", "confidence": 0.97, "critique": "Evidence confirms."})
        judge = LLMJudge(oracle)
        v = judge.evaluate("Age of Earth?", "4.5 billion years.", evidence=["Earth is 4.54 billion years old."])
        assert v.outcome == JudgeOutcome.SUPPORTED

    def test_evidence_truncation(self):
        oracle = _FixedOracle({"verdict": "supported", "confidence": 0.80, "critique": "ok"})
        judge = LLMJudge(oracle, max_evidence_chars=10)
        long_evidence = ["x" * 500]
        v = judge.evaluate("q?", "a.", evidence=long_evidence)
        assert v.outcome == JudgeOutcome.SUPPORTED

    def test_is_trustworthy_requires_high_confidence(self):
        v_high = JudgeVerdict(JudgeOutcome.SUPPORTED, 0.71, "ok")
        v_low = JudgeVerdict(JudgeOutcome.SUPPORTED, 0.69, "ok")
        assert v_high.is_trustworthy
        assert not v_low.is_trustworthy
