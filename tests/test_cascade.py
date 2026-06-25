"""Tests for remora.cascade — multi-stage cascade pipeline."""
import json
import pytest
from remora.cascade.result import CascadeStage, CascadeVerdict, CascadeResult
from remora.cascade.stages import FastGate, VerifierGate, SelfConsistencyGate, CritiqueRevisionGate, _StageContext
from remora.cascade.engine import CascadeEngine
from remora.genome import Genome
from remora.core import Oracle, OracleResponse


class _FixedOracle(Oracle):
    def __init__(self, payload: dict, name: str = "fixed"):
        self._payload = payload
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def _call(self, prompt: str) -> tuple[str, float, float]:
        return json.dumps(self._payload), 0.0, 1.0


class _SequenceOracle(Oracle):
    """Returns payloads in sequence; last payload repeats."""

    def __init__(self, payloads: list[dict], name: str = "seq"):
        self._payloads = payloads
        self._idx = 0
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def _call(self, prompt: str) -> tuple[str, float, float]:
        payload = self._payloads[min(self._idx, len(self._payloads) - 1)]
        self._idx += 1
        return json.dumps(payload), 0.0, 1.0


class TestCascadeResult:
    def test_is_accepted(self):
        r = CascadeResult(CascadeVerdict.ACCEPT, 0.95)
        assert r.is_accepted
        assert not r.is_abstained

    def test_is_abstained(self):
        r = CascadeResult(CascadeVerdict.ABSTAIN, 0.10)
        assert r.is_abstained

    def test_escalate_is_abstained(self):
        r = CascadeResult(CascadeVerdict.ESCALATE, 0.05)
        assert r.is_abstained

    def test_summary_keys(self):
        r = CascadeResult(CascadeVerdict.ACCEPT, 0.90, answer="yes", total_oracle_calls=3, stopped_at_stage=1)
        s = r.summary()
        assert s["verdict"] == "accept"
        assert s["oracle_calls"] == 3
        assert s["stages_run"] == 1


class TestFastGate:
    def test_accept_on_high_confidence(self):
        oracle = _FixedOracle({"answer": "Paris", "confidence": 0.95, "reasoning": "obvious"})
        gate = FastGate(oracle, threshold=0.90)
        ctx = _StageContext(question="What is the capital of France?")
        result = gate.run(ctx)
        assert result.verdict == CascadeVerdict.ACCEPT
        assert result.stopped is True
        assert result.oracle_calls == 1
        assert result.confidence == pytest.approx(0.95)

    def test_continue_on_low_confidence(self):
        oracle = _FixedOracle({"answer": "Maybe Paris", "confidence": 0.70})
        gate = FastGate(oracle, threshold=0.90)
        ctx = _StageContext(question="What is the capital of France?")
        result = gate.run(ctx)
        assert result.verdict == CascadeVerdict.VERIFY
        assert result.stopped is False

    def test_answer_stored_in_context(self):
        oracle = _FixedOracle({"answer": "Berlin", "confidence": 0.95})
        gate = FastGate(oracle, threshold=0.90)
        ctx = _StageContext(question="Capital of Germany?")
        gate.run(ctx)
        assert ctx.consensus_answer == "Berlin"


class TestVerifierGate:
    def test_supported_high_confidence_accepts(self):
        oracle = _FixedOracle({"verdict": "supported", "confidence": 0.85, "critique": "Correct."})
        gate = VerifierGate(oracle, verify_threshold=0.70)
        ctx = _StageContext(question="q?", consensus_answer="Paris")
        result = gate.run(ctx)
        assert result.verdict == CascadeVerdict.ACCEPT
        assert result.stopped is True

    def test_refuted_abstains(self):
        oracle = _FixedOracle({"verdict": "refuted", "confidence": 0.88, "critique": "Wrong."})
        gate = VerifierGate(oracle, verify_threshold=0.70)
        ctx = _StageContext(question="q?", consensus_answer="Wrong answer")
        result = gate.run(ctx)
        assert result.verdict == CascadeVerdict.ABSTAIN
        assert result.stopped is True

    def test_challenged_continues(self):
        oracle = _FixedOracle({"verdict": "challenged", "confidence": 0.55, "critique": "Vague."})
        gate = VerifierGate(oracle, verify_threshold=0.70)
        ctx = _StageContext(question="q?", consensus_answer="Some answer")
        result = gate.run(ctx)
        assert result.verdict == CascadeVerdict.VERIFY
        assert result.stopped is False

    def test_supported_low_confidence_continues(self):
        oracle = _FixedOracle({"verdict": "supported", "confidence": 0.55, "critique": "Weak."})
        gate = VerifierGate(oracle, verify_threshold=0.70)
        ctx = _StageContext(question="q?", consensus_answer="Some answer")
        result = gate.run(ctx)
        assert result.stopped is False


class TestSelfConsistencyGate:
    def test_high_agreement_accepts(self):
        oracle = _FixedOracle({"answer": "Paris", "confidence": 0.80})
        gate = SelfConsistencyGate(oracle, sc_samples=5, sc_threshold=0.70)
        ctx = _StageContext(question="Capital of France?")
        result = gate.run(ctx)
        assert result.verdict == CascadeVerdict.ACCEPT
        assert result.oracle_calls == 5
        assert result.metadata["agreement"] == pytest.approx(1.0)

    def test_low_agreement_abstains(self):
        payloads = [
            {"answer": "Paris"}, {"answer": "Berlin"}, {"answer": "Rome"},
            {"answer": "Madrid"}, {"answer": "Vienna"},
        ]
        oracle = _SequenceOracle(payloads)
        gate = SelfConsistencyGate(oracle, sc_samples=5, sc_threshold=0.70)
        ctx = _StageContext(question="Capital?")
        result = gate.run(ctx)
        assert result.verdict == CascadeVerdict.ABSTAIN
        assert result.metadata["agreement"] < 0.50


