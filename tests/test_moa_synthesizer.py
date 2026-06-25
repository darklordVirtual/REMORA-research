# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for MixtureOfAgentsSynth stage in remora.cascade.stages.

Uses MockOracle — no API keys required.
"""
from __future__ import annotations

import json
from remora.cascade.result import CascadeStage, CascadeVerdict
from remora.cascade.stages import MixtureOfAgentsSynth, _StageContext
from remora.core import Oracle, OracleResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FixedOracle(Oracle):
    """Oracle that returns a fixed JSON response."""

    def __init__(self, name: str, answer: str, confidence: float, consensus: str = "agree"):
        self._name = name
        self._answer = answer
        self._confidence = confidence
        self._consensus = consensus

    @property
    def name(self) -> str:
        return self._name

    def _call(self, prompt: str) -> tuple[str, float, float]:
        resp = json.dumps({
            "answer": self._answer,
            "confidence": self._confidence,
            "consensus": self._consensus,
            "reasoning": f"Oracle {self._name} synthesized this answer.",
        })
        return resp, 0.0, 5.0


class ErrorOracle(Oracle):
    @property
    def name(self) -> str:
        return "error_oracle"

    def _call(self, prompt: str) -> tuple[str, float, float]:
        raise RuntimeError("Simulated API failure")


def _make_oracle_responses(n: int = 3) -> list[OracleResponse]:
    """Build N synthetic oracle responses for use in MoA input."""
    responses = []
    for i in range(n):
        responses.append(OracleResponse(
            provider=f"oracle_{i}",
            raw_text=json.dumps({"claim": f"Answer from oracle {i}", "confidence": 0.75}),
            extracted={"claim": f"Answer from oracle {i}", "confidence": 0.75,
                       "reasoning": f"Reasoning from oracle {i}"},
        ))
    return responses


def _make_ctx(question: str = "Is the speed of light approximately 3e8 m/s?") -> _StageContext:
    ctx = _StageContext(question=question)
    ctx.consensus_answer = "Yes, approximately."
    ctx.consensus_trust = 0.55
    ctx.consensus_phase = "critical"
    return ctx


# ---------------------------------------------------------------------------
# Basic construction
# ---------------------------------------------------------------------------

class TestMoAConstruction:
    def test_instantiation(self):
        oracle = FixedOracle("synth", "True", 0.85)
        stage = MixtureOfAgentsSynth(oracle)
        assert stage.synthesis_oracle is oracle
        assert stage.accept_threshold == 0.65

    def test_custom_threshold(self):
        oracle = FixedOracle("synth", "True", 0.85)
        stage = MixtureOfAgentsSynth(oracle, accept_threshold=0.80)
        assert stage.accept_threshold == 0.80


# ---------------------------------------------------------------------------
# run() — basic contracts
# ---------------------------------------------------------------------------

class TestMoARun:
    def test_returns_stage_result_with_moa_stage(self):
        synth = FixedOracle("synth", "Confirmed: True", 0.90, "agree")
        stage = MixtureOfAgentsSynth(synth)
        ctx = _make_ctx()
        result = stage.run(ctx, oracle_responses=_make_oracle_responses())
        assert result.stage == CascadeStage.MOA_SYNTH

    def test_high_confidence_returns_accept(self):
        synth = FixedOracle("synth", "Confirmed: True", 0.90, "agree")
        stage = MixtureOfAgentsSynth(synth, accept_threshold=0.65)
        ctx = _make_ctx()
        result = stage.run(ctx)
        assert result.verdict == CascadeVerdict.ACCEPT
        assert result.stopped

    def test_low_confidence_returns_abstain(self):
        synth = FixedOracle("synth", "Uncertain", 0.30, "disagree")
        stage = MixtureOfAgentsSynth(synth, accept_threshold=0.65)
        ctx = _make_ctx()
        result = stage.run(ctx)
        assert result.verdict == CascadeVerdict.ABSTAIN
        assert result.stopped

    def test_oracle_calls_is_one(self):
        synth = FixedOracle("synth", "True", 0.80)
        stage = MixtureOfAgentsSynth(synth)
        ctx = _make_ctx()
        result = stage.run(ctx, oracle_responses=_make_oracle_responses())
        assert result.oracle_calls == 1

    def test_answer_propagates_to_ctx(self):
        synth = FixedOracle("synth", "Synthesized answer", 0.88)
        stage = MixtureOfAgentsSynth(synth)
        ctx = _make_ctx()
        result = stage.run(ctx)
        assert ctx.consensus_answer == result.answer

    def test_metadata_contains_synthesis_oracle(self):
        synth = FixedOracle("my_synth", "Yes", 0.85)
        stage = MixtureOfAgentsSynth(synth)
        ctx = _make_ctx()
        result = stage.run(ctx)
        assert result.metadata["synthesis_oracle"] == "my_synth"

    def test_metadata_contains_n_inputs(self):
        synth = FixedOracle("synth", "Yes", 0.80)
        stage = MixtureOfAgentsSynth(synth)
        ctx = _make_ctx()
        responses = _make_oracle_responses(n=3)
        result = stage.run(ctx, oracle_responses=responses)
        assert result.metadata["n_inputs"] == 3


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestMoAErrorHandling:
    def test_synthesis_oracle_failure_returns_verify(self):
        stage = MixtureOfAgentsSynth(ErrorOracle())
        ctx = _make_ctx()
        result = stage.run(ctx)
        assert result.verdict == CascadeVerdict.VERIFY
        assert not result.stopped  # pipeline continues

    def test_synthesis_oracle_failure_preserves_consensus_answer(self):
        stage = MixtureOfAgentsSynth(ErrorOracle())
        ctx = _make_ctx()
        original_answer = ctx.consensus_answer
        result = stage.run(ctx)
        assert result.answer == original_answer

    def test_no_oracle_responses_uses_consensus_fallback(self):
        """When no oracle responses are provided, uses ctx.consensus_answer as input."""
        synth = FixedOracle("synth", "Fallback answer", 0.75)
        stage = MixtureOfAgentsSynth(synth)
        ctx = _make_ctx()
        ctx.consensus_answer = "Original consensus"
        result = stage.run(ctx, oracle_responses=[])
        # Should still produce a result (falls back to consensus_answer as sole input)
        assert result.stage == CascadeStage.MOA_SYNTH


# ---------------------------------------------------------------------------
# Confidence boundary conditions
# ---------------------------------------------------------------------------

class TestMoAConfidenceBoundaries:
    def test_confidence_at_threshold_accepts(self):
        synth = FixedOracle("synth", "Borderline", 0.65)
        stage = MixtureOfAgentsSynth(synth, accept_threshold=0.65)
        ctx = _make_ctx()
        result = stage.run(ctx)
        assert result.verdict == CascadeVerdict.ACCEPT

    def test_confidence_just_below_threshold_abstains(self):
        synth = FixedOracle("synth", "Borderline", 0.64)
        stage = MixtureOfAgentsSynth(synth, accept_threshold=0.65)
        ctx = _make_ctx()
        result = stage.run(ctx)
        assert result.verdict == CascadeVerdict.ABSTAIN

    def test_invalid_confidence_parsed_as_half(self):
        """If synthesis oracle returns non-numeric confidence, defaults to 0.5."""
        class BadConfOracle(Oracle):
            @property
            def name(self): return "bad_conf"
            def _call(self, prompt): return '{"answer":"yes","confidence":"not_a_number"}', 0.0, 5.0

        stage = MixtureOfAgentsSynth(BadConfOracle(), accept_threshold=0.65)
        ctx = _make_ctx()
        result = stage.run(ctx)
        assert result.confidence == 0.5
        assert result.verdict == CascadeVerdict.ABSTAIN
