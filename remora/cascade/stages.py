# Author: Stian Skogbrott
# License: Apache-2.0
"""Individual stage implementations for the REMORA cascade pipeline.

Each stage receives the question, optional context, and whatever
accumulated state the prior stages produced.  Each stage returns
a StageResult indicating whether the pipeline should stop or continue.

Stage layout:
  1  FastGate          — 1 oracle call, verbalized confidence gate
  2  ConsensusGate     — full 3-oracle REMORA consensus + thermodynamics
  3  VerifierGate      — LLM-as-judge against consensus answer + evidence
  4  SelfConsistency   — N independent samples from single oracle, measure agreement
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from remora.canonical import phi as _phi
from remora.cascade.result import CascadeStage, CascadeVerdict, StageResult
from remora.confidence.extractor import extract_confidence, extract_confidence_from_json
from remora.core import Oracle, OracleResponse
from remora.verifier.llm_judge import JudgeOutcome, LLMJudge

_FAST_GATE_PROMPT = """\
Answer the following question as accurately as possible. \
Return ONLY valid JSON with no preamble.

Format: {{"answer": "<your answer>", "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}}

- confidence is your calibrated certainty that the answer is correct (0 = no idea, 1 = certain)
- Keep the answer concise but complete.

Question: {question}"""

_SC_PROMPT = """\
Answer the following question. Return ONLY valid JSON.
Format: {{"answer": "<answer>", "confidence": <0.0-1.0>}}
Question: {question}"""


@dataclass
class _StageContext:
    """Accumulated information passed through stages."""
    question: str
    context: Optional[str] = None
    evidence: Optional[list[str]] = None
    consensus_answer: Optional[str] = None
    consensus_polarity: object = None
    consensus_trust: Optional[float] = None
    consensus_phase: Optional[str] = None
    cascade_confidence: float = 0.5
    last_critique: Optional[str] = None
    oracle_responses: Optional[list[OracleResponse]] = None
    # Per-domain accept threshold override (set by CascadeEngine when a
    # DomainCoverageOptimizer is attached and a domain label is passed to run()).
    domain_accept_threshold: Optional[float] = None
    # Uncertainty decomposition results (populated by CascadeEngine when
    # use_uncertainty_routing=True and uncertainty routing fires).
    uncertainty_epistemic: Optional[float] = None
    uncertainty_aleatoric: Optional[float] = None


class FastGate:
    """Stage 1: single fast oracle + verbalized confidence threshold.

    If the fast oracle expresses high confidence (≥ fast_threshold), the
    pipeline short-circuits here — no further oracle calls needed.
    Cost: 1 oracle call.
    """

    def __init__(self, oracle: Oracle, threshold: float = 0.90) -> None:
        self.oracle = oracle
        self.threshold = threshold

    def run(self, ctx: _StageContext) -> StageResult:
        prompt = _FAST_GATE_PROMPT.format(question=ctx.question)
        response = self.oracle.ask(prompt)

        conf_from_json = extract_confidence_from_json(response.extracted)
        conf_from_text = extract_confidence(response.raw_text)
        raw_conf = conf_from_json if conf_from_json is not None else (conf_from_text or 0.5)

        answer_text = (
            response.extracted.get("answer")
            or response.extracted.get("claim")
            or response.extracted.get("unstructured", "")
        )
        if isinstance(answer_text, dict):
            answer_text = json.dumps(answer_text)

        ctx.consensus_answer = str(answer_text).strip() if answer_text else None
        ctx.cascade_confidence = raw_conf

        if raw_conf >= self.threshold:
            return StageResult(
                stage=CascadeStage.FAST_GATE,
                verdict=CascadeVerdict.ACCEPT,
                confidence=raw_conf,
                oracle_calls=1,
                answer=ctx.consensus_answer,
                stopped=True,
                metadata={"fast_conf": raw_conf, "threshold": self.threshold},
            )

        return StageResult(
            stage=CascadeStage.FAST_GATE,
            verdict=CascadeVerdict.VERIFY,
            confidence=raw_conf,
            oracle_calls=1,
            answer=ctx.consensus_answer,
            stopped=False,
            metadata={"fast_conf": raw_conf, "threshold": self.threshold},
        )


class ConsensusGate:
    """Stage 2: full multi-oracle REMORA consensus with thermodynamic control.

    Wraps the existing Remora engine.  Translates the trust score and phase
    into a cascade verdict:
      trust > accept_threshold  → ACCEPT
      trust < abstain_threshold → ABSTAIN (save Stage 3 call for lost causes)
      otherwise                 → continue to Stage 3
    Cost: typically 3 oracle calls (router gate) to 3×N calls (full iteration).
    """

    def __init__(
        self,
        remora_engine,  # remora.engine.Remora — injected to avoid circular import
        accept_threshold: float = 0.65,
        abstain_threshold: float = 0.12,
        platt_scaler=None,  # Optional[PlattScaler] — late import avoids circular dep
    ) -> None:
        self.engine = remora_engine
        self.accept_threshold = accept_threshold
        self.abstain_threshold = abstain_threshold
        self.platt_scaler = platt_scaler

    def run(self, ctx: _StageContext) -> StageResult:
        state = self.engine.run(ctx.question, ctx.context)
        _report = self.engine.report(state)  # noqa: F841

        trust = None
        phase = None
        thermo = state.last_thermo
        if thermo is not None:
            trust = getattr(thermo, "trust_score", None)
            phase_raw = getattr(thermo, "phase", None)
            phase = phase_raw.value if hasattr(phase_raw, "value") else phase_raw

        oracle_calls = len(state.oracle_log)

        # Extract best candidate answer text from oracle log
        winning_fp = None
        top_support = -1.0
        for fp, sup in state.candidate_support.items():
            if sup > top_support:
                top_support = sup
                winning_fp = fp

        candidate_answer = _extract_answer_from_log(state.oracle_log, winning_fp)
        if candidate_answer:
            ctx.consensus_answer = candidate_answer

        ctx.consensus_trust = trust
        ctx.consensus_phase = phase
        ctx.consensus_polarity = (
            state.candidates[winning_fp].polarity if winning_fp and winning_fp in state.candidates else None
        )
        # Store raw oracle responses so downstream stages (e.g. MoA) can use them
        ctx.oracle_responses = list(state.oracle_log)

        # Apply Platt calibration if a fitted scaler is attached.
        # calibrated_trust is used for all threshold comparisons;
        # raw trust is preserved in metadata for traceability.
        calibrated_trust = trust
        if trust is not None and self.platt_scaler is not None:
            try:
                calibrated_trust = self.platt_scaler.transform([trust])[0]
            except Exception:
                calibrated_trust = trust  # fall back to raw on scaler error

        # Per-domain threshold overrides the global accept threshold.
        effective_accept = ctx.domain_accept_threshold or self.accept_threshold
        conf = calibrated_trust if calibrated_trust is not None else 0.5

        if calibrated_trust is not None and calibrated_trust >= effective_accept:
            verdict = CascadeVerdict.ACCEPT
            stopped = True
        elif calibrated_trust is not None and calibrated_trust < self.abstain_threshold:
            verdict = CascadeVerdict.ABSTAIN
            stopped = True
        else:
            verdict = CascadeVerdict.VERIFY
            stopped = False

        return StageResult(
            stage=CascadeStage.CONSENSUS,
            verdict=verdict,
            confidence=conf,
            oracle_calls=oracle_calls,
            answer=ctx.consensus_answer,
            stopped=stopped,
            metadata={
                "phase": phase,
                "trust": trust,
                "calibrated_trust": calibrated_trust,
                "effective_accept_threshold": effective_accept,
                "top_support": top_support,
            },
        )


class VerifierGate:
    """Stage 3: LLM-as-judge verification of the consensus answer.

    The judge oracle should be a different model family from the consensus
    oracles to maximise independence (e.g., Mistral if consensus used LLaMA).

    Outcomes:
      supported + confidence >= verify_threshold → ACCEPT
      refuted                                   → ABSTAIN
      challenged or low confidence              → continue to Stage 4
    Cost: 1 oracle call.
    """

    def __init__(
        self,
        judge_oracle: Oracle,
        verify_threshold: float = 0.70,
    ) -> None:
        self.judge = LLMJudge(judge_oracle)
        self.verify_threshold = verify_threshold

    def run(self, ctx: _StageContext) -> StageResult:
        answer = ctx.consensus_answer or "(no answer from consensus)"
        verdict_obj = self.judge.evaluate(
            question=ctx.question,
            answer=answer,
            evidence=ctx.evidence,
        )

        conf = verdict_obj.confidence

        if verdict_obj.outcome == JudgeOutcome.SUPPORTED and conf >= self.verify_threshold:
            verdict = CascadeVerdict.ACCEPT
            stopped = True
        elif verdict_obj.outcome == JudgeOutcome.REFUTED:
            verdict = CascadeVerdict.ABSTAIN
            stopped = True
        else:
            # CHALLENGED or PARSE_ERROR or low confidence — escalate to Stage 4
            verdict = CascadeVerdict.VERIFY
            stopped = False

        return StageResult(
            stage=CascadeStage.VERIFIER,
            verdict=verdict,
            confidence=conf,
            oracle_calls=1,
            answer=answer,
            critique=verdict_obj.critique,
            stopped=stopped,
            metadata={
                "judge_outcome": verdict_obj.outcome.value,
                "judge_confidence": conf,
                "verify_threshold": self.verify_threshold,
            },
        )


class SelfConsistencyGate:
    """Stage 4: multi-sample self-consistency from a single oracle.

    Inspired by Wang et al. (2023) "Self-Consistency Improves Chain of Thought
    Reasoning in Language Models."  Makes N independent calls and measures
    answer agreement.  Diversity relies on the model's inherent stochasticity
    (sampling temperature is not controlled through this interface).

    This is always the terminal stage — all three verdicts are final:
    Agreement ≥ sc_threshold  → ACCEPT
    Agreement ∈ [0.5, sc_threshold) → VERIFY  (moderate confidence, pipeline ends)
    Agreement < 0.5           → ABSTAIN
    Cost: sc_samples oracle calls.
    """

    def __init__(
        self,
        oracle: Oracle,
        sc_samples: int = 7,
        sc_threshold: float = 0.72,
    ) -> None:
        self.oracle = oracle
        self.sc_samples = sc_samples
        self.sc_threshold = sc_threshold

    def run(self, ctx: _StageContext) -> StageResult:
        prompt = _SC_PROMPT.format(question=ctx.question)
        answers: list[str] = []
        for _ in range(self.sc_samples):
            resp = self.oracle.ask(prompt)
            ans = _extract_sc_answer(resp)
            if ans:
                answers.append(ans.lower().strip())

        if not answers:
            return StageResult(
                stage=CascadeStage.SELF_CONSISTENCY,
                verdict=CascadeVerdict.ABSTAIN,
                confidence=0.0,
                oracle_calls=self.sc_samples,
                stopped=True,
                metadata={"sc_samples": self.sc_samples, "answers_received": 0},
            )

        # Count majority answer
        from collections import Counter
        counts = Counter(answers)
        majority_answer, majority_count = counts.most_common(1)[0]
        agreement = majority_count / len(answers)
        conf = agreement

        if agreement >= self.sc_threshold:
            verdict = CascadeVerdict.ACCEPT
        elif agreement >= 0.5:
            verdict = CascadeVerdict.VERIFY
        else:
            verdict = CascadeVerdict.ABSTAIN

        # Update ctx with majority answer
        ctx.consensus_answer = majority_answer

        return StageResult(
            stage=CascadeStage.SELF_CONSISTENCY,
            verdict=verdict,
            confidence=conf,
            oracle_calls=self.sc_samples,
            answer=majority_answer,
            stopped=True,
            metadata={
                "sc_samples": self.sc_samples,
                "answers_received": len(answers),
                "agreement": agreement,
                "majority_answer": majority_answer,
                "answer_distribution": dict(counts),
            },
        )


_REVISION_PROMPT = """\
You answered a question, but a reviewer found issues with your answer. \
Please revise your answer to address the critique directly.

Question: {question}
Your previous answer: {answer}
Reviewer critique: {critique}

Improve your answer by addressing the critique — be more precise, complete, and accurate.
Return ONLY valid JSON:
{{"answer": "<revised answer>", "confidence": <0.0-1.0>, "changes": "<one sentence: what you changed>"}}"""


class CritiqueRevisionGate:
    """Stage 3b: critique-driven revision loop (Constitutional AI pattern).

    When Stage 3 (VerifierGate) returns CHALLENGED, this gate feeds the
    judge's critique back to a revision oracle to produce an improved answer,
    then re-evaluates with the judge.  Runs up to max_rounds revision cycles.

    Outcomes:
      revised answer supported + confidence >= verify_threshold → ACCEPT
      revised answer refuted                                    → ABSTAIN
      still challenged after max_rounds                         → VERIFY (proceed to SC)

    Cost: max_rounds × 2 oracle calls (1 revision + 1 judge per round).
    """

    def __init__(
        self,
        revision_oracle: Oracle,
        judge_oracle: Oracle,
        max_rounds: int = 2,
        verify_threshold: float = 0.70,
        skip_high_trust_threshold: float = 0.75,
    ) -> None:
        self.revision_oracle = revision_oracle
        self.judge = LLMJudge(judge_oracle)
        self.max_rounds = max_rounds
        self.verify_threshold = verify_threshold
        self.skip_high_trust_threshold = skip_high_trust_threshold

    def run(self, ctx: _StageContext) -> StageResult:  # noqa: C901
        # ------------------------------------------------------------------
        # Dynamic Iteration Gate (empirical guard against Stage 3b overhead)
        # When Stage 2 already yielded high trust (>= skip_high_trust_threshold)
        # or the consensus phase is ordered, running critique-revision degrades
        # accuracy by ~22 pp on easy questions (NEGATIVE_RESULTS.md §2).
        # Short-circuit immediately and accept the existing consensus answer.
        # ------------------------------------------------------------------
        trust = ctx.consensus_trust
        if trust is not None and trust >= self.skip_high_trust_threshold:
            return StageResult(
                stage=CascadeStage.CRITIQUE_REVISION,
                verdict=CascadeVerdict.ACCEPT,
                confidence=trust,
                oracle_calls=0,
                answer=ctx.consensus_answer,
                stopped=True,
                metadata={
                    "rounds": 0,
                    "skipped": True,
                    "reason": f"high_trust_short_circuit trust={trust:.3f}>={self.skip_high_trust_threshold}",
                },
            )

        # DISORDERED phase: revision amplifies hallucination risk — abort immediately.
        # Trust score is unreliable in the disordered phase; additional oracle calls
        # statistically increase confabulation spread rather than correcting it
        # (NEGATIVE_RESULTS.md §3).  The cascade proceeds to ABSTAIN without revision.
        if ctx.consensus_phase == "disordered":
            return StageResult(
                stage=CascadeStage.CRITIQUE_REVISION,
                verdict=CascadeVerdict.ABSTAIN,
                confidence=trust if trust is not None else 0.0,
                oracle_calls=0,
                answer=ctx.consensus_answer,
                stopped=True,
                metadata={
                    "rounds": 0,
                    "skipped": True,
                    "reason": "disordered_phase_abort",
                },
            )

        # CRITICAL phase: run the full revision loop using the judge critique as a
        # minority challenge.  The judge oracle (independent model family) acts as
        # an adversarial minority view; running all max_rounds maximises correction
        # coverage under thermodynamic uncertainty.
        # (No special branch needed — the existing loop below handles this correctly.)

        answer = ctx.consensus_answer or "(no answer from prior stages)"
        critique = ctx.last_critique or "The answer was challenged — please revise it to be more accurate and complete."

        total_calls = 0
        rounds_done = 0
        last_verdict_obj = None

        for _ in range(self.max_rounds):
            # Ask oracle to revise its answer in light of the critique
            prompt = _REVISION_PROMPT.format(
                question=ctx.question,
                answer=answer,
                critique=critique,
            )
            resp = self.revision_oracle.ask(prompt)
            total_calls += 1

            if resp.error:
                # Oracle failed (network, timeout, etc.) — stop revision, return current best
                break

            revised = (
                resp.extracted.get("answer")
                or resp.extracted.get("claim")
                or resp.raw_text[:300]
            )
            if isinstance(revised, dict):
                revised = json.dumps(revised)
            revised = str(revised).strip() or answer

            # Re-judge the revised answer
            verdict_obj = self.judge.evaluate(
                question=ctx.question,
                answer=revised,
                evidence=ctx.evidence,
            )
            total_calls += 1
            rounds_done += 1
            last_verdict_obj = verdict_obj

            # Update context so subsequent stages see the latest revision
            ctx.consensus_answer = revised
            ctx.last_critique = verdict_obj.critique

            if verdict_obj.outcome == JudgeOutcome.SUPPORTED and verdict_obj.confidence >= self.verify_threshold:
                return StageResult(
                    stage=CascadeStage.CRITIQUE_REVISION,
                    verdict=CascadeVerdict.ACCEPT,
                    confidence=verdict_obj.confidence,
                    oracle_calls=total_calls,
                    answer=revised,
                    critique=verdict_obj.critique,
                    stopped=True,
                    metadata={"rounds": rounds_done, "judge_outcome": verdict_obj.outcome.value},
                )

            if verdict_obj.outcome == JudgeOutcome.REFUTED:
                return StageResult(
                    stage=CascadeStage.CRITIQUE_REVISION,
                    verdict=CascadeVerdict.ABSTAIN,
                    confidence=verdict_obj.confidence,
                    oracle_calls=total_calls,
                    answer=revised,
                    critique=verdict_obj.critique,
                    stopped=True,
                    metadata={"rounds": rounds_done, "judge_outcome": verdict_obj.outcome.value},
                )

            # CHALLENGED — update answer and critique for next round
            answer = revised
            critique = verdict_obj.critique

        # Still challenged after max_rounds — continue to Stage 4
        final_conf = last_verdict_obj.confidence if last_verdict_obj else 0.5
        final_critique = last_verdict_obj.critique if last_verdict_obj else critique
        return StageResult(
            stage=CascadeStage.CRITIQUE_REVISION,
            verdict=CascadeVerdict.VERIFY,
            confidence=final_conf,
            oracle_calls=total_calls,
            answer=ctx.consensus_answer,
            critique=final_critique,
            stopped=False,
            metadata={
                "rounds": rounds_done,
                "max_rounds": self.max_rounds,
                "judge_outcome": last_verdict_obj.outcome.value if last_verdict_obj else "none",
            },
        )


def _extract_answer_from_log(oracle_log: list[OracleResponse], winning_fp: Optional[str]) -> Optional[str]:
    """Return the claim text from the oracle response whose canonical fingerprint matches winning_fp.

    Iterates the log in reverse (most recent first) and returns the first claim whose
    phi fingerprint equals winning_fp.  Falls back to the most recent claim with a
    "claim" field if no fingerprint match is found (e.g. winning_fp is None).
    """
    first_claim: Optional[str] = None
    for resp in reversed(oracle_log):
        claim = resp.extracted.get("claim")
        if not (claim and isinstance(claim, str)):
            continue
        claim = claim.strip()
        if first_claim is None:
            first_claim = claim
        if winning_fp is None:
            return claim
        try:
            if _phi(resp.extracted).fingerprint() == winning_fp:
                return claim
        except Exception:
            pass
    return first_claim


def _extract_sc_answer(resp: OracleResponse) -> Optional[str]:
    """Extract answer from a self-consistency oracle response."""
    ans = resp.extracted.get("answer")
    if ans is not None:
        return str(ans)
    claim = resp.extracted.get("claim")
    if claim:
        return str(claim)
    unstructured = resp.extracted.get("unstructured", "")
    if unstructured and unstructured != resp.raw_text[:50]:
        return str(unstructured)[:100]
    return None


# ---------------------------------------------------------------------------
# Stage 6: Mixture-of-Agents Synthesizer
# ---------------------------------------------------------------------------

_MOA_SYNTHESIS_PROMPT = """\
You are a synthesis oracle.  {k} independent AI assistants have each answered
the question below.  Study all their answers, identify where they agree and
disagree, and produce the single most accurate, well-reasoned final answer.

Question: {question}

{oracle_responses}

Synthesize the best answer. Return ONLY valid JSON:
{{"answer": "<synthesized answer>", "confidence": <0.0-1.0>,
  "consensus": "<agree|partial|disagree>",
  "reasoning": "<one sentence: why this is the best answer>"}}"""


class MixtureOfAgentsSynth:
    """Stage 6: Mixture-of-Agents (MoA) synthesis oracle.

    Implements Wang et al. (2024) "Mixture-of-Agents Enhances Large Language
    Model Capabilities" for the REMORA cascade.  After K oracle agents each
    produce an independent answer (captured in the engine's oracle_log), a
    dedicated *synthesis oracle* (ideally from a different model family) reads
    all K raw answers together and produces a single synthesized response.

    Empirically, MoA outperforms majority voting by 8–15 pp on MMLU
    (Wang et al., 2024) because the synthesizer can reconcile partial
    agreements and filter confidently-wrong answers that happen to form a
    majority.

    When to use
    -----------
    - As an *optional* enhancement to ConsensusGate when the stage returns
      CascadeVerdict.VERIFY (trust is ambiguous but not hopeless).
    - As a *replacement* for SelfConsistencyGate when the synthesis oracle is
      a stronger model than the pool oracles.
    - At full pipeline termination when all other stages return ABSTAIN.

    Cost: 1 additional oracle call (the synthesis call).

    Parameters
    ----------
    synthesis_oracle:
        The oracle that synthesizes the pool answers.  Should be a different
        model family from the pool to maximise independent perspective.
    accept_threshold:
        Confidence threshold above which the synthesized answer is accepted.
    include_reasoning:
        If True, include each oracle's reasoning trace in the synthesis prompt
        (requires that oracle responses contain a "reasoning" field).
    """

    def __init__(
        self,
        synthesis_oracle: Oracle,
        accept_threshold: float = 0.65,
        include_reasoning: bool = True,
    ) -> None:
        self.synthesis_oracle = synthesis_oracle
        self.accept_threshold = accept_threshold
        self.include_reasoning = include_reasoning

    def run(self, ctx: _StageContext, oracle_responses: Optional[list[OracleResponse]] = None) -> StageResult:
        """Run the MoA synthesis stage.

        Parameters
        ----------
        ctx:
            Accumulated cascade context (question, consensus_answer, etc.).
        oracle_responses:
            Raw oracle responses from ConsensusGate's engine run.  If None,
            falls back to a single-oracle synthesis based on ctx.consensus_answer.
        """
        responses = oracle_responses or []

        # Build per-oracle response summaries for the synthesis prompt
        oracle_blocks: list[str] = []
        for i, resp in enumerate(responses, 1):
            answer_text = (
                resp.extracted.get("claim")
                or resp.extracted.get("answer")
                or resp.extracted.get("unstructured", "")
            )
            if isinstance(answer_text, dict):
                answer_text = json.dumps(answer_text)
            answer_text = str(answer_text).strip()[:300] if answer_text else "(no answer)"

            if self.include_reasoning:
                reasoning = resp.extracted.get("reasoning") or resp.extracted.get("rationale") or ""
                reasoning = str(reasoning).strip()[:200] if reasoning else ""
                block = f"Assistant {i} ({resp.provider}):\n  Answer: {answer_text}"
                if reasoning:
                    block += f"\n  Reasoning: {reasoning}"
            else:
                block = f"Assistant {i} ({resp.provider}): {answer_text}"

            oracle_blocks.append(block)

        # If no oracle responses were available, use the accumulated consensus answer
        if not oracle_blocks and ctx.consensus_answer:
            oracle_blocks = [f"Assistant 1 (consensus): {ctx.consensus_answer}"]

        oracle_responses_text = "\n\n".join(oracle_blocks) if oracle_blocks else "No individual answers available."

        prompt = _MOA_SYNTHESIS_PROMPT.format(
            k=len(oracle_blocks),
            question=ctx.question,
            oracle_responses=oracle_responses_text,
        )

        synth_resp = self.synthesis_oracle.ask(prompt)

        if synth_resp.error:
            # Synthesis oracle failed — fall back to consensus answer, mark as VERIFY
            return StageResult(
                stage=CascadeStage.MOA_SYNTH,
                verdict=CascadeVerdict.VERIFY,
                confidence=ctx.consensus_trust or 0.5,
                oracle_calls=1,
                answer=ctx.consensus_answer,
                stopped=False,
                metadata={"error": synth_resp.error, "fallback": True},
            )

        # Extract synthesized answer
        synth_answer = (
            synth_resp.extracted.get("answer")
            or synth_resp.extracted.get("claim")
            or synth_resp.extracted.get("unstructured", "")
        )
        if isinstance(synth_answer, dict):
            synth_answer = json.dumps(synth_answer)
        synth_answer = str(synth_answer).strip() if synth_answer else ctx.consensus_answer

        # Extract confidence
        conf_raw = synth_resp.extracted.get("confidence")
        try:
            conf = float(conf_raw) if conf_raw is not None else 0.5
            conf = max(0.0, min(1.0, conf))
        except (TypeError, ValueError):
            conf = 0.5

        consensus_label = str(synth_resp.extracted.get("consensus", "unknown")).lower()
        reasoning = str(synth_resp.extracted.get("reasoning", "")).strip()

        # Update context
        ctx.consensus_answer = synth_answer

        if conf >= self.accept_threshold:
            verdict = CascadeVerdict.ACCEPT
            stopped = True
        else:
            verdict = CascadeVerdict.ABSTAIN
            stopped = True

        return StageResult(
            stage=CascadeStage.MOA_SYNTH,
            verdict=verdict,
            confidence=conf,
            oracle_calls=1,
            answer=synth_answer,
            stopped=stopped,
            metadata={
                "synthesis_oracle": self.synthesis_oracle.name,
                "n_inputs": len(oracle_blocks),
                "consensus_label": consensus_label,
                "reasoning": reasoning,
                "accept_threshold": self.accept_threshold,
            },
        )