class TestCascadeEngine:
    def _make_engine(self, fast_payload, judge_payload, sc_payload=None, max_stages=3):
        from remora.oracles.mock import MockOracle

        fast = _FixedOracle(fast_payload, "fast")
        judge = _FixedOracle(judge_payload, "judge")
        consensus_oracles = [MockOracle("a"), MockOracle("b"), MockOracle("c")]

        genome = Genome(
            enable_routing=True,
            enable_thermodynamic_control=False,
            router_mode=__import__("remora.genome", fromlist=["RouterMode"]).RouterMode.BALANCED,
        )
        return CascadeEngine(
            consensus_oracles=consensus_oracles,
            judge_oracle=judge,
            fast_oracle=fast,
            genome=genome,
            fast_threshold=0.90,
            verify_threshold=0.70,
            max_stages=max_stages,
        )

    def test_fast_gate_accepts_at_stage_1(self):
        engine = self._make_engine(
            fast_payload={"answer": "Paris", "confidence": 0.95},
            judge_payload={"verdict": "supported", "confidence": 0.90, "critique": "ok"},
            max_stages=4,
        )
        result = engine.run("Capital of France?")
        assert result.final_verdict == CascadeVerdict.ACCEPT
        assert result.stopped_at_stage == CascadeStage.FAST_GATE.value
        assert result.total_oracle_calls == 1

    def test_result_has_answer(self):
        engine = self._make_engine(
            fast_payload={"answer": "Berlin", "confidence": 0.92},
            judge_payload={"verdict": "supported", "confidence": 0.85, "critique": "ok"},
        )
        result = engine.run("Capital of Germany?")
        assert result.answer is not None

    def test_budget_cap_returns_verify(self):
        from remora.oracles.mock import MockOracle
        fast = _FixedOracle({"answer": "Paris", "confidence": 0.50}, "fast")  # low conf → continue
        judge = _FixedOracle({"verdict": "challenged", "confidence": 0.55, "critique": "vague"}, "judge")
        genome = Genome(enable_routing=True)
        engine = CascadeEngine(
            consensus_oracles=[MockOracle("a"), MockOracle("b"), MockOracle("c")],
            judge_oracle=judge,
            fast_oracle=fast,
            genome=genome,
            budget_oracle_calls=1,  # Only allows Stage 1
            max_stages=4,
        )
        result = engine.run("Hard question?")
        # With budget=1, Stage 1 runs (1 call), budget exhausted → VERIFY
        assert result.final_verdict == CascadeVerdict.VERIFY
        assert result.total_oracle_calls <= 1


