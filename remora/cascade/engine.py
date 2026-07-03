# Author: Stian Skogbrott
# License: Apache-2.0
"""CascadeEngine — multi-stage verification pipeline for REMORA.

Architecture
------------
Stage 1  FastGate           1 oracle call — verbalized confidence gate.
                            Stops if the fast oracle is ≥ fast_threshold confident.

Stage 2  ConsensusGate      Full 3-oracle REMORA consensus + thermodynamic
                            phase classification.  Stops on high trust or total disorder.

Stage 3  VerifierGate       LLM-as-judge evaluates the consensus answer against
                            retrieved evidence.  Stops on supported or refuted.

Stage 3b CritiqueRevision   When Stage 3 returns CHALLENGED, feeds the judge's
                            critique back to a revision oracle (Constitutional AI).
                            Re-judges the revised answer.  Up to max_rounds cycles.

Stage 4  SelfConsistency    N independent samples from a single oracle; majority
                            answer + agreement rate decides final verdict.

Stage 6  MoA Synth          Optional — requires synthesis_oracle.  Aggregates
                            all prior oracle responses through a dedicated synthesis
                            oracle.  Runs when the pipeline has not yet reached a
                            terminal ACCEPT/ABSTAIN verdict after Stage 4.

Each stage can short-circuit (stop=True) before the next stage runs.
A budget_oracle_calls cap halts the pipeline early and returns VERIFY
if the budget is exhausted before a terminal verdict is reached.

Usage
-----
    from remora.cascade import CascadeEngine
    from remora.oracles.groq import GroqOracle
    from remora.oracles.openrouter import OpenRouterOracle
    from remora.genome import Genome

    fast  = GroqOracle("llama-3.1-8b-instant")
    cons  = [GroqOracle("llama-3.1-8b-instant"),
             GroqOracle("llama-3.3-70b-versatile"),
             OpenRouterOracle("google/gemma-4-27b-it:free")]
    judge = OpenRouterOracle("mistralai/mistral-7b-instruct:free")

    engine = CascadeEngine(
        consensus_oracles=cons,
        judge_oracle=judge,
        fast_oracle=fast,
        genome=Genome(enable_routing=True, enable_thermodynamic_control=True),
    )
    result = engine.run("Is the boiling point of water 100°C at sea level?")
    print(result.summary())
"""
from __future__ import annotations

from typing import Optional, Sequence

from remora.calibration.domain_optimizer import DomainCoverageOptimizer
from remora.calibration.platt_scaler import PlattScaler
from remora.cascade.result import CascadeResult, CascadeStage, CascadeVerdict, StageResult
from remora.cascade.stages import (
    ConsensusGate,
    CritiqueRevisionGate,
    FastGate,
    MixtureOfAgentsSynth,
    SelfConsistencyGate,
    VerifierGate,
    _StageContext,
)
from remora.core import Oracle, OracleResponse
from remora.genome import Genome
from remora.oracles.diversity import OracleDiversityTracker, select_diverse_swarm
from remora.uncertainty.decompose import decompose


def _extract_oracle_probs(oracle_responses: list[OracleResponse]) -> list[float]:
    """Extract per-oracle confidence probabilities for uncertainty decomposition.

    Looks for a ``confidence`` or ``polarity_prob`` field in the extracted dict
    of each OracleResponse.  Skips error responses and entries with no parseable
    numeric field.
    """
    probs: list[float] = []
    for resp in oracle_responses:
        if resp.error:
            continue
        val = resp.extracted.get("confidence") or resp.extracted.get("polarity_prob")
        if val is not None:
            try:
                probs.append(float(val))
            except (TypeError, ValueError):
                pass
    return probs