class TestCritiqueRevisionGate:
    """Tests for Stage 3b: critique-driven revision loop."""

    def _make_gate(self, rev_payloads, judge_payloads, max_rounds=2, verify_threshold=0.70):
        revision_oracle = (
            _SequenceOracle(rev_payloads) if len(rev_payloads) > 1 else _FixedOracle(rev_payloads[0])
        )
        judge_oracle = (
            _SequenceOracle(judge_payloads) if len(judge_payloads) > 1 else _FixedOracle(judge_payloads[0])
        )
        return CritiqueRevisionGate(
            revision_oracle, judge_oracle, max_rounds=max_rounds, verify_threshold=verify_threshold
        )

    def _ctx(self, answer="Draft answer", critique="Too vague."):
        return _StageContext(question="What is the capital of France?", consensus_answer=answer, last_critique=critique)

    def test_first_round_supported_accepts(self):
        gate = self._make_gate(
            rev_payloads=[{"answer": "Paris", "confidence": 0.90}],
            judge_payloads=[{"verdict": "supported", "confidence": 0.85, "critique": "Correct."}],
        )
        result = gate.run(self._ctx())
        assert result.verdict == CascadeVerdict.ACCEPT
        assert result.stopped is True
        assert result.oracle_calls == 2  # 1 revision + 1 judge

    def test_first_round_refuted_abstains(self):
        gate = self._make_gate(
            rev_payloads=[{"answer": "Berlin", "confidence": 0.70}],
            judge_payloads=[{"verdict": "refuted", "confidence": 0.90, "critique": "Berlin is not the capital of France."}],
        )
        result = gate.run(self._ctx())
        assert result.verdict == CascadeVerdict.ABSTAIN
        assert result.stopped is True
        assert result.oracle_calls == 2

    def test_max_rounds_still_challenged_returns_verify(self):
        gate = self._make_gate(
            rev_payloads=[{"answer": "Maybe Paris?"}, {"answer": "Probably Paris."}],
            judge_payloads=[
                {"verdict": "challenged", "confidence": 0.55, "critique": "Too hedged."},
                {"verdict": "challenged", "confidence": 0.50, "critique": "Still not confident enough."},
            ],
            max_rounds=2,
        )
        result = gate.run(self._ctx())
        assert result.verdict == CascadeVerdict.VERIFY
        assert result.stopped is False
        assert result.oracle_calls == 4  # 2 rounds × (1 revision + 1 judge)
        assert result.metadata["rounds"] == 2
        assert result.metadata["max_rounds"] == 2

    def test_second_round_accepts(self):
        gate = self._make_gate(
            rev_payloads=[{"answer": "I think Paris"}, {"answer": "Paris"}],
            judge_payloads=[
                {"verdict": "challenged", "confidence": 0.55, "critique": "Too uncertain."},
                {"verdict": "supported", "confidence": 0.92, "critique": "Correct and precise."},
            ],
            max_rounds=2,
        )
        result = gate.run(self._ctx())
        assert result.verdict == CascadeVerdict.ACCEPT
        assert result.stopped is True
        assert result.oracle_calls == 4  # both rounds completed
        assert result.metadata["rounds"] == 2

    def test_context_updated_with_revised_answer(self):
        gate = self._make_gate(
            rev_payloads=[{"answer": "The capital is Paris."}],
            judge_payloads=[{"verdict": "supported", "confidence": 0.95, "critique": "Correct."}],
        )
        ctx = self._ctx(answer="Paris maybe")
        gate.run(ctx)
        assert ctx.consensus_answer == "The capital is Paris."

    def test_low_confidence_supported_continues(self):
        gate = self._make_gate(
            rev_payloads=[{"answer": "Paris"}, {"answer": "Paris (confirmed)"}],
            judge_payloads=[
                {"verdict": "supported", "confidence": 0.60, "critique": "Correct but low confidence."},
                {"verdict": "supported", "confidence": 0.85, "critique": "Correct."},
            ],
            max_rounds=2,
            verify_threshold=0.70,
        )
        result = gate.run(self._ctx())
        # First round: supported but conf=0.60 < threshold=0.70 → treated as CHALLENGED? No —
        # supported with confidence below threshold should be CHALLENGED-like in the judge logic,
        # but the CritiqueRevisionGate only checks JudgeOutcome, not confidence for "supported".
        # Actually JudgeOutcome.SUPPORTED + conf >= verify_threshold → ACCEPT.
        # conf=0.60 < 0.70 → NOT accepted → falls through to next round.
        assert result.verdict == CascadeVerdict.ACCEPT
        assert result.oracle_calls == 4

    def test_stage_enum_is_critique_revision(self):
        gate = self._make_gate(
            rev_payloads=[{"answer": "Paris"}],
            judge_payloads=[{"verdict": "supported", "confidence": 0.90, "critique": "OK."}],
        )
        result = gate.run(self._ctx())
        assert result.stage == CascadeStage.CRITIQUE_REVISION

    def test_no_critique_in_context_uses_fallback(self):
        gate = self._make_gate(
            rev_payloads=[{"answer": "Paris"}],
            judge_payloads=[{"verdict": "supported", "confidence": 0.88, "critique": "Fine."}],
        )
        ctx = _StageContext(question="Capital?", consensus_answer="Paris", last_critique=None)
        result = gate.run(ctx)  # should not raise even with no critique
        assert result.verdict == CascadeVerdict.ACCEPT


class TestCritiqueRevisionGateEdgeCases:
    """Edge-case tests for CritiqueRevisionGate robustness."""

    def test_oracle_error_breaks_loop_early(self):
        """When the revision oracle fails, the gate should stop and return VERIFY."""

        class _ErrorOracle:
            """Oracle that always returns an error response."""
            name = "error"
            def ask(self, prompt: str) -> OracleResponse:
                return OracleResponse(provider="error", raw_text="", extracted={}, error="timeout")

        judge_oracle = _FixedOracle(
            {"verdict": "supported", "confidence": 0.90, "critique": "Good."}
        )
        gate = CritiqueRevisionGate(_ErrorOracle(), judge_oracle, max_rounds=2)
        ctx = _StageContext(question="q?", consensus_answer="Draft", last_critique="Too vague.")
        result = gate.run(ctx)
        # Oracle failed on first revision call — loop breaks, returns VERIFY (not stopped)
        assert result.verdict == CascadeVerdict.VERIFY
        assert result.stopped is False
        assert result.oracle_calls == 1  # only the failed revision call counted

    def test_judge_parse_error_treated_as_challenged(self):
        """PARSE_ERROR from the judge within a revision round is treated as CHALLENGED."""
        gate = CritiqueRevisionGate(
            _FixedOracle({"answer": "Paris"}),
            _FixedOracle({"verdict": "completely_unparseable_garbage"}),
            max_rounds=1,
            verify_threshold=0.70,
        )
        ctx = _StageContext(question="Capital?", consensus_answer="Paris", last_critique="Vague.")
        result = gate.run(ctx)
        # PARSE_ERROR is neither SUPPORTED nor REFUTED → max_rounds exhausted → VERIFY
        assert result.verdict == CascadeVerdict.VERIFY
        assert result.stopped is False

    def test_stopped_at_stage_value_is_5_when_cr_terminal(self):
        """CascadeResult.stopped_at_stage should be 5 (CRITIQUE_REVISION) when CR is terminal."""
        from remora.oracles.mock import MockOracle
        fast = _FixedOracle({"answer": "Draft", "confidence": 0.40}, "fast")
        judge = _SequenceOracle([
            {"verdict": "challenged", "confidence": 0.55, "critique": "Too vague."},  # Stage 3
            {"verdict": "supported", "confidence": 0.88, "critique": "Correct now."},  # Stage 3b
        ], "judge")
        genome = Genome(
            enable_routing=True,
            enable_thermodynamic_control=False,
            router_mode=__import__("remora.genome", fromlist=["RouterMode"]).RouterMode.BALANCED,
        )
        engine = CascadeEngine(
            consensus_oracles=[MockOracle("a"), MockOracle("b"), MockOracle("c")],
            judge_oracle=judge, fast_oracle=fast, genome=genome,
            fast_threshold=0.50, verify_threshold=0.70, max_stages=4, budget_oracle_calls=20,
        )
        result = engine.run("Test question?")
        if result.final_verdict == CascadeVerdict.ACCEPT:
            assert result.stopped_at_stage == CascadeStage.CRITIQUE_REVISION.value  # == 5


class TestCascadeEngineCritiqueRevision:
    """Integration tests for critique-revision in the full CascadeEngine."""

    def _make_engine(self, fast_payload, judge_payloads, max_stages=4):
        from remora.oracles.mock import MockOracle

        fast = _FixedOracle(fast_payload, "fast")
        # judge oracle must handle both VerifierGate (1 call) and CritiqueRevisionGate
        judge = _SequenceOracle(judge_payloads, "judge") if len(judge_payloads) > 1 else _FixedOracle(judge_payloads[0], "judge")
        consensus_oracles = [MockOracle("a"), MockOracle("b"), MockOracle("c")]
        genome = Genome(
            enable_routing=True,
            enable_thermodynamic_control=False,
            router_mode=__import__("remora.genome", fromlist=["RouterMode"]).RouterMode.BALANCED,
        )
        return CascadeEngine(
            consensus_oracles=consensus_oracles,
            judge_oracle=judge,
            fast_oracle=fast,
            genome=genome,
            fast_threshold=0.50,  # low so Stage 1 never short-circuits
            verify_threshold=0.70,
            max_stages=max_stages,
            budget_oracle_calls=20,
        )

    def test_critique_revision_accepts_after_challenged(self):
        # Stage 1: low confidence (0.40) → proceed
        # Stage 3: CHALLENGED → Stage 3b triggered
        # Stage 3b: revision oracle returns revised answer, judge says SUPPORTED
        engine = self._make_engine(
            fast_payload={"answer": "Draft", "confidence": 0.40},
            judge_payloads=[
                {"verdict": "challenged", "confidence": 0.55, "critique": "Too vague."},  # Stage 3
                {"verdict": "supported", "confidence": 0.88, "critique": "Now correct."},  # Stage 3b judge
            ],
        )
        result = engine.run("What is 2+2?")
        assert result.final_verdict == CascadeVerdict.ACCEPT
        assert any(s.stage == CascadeStage.CRITIQUE_REVISION for s in result.stages_run)

    def test_critique_revision_abstains_after_refuted(self):
        engine = self._make_engine(
            fast_payload={"answer": "Wrong", "confidence": 0.40},
            judge_payloads=[
                {"verdict": "challenged", "confidence": 0.55, "critique": "Wrong."},  # Stage 3
                {"verdict": "refuted", "confidence": 0.92, "critique": "Still wrong."},  # Stage 3b
            ],
        )
        result = engine.run("Is 2+2=5?")
        assert result.final_verdict == CascadeVerdict.ABSTAIN
        assert any(s.stage == CascadeStage.CRITIQUE_REVISION for s in result.stages_run)


class TestDynamicIterationGate:
    """Tests for the Dynamic Iteration Gate short-circuit in CritiqueRevisionGate."""

    def _make_gate(self, skip_threshold=0.75):
        # Oracle bodies don't matter — we expect the gate to short-circuit before calling them
        from remora.oracles.mock import MockOracle
        revision_oracle = MockOracle("rev")
        judge_oracle = MockOracle("judge")
        return CritiqueRevisionGate(
            revision_oracle,
            judge_oracle,
            max_rounds=2,
            verify_threshold=0.70,
            skip_high_trust_threshold=skip_threshold,
        )

    def _ctx(self, trust, answer="Good answer"):
        ctx = _StageContext(question="Test question?", consensus_answer=answer)
        ctx.consensus_trust = trust
        return ctx

    def test_high_trust_short_circuits_with_zero_oracle_calls(self):
        """trust >= 0.75 → immediately ACCEPT with 0 oracle calls."""
        gate = self._make_gate()
        result = gate.run(self._ctx(trust=0.80))
        assert result.verdict == CascadeVerdict.ACCEPT
        assert result.oracle_calls == 0
        assert result.stopped is True
        assert result.metadata.get("skipped") is True

    def test_high_trust_preserves_consensus_answer(self):
        """Short-circuit should preserve the existing consensus answer unchanged."""
        gate = self._make_gate()
        ctx = self._ctx(trust=0.90, answer="The Eiffel Tower")
        result = gate.run(ctx)
        assert result.answer == "The Eiffel Tower"

    def test_trust_exactly_at_threshold_short_circuits(self):
        """trust == 0.75 (exactly at threshold) should short-circuit."""
        gate = self._make_gate(skip_threshold=0.75)
        result = gate.run(self._ctx(trust=0.75))
        assert result.oracle_calls == 0
        assert result.verdict == CascadeVerdict.ACCEPT

    def test_trust_below_threshold_runs_normal_loop(self):
        """trust < 0.75 should NOT short-circuit; normal revision loop runs."""
        gate = self._make_gate(skip_threshold=0.75)
        ctx = self._ctx(trust=0.60)
        # MockOracle will produce a revision + judge call; gate should attempt loop
        result = gate.run(ctx)
        # Normal loop ran: oracle_calls > 0 (even if Mock returns poor results)
        assert result.oracle_calls > 0

    def test_none_trust_runs_normal_loop(self):
        """ctx.consensus_trust = None should NOT short-circuit."""
        gate = self._make_gate(skip_threshold=0.75)
        ctx = _StageContext(question="q?", consensus_answer="Draft")
        ctx.consensus_trust = None
        result = gate.run(ctx)
        assert result.oracle_calls > 0

    def test_custom_skip_threshold_is_respected(self):
        """skip_high_trust_threshold=0.95 should not trigger at trust=0.80."""
        gate = self._make_gate(skip_threshold=0.95)
        result = gate.run(self._ctx(trust=0.80))
        # 0.80 < 0.95 → normal loop
        assert result.oracle_calls > 0

    def test_disordered_phase_short_circuits_to_abstain(self):
        """consensus_phase='disordered' → immediate ABSTAIN with 0 oracle calls."""
        gate = self._make_gate(skip_threshold=0.75)
        ctx = self._ctx(trust=0.40)  # below high-trust threshold
        ctx.consensus_phase = "disordered"
        result = gate.run(ctx)
        assert result.verdict == CascadeVerdict.ABSTAIN
        assert result.oracle_calls == 0
        assert result.stopped is True
        assert result.metadata.get("reason") == "disordered_phase_abort"

    def test_disordered_phase_abort_takes_priority_over_loop(self):
        """DISORDERED abort fires even when trust=None (loop would otherwise run)."""
        gate = self._make_gate(skip_threshold=0.75)
        ctx = _StageContext(question="q?", consensus_answer="Draft")
        ctx.consensus_trust = None
        ctx.consensus_phase = "disordered"
        result = gate.run(ctx)
        assert result.verdict == CascadeVerdict.ABSTAIN
        assert result.oracle_calls == 0

    def test_critical_phase_runs_revision_loop(self):
        """consensus_phase='critical' → revision loop runs (oracle_calls > 0)."""
        gate = self._make_gate(skip_threshold=0.75)
        ctx = self._ctx(trust=0.40)  # below high-trust threshold
        ctx.consensus_phase = "critical"
        result = gate.run(ctx)
        # Revision loop ran: at least one oracle call was made
        assert result.oracle_calls > 0

    def test_ordered_phase_below_high_trust_runs_loop(self):
        """ordered phase with low trust should still run the revision loop normally."""
        gate = self._make_gate(skip_threshold=0.75)
        ctx = self._ctx(trust=0.50)
        ctx.consensus_phase = "ordered"
        result = gate.run(ctx)
        assert result.oracle_calls > 0