class CascadeEngine:
    """Adaptive multi-stage cascade for question answering with quality gates.

    .. warning::
       **Answer-quality only — NOT an execution-authorization component.**
       ``run()`` takes a question/context/evidence/domain and its ``FastGate``
       can return ``ACCEPT`` from a single oracle's self-reported confidence
       (>= ``fast_threshold``). That ``ACCEPT`` means "this answer is high
       quality", NOT "this tool call may execute". It carries no
       ``PolicyObservation``, ``action_type``, ``risk_tier``, or tenant, and
       must never gate a real tool call. Actuation must go through
       ``remora.policy.RemoraDecisionEngine.decide()`` (the deterministic
       policy floor). External security audit CLAIM 2 confirmed this component
       is not on any enforcement path; ``tests/test_cascade_not_authorization.py``
       keeps it that way.

    Parameters
    ----------
    consensus_oracles:
        Pool of oracles for the Stage 2 consensus (typically 3, from different families).
    judge_oracle:
        Single oracle used by the Stage 3 LLM judge.  Should be a different model
        family from the consensus oracles for maximum independence.
    fast_oracle:
        Single oracle for the Stage 1 fast gate.  Defaults to consensus_oracles[0].
    genome:
        REMORA genome passed to the Stage 2 consensus engine.
        Recommended: enable_routing=True, enable_thermodynamic_control=True.
    fast_threshold:
        Verbalized confidence ≥ this → accept at Stage 1 (default 0.90).
    consensus_accept_threshold:
        Trust score ≥ this → accept at Stage 2 (default 0.65).
    consensus_abstain_threshold:
        Trust score < this at Stage 2 → abstain without calling Stage 3 (default 0.12).
    verify_threshold:
        Judge confidence ≥ this for a "supported" verdict → accept at Stage 3 (default 0.70).
    sc_samples:
        Number of independent samples in Stage 4 (default 7).
    sc_threshold:
        Agreement rate ≥ this → accept at Stage 4 (default 0.72).
    max_stages:
        Maximum number of main stages to run (1–4, default 4).
        When synthesis_oracle is provided, Stage 6 (MoA Synth) runs
        automatically after Stage 4 if no ACCEPT/ABSTAIN was reached.
        Setting max_stages < 4 suppresses earlier stage(s) as before.
    budget_oracle_calls:
        Hard cap on total oracle calls across all stages.  When hit, the pipeline
        returns a VERIFY verdict with the best answer seen so far.
    critique_max_rounds:
        Maximum number of critique-revision cycles in Stage 3b (default 2).
        Each round costs 2 oracle calls (1 revision + 1 judge).

        **Empirical note — short-circuit necessity (Negative Result #2):**
        Running ≥2 critique-revision rounds on *easy* questions (low uncertainty,
        ordered phase) degrades accuracy by ~22 percentage points versus accepting
        the Stage 2 consensus answer directly
        (``experiments/chi_iteration_utility.py``).
        This "overthinking" effect is the empirical justification for the cascade's
        short-circuit design: Stage 3b is only reached when Stages 1 and 2 have
        already flagged genuine uncertainty.  Do not lower ``critique_max_rounds``
        to 0 — instead, adjust ``consensus_accept_threshold`` so that easy
        questions are accepted at Stage 2 and never reach Stage 3b.
    synthesis_oracle:
        Optional oracle for Stage 6 (Mixture-of-Agents synthesis).  When
        provided, this oracle reads all prior oracle responses and produces a
        single synthesized answer.  Should be a different model family from
        the consensus oracles.  If None (default), Stage 6 is skipped.
    moa_accept_threshold:
        Synthesis confidence ≥ this → ACCEPT at Stage 6 (default 0.65).
    revision_oracle:
        Oracle used by Stage 3b for answer revision.  Defaults to fast_oracle
        (or consensus_oracles[0] if fast_oracle is None).  Pass a dedicated
        oracle to maximise independence from the Stage 1 fast-gate oracle.
    platt_scaler:
        Optional :class:`~remora.calibration.platt_scaler.PlattScaler` fitted
        on a labelled calibration set.  When provided, raw consensus trust
        scores are mapped to calibrated posterior probabilities before the
        accept/abstain threshold comparison in Stage 2.  This repairs the
        conformal-guarantee failure documented in NEGATIVE_RESULTS.md §5.
    oracle_names:
        Optional list of string identifiers, one per oracle in
        ``consensus_oracles`` (same order).  Required for diversity selection.
    diversity_tracker:
        Optional :class:`~remora.oracles.diversity.OracleDiversityTracker`
        with historical pairwise agreement data.  When provided together with
        ``oracle_names``, the engine selects the ``diversity_k`` most-diverse
        oracles from the pool before building the consensus engine.
    diversity_k:
        Target swarm size for diversity selection (default 3).  Ignored when
        ``diversity_tracker`` or ``oracle_names`` is None, or when the pool
        is already ≤ diversity_k oracles.
    domain_optimizer:
        Optional :class:`~remora.calibration.domain_optimizer.DomainCoverageOptimizer`
        fitted on a labelled benchmark.  When provided and ``domain`` is
        passed to :meth:`run`, the per-domain precision-optimal threshold
        overrides ``consensus_accept_threshold`` for that call.
    use_uncertainty_routing:
        When True, decompose Stage 2 VERIFY oracle pools into epistemic and
        aleatoric uncertainty and escalate to human review when the
        decomposition recommends it (see
        :func:`~remora.uncertainty.decompose.decompose`).
    """

    def __init__(
        self,
        consensus_oracles: Sequence[Oracle],
        judge_oracle: Optional[Oracle] = None,
        fast_oracle: Optional[Oracle] = None,
        revision_oracle: Optional[Oracle] = None,
        synthesis_oracle: Optional[Oracle] = None,
        genome: Optional[Genome] = None,
        fast_threshold: float = 0.90,
        consensus_accept_threshold: float = 0.65,
        consensus_abstain_threshold: float = 0.12,
        verify_threshold: float = 0.70,
        sc_samples: int = 7,
        sc_threshold: float = 0.72,
        max_stages: int = 4,
        budget_oracle_calls: Optional[int] = None,
        critique_max_rounds: int = 2,
        moa_accept_threshold: float = 0.65,
        # ── Runtime calibration & routing helpers ───────────────────────────────────────────
        platt_scaler: Optional[PlattScaler] = None,
        oracle_names: Optional[Sequence[str]] = None,
        diversity_tracker: Optional[OracleDiversityTracker] = None,
        diversity_k: int = 3,
        domain_optimizer: Optional[DomainCoverageOptimizer] = None,
        use_uncertainty_routing: bool = False,
    ) -> None:
        if not consensus_oracles:
            raise ValueError("At least one consensus oracle is required.")

        from remora.engine import Remora
        from remora.genome import Genome as _Genome

        _genome = genome or _Genome(enable_routing=True, enable_thermodynamic_control=True)

        # Oracle diversity selection: when a tracker + names are supplied with a
        # pool larger than diversity_k, select the most-diverse subset.
        _oracles = list(consensus_oracles)
        if (
            diversity_tracker is not None
            and oracle_names is not None
            and len(oracle_names) == len(_oracles)
            and len(_oracles) > diversity_k
        ):
            selected_names = select_diverse_swarm(
                list(oracle_names), diversity_tracker, k=diversity_k
            )
            _name_to_oracle = dict(zip(oracle_names, _oracles))
            _oracles = [_name_to_oracle[n] for n in selected_names if n in _name_to_oracle]

        _fast = fast_oracle or _oracles[0]
        _judge = judge_oracle or _oracles[-1]
        _revision = revision_oracle or _fast

        self._fast_gate = FastGate(_fast, threshold=fast_threshold)
        self._consensus_gate = ConsensusGate(
            remora_engine=Remora(_oracles, _genome),
            accept_threshold=consensus_accept_threshold,
            abstain_threshold=consensus_abstain_threshold,
            platt_scaler=platt_scaler,
        )
        self._verifier_gate = VerifierGate(_judge, verify_threshold=verify_threshold)
        self._critique_gate = CritiqueRevisionGate(
            revision_oracle=_revision,
            judge_oracle=_judge,
            max_rounds=critique_max_rounds,
            verify_threshold=verify_threshold,
            skip_high_trust_threshold=consensus_accept_threshold,
        )
        self._sc_gate = SelfConsistencyGate(_fast, sc_samples=sc_samples, sc_threshold=sc_threshold)

        # Stage 6 — optional MoA synthesis
        self._moa_gate: Optional[MixtureOfAgentsSynth] = (
            MixtureOfAgentsSynth(synthesis_oracle, accept_threshold=moa_accept_threshold)
            if synthesis_oracle is not None
            else None
        )

        self.max_stages = max(1, min(4, max_stages))
        self.budget = budget_oracle_calls
        self._domain_optimizer = domain_optimizer
        self._use_uncertainty_routing = use_uncertainty_routing

    def run(
        self,
        question: str,
        context: Optional[str] = None,
        evidence: Optional[list[str]] = None,
        domain: Optional[str] = None,
    ) -> CascadeResult:
        """Run the cascade and return a CascadeResult.

        Parameters
        ----------
        question:
            The question or claim to evaluate.
        context:
            Optional document context passed to Stage 2 and the verifier.
        evidence:
            Optional list of evidence strings passed to the verifier.
        domain:
            Optional domain label (e.g. ``"science"``, ``"legal"``).
            When a ``domain_optimizer`` is attached, the engine uses the
            per-domain precision-optimal threshold instead of the global
            ``consensus_accept_threshold``.
        """
        ctx = _StageContext(question=question, context=context, evidence=evidence)

        # Domain-specific accept threshold: override the global threshold when
        # a DomainCoverageOptimizer is attached and a domain label is given.
        if self._domain_optimizer is not None and domain is not None:
            ctx.domain_accept_threshold = self._domain_optimizer.threshold(domain)

        stages_run: list[StageResult] = []
        total_calls = 0

        stage_runners = [
            (CascadeStage.FAST_GATE, self._fast_gate.run),
            (CascadeStage.CONSENSUS, self._consensus_gate.run),
            (CascadeStage.VERIFIER, self._verifier_gate.run),
            (CascadeStage.SELF_CONSISTENCY, self._sc_gate.run),
        ][: self.max_stages]

        for stage_enum, runner in stage_runners:
            if self.budget is not None and total_calls >= self.budget:
                # Budget exhausted — return best effort
                return self._build_result(stages_run, CascadeVerdict.VERIFY, ctx, total_calls)

            result = runner(ctx)
            stages_run.append(result)
            total_calls += result.oracle_calls

            if result.stopped:
                # ACCEPT is always final — return immediately.
                # For non-ACCEPT terminal verdicts (ABSTAIN/ESCALATE) from Stage 4,
                # give MoA a last-resort synthesis opportunity before giving up.
                if result.verdict == CascadeVerdict.ACCEPT:
                    return self._build_result(stages_run, result.verdict, ctx, total_calls)
                if (
                    self._moa_gate is not None
                    and stage_enum == CascadeStage.SELF_CONSISTENCY
                    and (self.budget is None or total_calls < self.budget)
                ):
                    moa = self._moa_gate.run(ctx, oracle_responses=ctx.oracle_responses)
                    stages_run.append(moa)
                    total_calls += moa.oracle_calls
                    return self._build_result(stages_run, moa.verdict, ctx, total_calls)
                return self._build_result(stages_run, result.verdict, ctx, total_calls)

            # Uncertainty decomposition routing — fires after Stage 2 VERIFY.
            # Decomposes oracle pool confidence into epistemic + aleatoric
            # components; escalates to human review when recommended.
            if (
                self._use_uncertainty_routing
                and stage_enum == CascadeStage.CONSENSUS
                and not result.stopped
                and ctx.oracle_responses
            ):
                probs = _extract_oracle_probs(ctx.oracle_responses)
                if len(probs) >= 2:
                    est = decompose(probs)
                    ctx.uncertainty_epistemic = est.epistemic
                    ctx.uncertainty_aleatoric = est.aleatoric
                    if est.action in ("escalate_human", "escalate_adversarial"):
                        return self._build_result(
                            stages_run, CascadeVerdict.ESCALATE, ctx, total_calls
                        )
                    # action == "add_oracles" → continue to Stage 3
                    # action == "accept"      → continue (let Stage 3 confirm)

            # Stage 3b: when Stage 3 (Verifier) returns CHALLENGED (not PARSE_ERROR),
            # run critique-revision before Stage 4 (Self-Consistency).
            # Skip when the judge couldn't parse a verdict — there is no actionable
            # critique to feed back, so proceed directly to SC.
            if (
                stage_enum == CascadeStage.VERIFIER
                and result.metadata.get("judge_outcome") != "parse_error"
            ):
                if result.critique:
                    ctx.last_critique = result.critique
                if self.budget is None or total_calls < self.budget:
                    cr = self._critique_gate.run(ctx)
                    stages_run.append(cr)
                    total_calls += cr.oracle_calls
                    if cr.stopped:
                        return self._build_result(stages_run, cr.verdict, ctx, total_calls)

        # All stages ran without a terminal verdict — try MoA synthesis if available
        if self._moa_gate is not None:
            if self.budget is None or total_calls < self.budget:
                moa = self._moa_gate.run(ctx, oracle_responses=ctx.oracle_responses)
                stages_run.append(moa)
                total_calls += moa.oracle_calls
                return self._build_result(stages_run, moa.verdict, ctx, total_calls)

        # No terminal verdict and no MoA — return VERIFY
        last = stages_run[-1] if stages_run else None
        verdict = last.verdict if last else CascadeVerdict.ABSTAIN
        return self._build_result(stages_run, verdict, ctx, total_calls)

    def _build_result(
        self,
        stages: list[StageResult],
        verdict: CascadeVerdict,
        ctx: _StageContext,
        total_calls: int,
    ) -> CascadeResult:
        # Confidence = last stage's confidence, or mean of all stages
        if stages:
            conf = stages[-1].confidence
        else:
            conf = 0.0

        critique = next(
            (s.critique for s in reversed(stages) if s.critique), None
        )

        return CascadeResult(
            final_verdict=verdict,
            final_confidence=conf,
            answer=ctx.consensus_answer,
            critique=critique,
            stages_run=stages,
            total_oracle_calls=total_calls,
            stopped_at_stage=stages[-1].stage.value if stages else 0,
            uncertainty_epistemic=ctx.uncertainty_epistemic,
            uncertainty_aleatoric=ctx.uncertainty_aleatoric,
        )