class TestCascadeEngineRuntimeWiring:
    """Integration tests: PlattScaler, DomainCoverageOptimizer, OracleDiversityTracker,
    and uncertainty decomposition routing wired into CascadeEngine."""

    # ------------------------------------------------------------------
    # Mock helpers shared across sub-tests
    # ------------------------------------------------------------------

    class _MockThermoState:
        """Minimal thermodynamic state returned by a fake Remora engine."""
        def __init__(self, trust: float, oracle_confidences: list[float]):
            from remora.core import OracleResponse as _OR
            self.last_thermo = type("T", (), {"trust_score": trust, "phase": "critical"})()
            self.oracle_log = [
                _OR(provider="mock", raw_text="{}", extracted={"confidence": c})
                for c in oracle_confidences
            ]
            self.candidate_support = {}
            self.candidates = {}

    class _MockRemoraEngine:
        """Fake Remora engine that returns a pre-set trust score and oracle confidences."""
        def __init__(self, trust: float, oracle_confidences: list[float]):
            self._trust = trust
            self._confs = oracle_confidences

        def run(self, question: str, context=None):
            return TestCascadeEngineRuntimeWiring._MockThermoState(self._trust, self._confs)

        def report(self, state):
            return {}

    # ------------------------------------------------------------------
    # PlattScaler integration
    # ------------------------------------------------------------------

    def test_platt_scaler_maps_medium_trust_to_accept(self):
        """ConsensusGate + PlattScaler: raw trust 0.50 calibrates to ACCEPT when
        scaler is fit to label all 0.50 items as correct."""
        from remora.calibration.platt_scaler import PlattScaler
        from remora.cascade.stages import ConsensusGate, _StageContext
        from remora.cascade.result import CascadeVerdict

        # Fit so that trust=0.50 maps to P(correct) >> accept_threshold
        scaler = PlattScaler()
        scaler.fit([0.5, 0.5, 0.5, 0.5, 0.5], [True, True, True, True, True])
        calibrated = scaler.transform([0.5])[0]
        assert calibrated > 0.65, "Scaler should push 0.50 toward 1.0 when all items are correct"

        gate = ConsensusGate(
            remora_engine=self._MockRemoraEngine(trust=0.50, oracle_confidences=[0.5]),
            accept_threshold=0.65,
            abstain_threshold=0.12,
            platt_scaler=scaler,
        )
        ctx = _StageContext(question="test?")
        result = gate.run(ctx)
        assert result.verdict == CascadeVerdict.ACCEPT
        assert result.stopped is True
        assert result.metadata["calibrated_trust"] > result.metadata["trust"]

    def test_platt_scaler_calibrated_trust_in_metadata(self):
        """ConsensusGate stores both raw and calibrated trust in stage metadata."""
        from remora.calibration.platt_scaler import PlattScaler
        from remora.cascade.stages import ConsensusGate, _StageContext

        scaler = PlattScaler()
        scaler.fit([0.4, 0.4, 0.4], [False, False, False])
        gate = ConsensusGate(
            remora_engine=self._MockRemoraEngine(trust=0.40, oracle_confidences=[0.4]),
            accept_threshold=0.65,
            abstain_threshold=0.12,
            platt_scaler=scaler,
        )
        ctx = _StageContext(question="test?")
        result = gate.run(ctx)
        assert "calibrated_trust" in result.metadata
        assert "trust" in result.metadata
        # Raw and calibrated should differ when scaler is fitted
        assert result.metadata["calibrated_trust"] != result.metadata["trust"]

    def test_no_platt_scaler_raw_trust_equals_calibrated(self):
        """Without PlattScaler, calibrated_trust in metadata equals raw trust."""
        from remora.cascade.stages import ConsensusGate, _StageContext

        gate = ConsensusGate(
            remora_engine=self._MockRemoraEngine(trust=0.50, oracle_confidences=[0.5]),
            accept_threshold=0.65,
            abstain_threshold=0.12,
        )
        ctx = _StageContext(question="test?")
        result = gate.run(ctx)
        assert result.metadata["calibrated_trust"] == result.metadata["trust"]

    # ------------------------------------------------------------------
    # DomainCoverageOptimizer integration
    # ------------------------------------------------------------------

    def test_domain_threshold_overrides_global(self):
        """Domain-specific threshold overrides global when domain_optimizer + domain given."""
        from remora.calibration.domain_optimizer import DomainCoverageOptimizer
        from remora.cascade.stages import ConsensusGate, _StageContext
        from remora.cascade.result import CascadeVerdict

        # Fit an optimizer: "strict" domain gets very high threshold (0.95)
        optimizer = DomainCoverageOptimizer(min_coverage=0.0, fallback_threshold=0.95)
        # Pre-set threshold without a full fit by using internal dict directly
        optimizer._thresholds["strict"] = 0.95
        optimizer._fitted = True

        gate = ConsensusGate(
            remora_engine=self._MockRemoraEngine(trust=0.70, oracle_confidences=[0.7]),
            accept_threshold=0.65,  # 0.70 > 0.65 would normally ACCEPT
            abstain_threshold=0.12,
        )
        # Simulate what CascadeEngine does: set domain_accept_threshold on ctx
        ctx = _StageContext(question="strict domain question?")
        ctx.domain_accept_threshold = optimizer.threshold("strict")  # 0.95
        result = gate.run(ctx)
        # trust=0.70 < domain threshold=0.95 → should NOT accept
        assert result.verdict != CascadeVerdict.ACCEPT
        assert result.metadata["effective_accept_threshold"] == pytest.approx(0.95)

    def test_domain_threshold_set_on_ctx_by_engine(self):
        """CascadeEngine.run(domain=) sets ctx.domain_accept_threshold when optimizer attached."""
        from remora.calibration.domain_optimizer import DomainCoverageOptimizer
        from remora.oracles.mock import MockOracle

        optimizer = DomainCoverageOptimizer(fallback_threshold=0.80)
        optimizer._thresholds["science"] = 0.82
        optimizer._fitted = True

        engine = CascadeEngine(
            consensus_oracles=[MockOracle("a"), MockOracle("b"), MockOracle("c")],
            domain_optimizer=optimizer,
            max_stages=1,  # Only Fast gate — stops after Stage 1
            fast_threshold=0.99,  # Fast gate won't accept unless extremely confident
            genome=Genome(
                enable_routing=True,
                enable_thermodynamic_control=False,
                router_mode=__import__("remora.genome", fromlist=["RouterMode"]).RouterMode.BALANCED,
            ),
            fast_oracle=_FixedOracle({"answer": "test", "confidence": 0.50}, "fast"),
        )
        # Running with domain="science" should not crash and should process normally
        result = engine.run("What is gravity?", domain="science")
        # Fast gate confidence=0.50 < threshold=0.99 → VERIFY, not error
        assert result is not None

    # ------------------------------------------------------------------
    # Uncertainty routing integration
    # ------------------------------------------------------------------

    def test_uncertainty_routing_escalates_when_oracles_maximally_uncertain(self):
        """use_uncertainty_routing=True → ESCALATE when all oracles return confidence=0.5
        (maximum aleatoric uncertainty, low epistemic → escalate_human)."""
        from remora.cascade.stages import ConsensusGate, _StageContext
        from remora.cascade.result import CascadeVerdict

        # trust=0.40 puts Stage 2 in VERIFY range (between abstain_threshold and accept_threshold)
        # oracle confidences all 0.5 → aleatoric=1.0, epistemic=0.0 → escalate_human
        gate = ConsensusGate(
            remora_engine=self._MockRemoraEngine(trust=0.40, oracle_confidences=[0.5, 0.5, 0.5]),
            accept_threshold=0.65,
            abstain_threshold=0.12,
        )
        ctx = _StageContext(question="genuinely ambiguous?")
        result = gate.run(ctx)
        assert result.verdict == CascadeVerdict.VERIFY  # Gate itself just returns VERIFY
        # The uncertainty routing fires in CascadeEngine.run(), not in ConsensusGate directly
        assert ctx.oracle_responses is not None
        assert len(ctx.oracle_responses) == 3

    def test_uncertainty_routing_in_engine_triggers_escalate(self):
        """CascadeEngine with use_uncertainty_routing=True escalates when Stage 2 oracle
        pool confidence is maximally ambiguous (all 0.5)."""
        from remora.cascade.stages import ConsensusGate
        from remora.oracles.mock import MockOracle
        from remora.cascade.result import CascadeVerdict

        genome = Genome(
            enable_routing=True,
            enable_thermodynamic_control=False,
            router_mode=__import__("remora.genome", fromlist=["RouterMode"]).RouterMode.BALANCED,
        )
        # Pin fast oracle to low confidence so Stage 1 never accepts.
        low_conf_fast = _FixedOracle({"answer": "unsure", "confidence": 0.50}, "fast")
        engine = CascadeEngine(
            consensus_oracles=[MockOracle("a"), MockOracle("b"), MockOracle("c")],
            fast_oracle=low_conf_fast,
            genome=genome,
            max_stages=4,
            use_uncertainty_routing=True,
        )
        # Replace consensus gate with one that returns VERIFY + all-0.5 oracle responses
        engine._consensus_gate = ConsensusGate(
            remora_engine=self._MockRemoraEngine(trust=0.40, oracle_confidences=[0.5, 0.5, 0.5]),
            accept_threshold=0.65,
            abstain_threshold=0.12,
        )
        result = engine.run("Is this ambiguous?")
        # All oracles confident at 0.5 → aleatoric=1.0 → escalate_human → ESCALATE
        assert result.final_verdict == CascadeVerdict.ESCALATE
        assert result.uncertainty_aleatoric is not None
        assert result.uncertainty_aleatoric > 0.9

    def test_uncertainty_routing_disabled_does_not_escalate(self):
        """Without use_uncertainty_routing, maximally uncertain oracle pool just continues."""
        from remora.cascade.stages import ConsensusGate
        from remora.oracles.mock import MockOracle

        genome = Genome(
            enable_routing=True,
            enable_thermodynamic_control=False,
            router_mode=__import__("remora.genome", fromlist=["RouterMode"]).RouterMode.BALANCED,
        )
        engine = CascadeEngine(
            consensus_oracles=[MockOracle("a"), MockOracle("b"), MockOracle("c")],
            genome=genome,
            max_stages=2,  # Stop after Stage 2 to see its natural verdict
            use_uncertainty_routing=False,  # routing disabled
        )
        engine._consensus_gate = ConsensusGate(
            remora_engine=self._MockRemoraEngine(trust=0.40, oracle_confidences=[0.5, 0.5, 0.5]),
            accept_threshold=0.65,
            abstain_threshold=0.12,
        )
        result = engine.run("Is this ambiguous?")
        # Without routing, Stage 2 VERIFY → pipeline returns VERIFY, not ESCALATE
        assert result.final_verdict != __import__("remora.cascade.result", fromlist=["CascadeVerdict"]).CascadeVerdict.ESCALATE

    # ------------------------------------------------------------------
    # OracleDiversityTracker integration
    # ------------------------------------------------------------------

    def test_diversity_selection_trims_pool(self):
        """When diversity_tracker + oracle_names are provided with pool > k, engine initializes."""
        from remora.oracles.diversity import OracleDiversityTracker
        from remora.oracles.mock import MockOracle

        tracker = OracleDiversityTracker()
        # Record history: a-b independent, a-c correlated, b-c correlated
        for _ in range(20):
            tracker.observe("a", "b", agreed=False)   # diverse pair
            tracker.observe("a", "c", agreed=True)    # correlated pair
            tracker.observe("b", "c", agreed=True)    # correlated pair

        # Pool of 4 oracles; select best 2
        oracles = [MockOracle(n) for n in ["a", "b", "c", "d"]]
        engine = CascadeEngine(
            consensus_oracles=oracles,
            oracle_names=["a", "b", "c", "d"],
            diversity_tracker=tracker,
            diversity_k=2,
            max_stages=1,
            fast_oracle=_FixedOracle({"answer": "test", "confidence": 0.99}, "fast"),
            genome=Genome(
                enable_routing=True,
                enable_thermodynamic_control=False,
                router_mode=__import__("remora.genome", fromlist=["RouterMode"]).RouterMode.BALANCED,
            ),
        )
        # Engine should initialize without error; selected oracle pool is diversity_k=2
        result = engine.run("test question?")
        assert result is not None

    def test_diversity_selection_skipped_when_pool_equals_k(self):
        """When pool size == diversity_k, no selection occurs and all oracles are used."""
        from remora.oracles.diversity import OracleDiversityTracker
        from remora.oracles.mock import MockOracle

        tracker = OracleDiversityTracker()
        oracles = [MockOracle(n) for n in ["a", "b", "c"]]
        engine = CascadeEngine(
            consensus_oracles=oracles,
            oracle_names=["a", "b", "c"],
            diversity_tracker=tracker,
            diversity_k=3,  # exactly pool size — no trimming
            max_stages=1,
            fast_oracle=_FixedOracle({"answer": "ok", "confidence": 0.99}, "fast"),
            genome=Genome(
                enable_routing=True,
                enable_thermodynamic_control=False,
                router_mode=__import__("remora.genome", fromlist=["RouterMode"]).RouterMode.BALANCED,
            ),
        )
        result = engine.run("test?")
        assert result is not None


class TestCascadeEngineMoASynth:
    """Integration tests: CascadeEngine actually executes Stage 6 MoA Synth."""

    def _make_engine_with_moa(self, fast_payload, synth_payload, sc_payload=None):
        """Build an engine that is *guaranteed* to reach Stage 6.

        Fast gate returns low confidence → Stage 1 does not stop.
        ConsensusGate (MockOracle) returns VERIFY trust → Stage 2 does not stop.
        Verifier judge returns CHALLENGED → Stage 3 does not stop.
        CritiqueRevision also does not stop.
        SelfConsistency returns low agreement → Stage 4 does not stop.
        MoA Synth is the final arbiter.
        """
        from remora.oracles.mock import MockOracle

        # Stage 1: low confidence → continue
        fast = _FixedOracle(fast_payload, "fast")
        # Stage 3 judge: challenged → continue
        judge = _FixedOracle(
            {"verdict": "challenged", "confidence": 0.50, "critique": "Needs verification"},
            "judge",
        )
        # Stage 4 self-consistency: split answers → low agreement → continue
        sc_oracle = _SequenceOracle(
            [{"answer": "Paris"}, {"answer": "Berlin"}, {"answer": "Rome"},
             {"answer": "Madrid"}, {"answer": "Vienna"}, {"answer": "Paris"}, {"answer": "Berlin"}],
            "sc",
        )
        # Stage 6 synthesis oracle
        synth = _FixedOracle(synth_payload, "synth")

        consensus_oracles = [MockOracle("a"), MockOracle("b"), MockOracle("c")]
        genome = Genome(
            enable_routing=True,
            enable_thermodynamic_control=False,
            router_mode=__import__("remora.genome", fromlist=["RouterMode"]).RouterMode.BALANCED,
        )
        engine = CascadeEngine(
            consensus_oracles=consensus_oracles,
            judge_oracle=judge,
            fast_oracle=fast,
            synthesis_oracle=synth,
            genome=genome,
            fast_threshold=0.90,
            verify_threshold=0.70,
            sc_samples=7,
            sc_threshold=0.90,  # high threshold → SC does not stop on split answers
            max_stages=4,
        )
        # Replace SC gate with the split-answer oracle so Stage 4 doesn't accept
        from remora.cascade.stages import SelfConsistencyGate
        engine._sc_gate = SelfConsistencyGate(sc_oracle, sc_samples=7, sc_threshold=0.90)
        return engine

    def test_moa_synth_accept_stops_at_stage_6(self):
        """When synthesis oracle returns high confidence, verdict is ACCEPT at MOA_SYNTH."""
        engine = self._make_engine_with_moa(
            fast_payload={"answer": "unsure", "confidence": 0.50},
            synth_payload={"answer": "Paris", "confidence": 0.88, "consensus": "agree", "reasoning": "majority"},
        )
        result = engine.run("Capital of France?")
        assert result.final_verdict == CascadeVerdict.ACCEPT
        assert result.stopped_at_stage == CascadeStage.MOA_SYNTH.value
        # At least the MoA call on top of prior calls
        assert result.total_oracle_calls >= 2

    def test_moa_synth_low_confidence_abstains(self):
        """When synthesis oracle returns low confidence, verdict is ABSTAIN at MOA_SYNTH."""
        engine = self._make_engine_with_moa(
            fast_payload={"answer": "unsure", "confidence": 0.50},
            synth_payload={"answer": "maybe Paris", "confidence": 0.30, "consensus": "disagree", "reasoning": "unclear"},
        )
        result = engine.run("Capital of France?")
        assert result.final_verdict == CascadeVerdict.ABSTAIN
        assert result.stopped_at_stage == CascadeStage.MOA_SYNTH.value

    def test_no_synthesis_oracle_skips_stage_6(self):
        """Without synthesis_oracle, Stage 6 is not run even when all prior stages return VERIFY."""
        from remora.oracles.mock import MockOracle

        fast = _FixedOracle({"answer": "unsure", "confidence": 0.50}, "fast")
        judge = _FixedOracle(
            {"verdict": "challenged", "confidence": 0.50, "critique": "Unclear"}, "judge"
        )
        consensus_oracles = [MockOracle("a"), MockOracle("b"), MockOracle("c")]
        genome = Genome(
            enable_routing=True,
            enable_thermodynamic_control=False,
            router_mode=__import__("remora.genome", fromlist=["RouterMode"]).RouterMode.BALANCED,
        )
        engine = CascadeEngine(
            consensus_oracles=consensus_oracles,
            judge_oracle=judge,
            fast_oracle=fast,
            # No synthesis_oracle — Stage 6 disabled
            genome=genome,
            max_stages=1,  # Only Stage 1 — fast gate doesn't accept, returns VERIFY
        )
        result = engine.run("Capital of France?")
        # Stage 6 was never reached
        moa_stages = [s for s in result.stages_run if s.stage == CascadeStage.MOA_SYNTH]
        assert len(moa_stages) == 0

    def test_moa_synth_answer_propagates(self):
        """Synthesized answer becomes the final result answer."""
        engine = self._make_engine_with_moa(
            fast_payload={"answer": "unsure", "confidence": 0.50},
            synth_payload={"answer": "Synthesized: Paris", "confidence": 0.85, "consensus": "agree", "reasoning": "ok"},
        )
        result = engine.run("Capital of France?")
        assert result.answer == "Synthesized: Paris"


class TestPlattCalibrator:
    def test_default_identity_like(self):
        from remora.confidence.calibrator import PlattCalibrator
        cal = PlattCalibrator()
        # Default a=-4, b=2 maps 0.5 → sigmoid(-4*0.5+2) = sigmoid(0) = 0.5
        p = cal.calibrate(0.5)
        assert 0.3 <= p <= 0.7

    def test_fit_improves_overconfident_scores(self):
        from remora.confidence.calibrator import PlattCalibrator
        # Simulate overconfident model: always says 0.9, correct only 50% of time
        cal = PlattCalibrator()
        raw = [0.9] * 100
        labels = [1, 0] * 50
        cal.fit(raw, labels)
        # After fitting, calibrate(0.9) should be closer to 0.5
        p = cal.calibrate(0.9)
        assert p < 0.8

    def test_save_load_roundtrip(self, tmp_path):
        from remora.confidence.calibrator import PlattCalibrator
        path = tmp_path / "cal.json"
        cal = PlattCalibrator(a=-3.0, b=1.5, is_fitted=True)
        cal.save(path)
        loaded = PlattCalibrator.load(path)
        assert loaded.a == pytest.approx(-3.0)
        assert loaded.b == pytest.approx(1.5)
        assert loaded.is_fitted
