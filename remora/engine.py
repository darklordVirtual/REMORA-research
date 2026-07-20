# Author: Stian Skogbrott
# License: Apache-2.0
"""Multi-oracle consensus engine for REMORA."""
from __future__ import annotations
import hashlib
import json
from collections import defaultdict
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, wait

_logger = logging.getLogger(__name__)
from dataclasses import dataclass, field, replace
from typing import Optional, Sequence

from remora.layers import adaptive_decompose
from remora.canonical import CanonicalVerdict, phi
from remora.correlation import CorrelationMatrix, weighted_consensus
from remora.genome import Genome, RouterMode
from remora.lyapunov import (LyapunovController, LyapunovParams, state_from_consensus)
from remora.core import Oracle, OracleResponse
from remora.evidence.evidence_types import EvidenceSignal
from remora.evidence.evidence_router import CriticalEvidenceRouter
from remora.evidence.provider import (
    EvidenceProvider,
    EvidenceProviderResult,
    OracleProxyEvidenceProvider,
)

@dataclass
class RemoraState:
    question: str
    iteration: int = 0
    candidates: dict[str, CanonicalVerdict] = field(default_factory=dict)
    candidate_support: dict[str, float] = field(default_factory=dict)
    falsified: set[str] = field(default_factory=set)
    cumulative_cost: float = 0.0
    allow_exploration: bool = False
    controller: LyapunovController = field(default_factory=lambda: LyapunovController.init(LyapunovParams()))
    oracle_log: list[OracleResponse] = field(default_factory=list)
    consensus_log: list[dict] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    require_rag: bool = False
    refuse_parametric_verdict: bool = False
    evidence_request_reason: str | None = None
    last_thermo: object = None
    # Enterprise request context (filled by caller via run())
    domain: str | None = None
    risk_tier: str | None = None
    action_type: str | None = None
    target_environment: str | None = None
    external_evidence: list[dict] = field(default_factory=list)
    # v0.9 governance context — caller-supplied; engine populates what it can detect
    session_id: str | None = None
    session_action_count: int | None = None
    session_cumulative_risk: float | None = None
    fleet_level_effect: str | None = None
    policy_generalization_risk: float | None = None
    similar_action_seen_count: int | None = None
    environment_confidence: float | None = None
    model_misspecification_risk: float | None = None
    classification_confidence: float | None = None
    coercion_detected: bool = False

class Remora:
    """Multi-oracle consensus engine with Lyapunov stability control."""
    def __init__(
        self,
        oracles: Sequence[Oracle],
        genome: Genome,
        correlation: Optional[CorrelationMatrix] = None,
        oracle_timeout_s: float = 15.0,
        min_valid_oracles: int = 2,
        max_decision_time_s: float | None = None,
        evidence_provider: EvidenceProvider | None = None,
        retrieval_evidence_provider: EvidenceProvider | None = None,
    ):
        if len(oracles) < 2:
            raise ValueError("Remora requires at least 2 oracles")
        self.oracles = list(oracles)
        self.genome = genome
        self.correlation = correlation or CorrelationMatrix(window_size=200)
        self.oracle_timeout_s = oracle_timeout_s
        self.min_valid_oracles = min_valid_oracles
        self.max_decision_time_s = max_decision_time_s
        self.evidence_provider = evidence_provider or OracleProxyEvidenceProvider(
            mean_rho_fn=self._mean_rho
        )
        self.retrieval_evidence_provider = retrieval_evidence_provider
        # CR-4: session-level stop event; set when oracle deadline fires so that
        # any oracle calls queued but not yet started are rejected immediately.
        # Oracle implementations that accept a stop_event should also check it
        # during long-running HTTP calls to exit cooperatively.
        self._stop_event: threading.Event = threading.Event()

    def _genome_to_lyapunov_params(self) -> LyapunovParams:
        g = self.genome
        return LyapunovParams(lambda_dissensus=g.negation_weight,
            mu_cost=g.divergent_boost*0.1,
            epsilon_tolerance=max(0.0, g.entropy_abort_ratio - 1.0), min_window=2)

    def _mean_rho(self, providers: list[str]) -> float:
        """Return mean pairwise rho across the supplied providers."""
        if len(providers) < 2:
            return 0.0
        values = []
        for i in range(len(providers)):
            for j in range(i + 1, len(providers)):
                values.append(self.correlation.rho(providers[i], providers[j]))
        return sum(values) / len(values) if values else 0.0

    @staticmethod
    def _detect_adversarial_input(text: str) -> bool:
        """Admission firewall: delegate to remora.safety.adversarial.

        SEC-2: Full normalisation pipeline including NFKC, zero-width strip,
        leet-speak substitution, base64 scan, and AST-backed shell/SQL detection.
        """
        from remora.safety.adversarial import detect_adversarial
        return detect_adversarial(text)

    @staticmethod
    def _detect_coercion(text: str) -> bool:
        """Heuristic coercion/blackmail signal from question text.

        Looks for linguistic patterns that indicate the requester is coercing or
        blackmailing the agent into executing an action.  False negatives are
        acceptable — this is a best-effort heuristic, not a hard proof.  Hard
        proof requires the caller to set coercion_detected=True directly.
        """
        import re
        _COERCION_PATTERNS = re.compile(
            r"(if\s+you\s+don.t|unless\s+you|or\s+i\s+will|i\s+will\s+(threaten|leak|destroy|expose|report|publish)|"
            r"blackmail|coerce|extort|you\s+must\s+.+\s+or\s+i)",
            re.IGNORECASE,
        )
        return bool(_COERCION_PATTERNS.search(text))

    # Irreversible action types — rollback_available defaults to False for these.
    _IRREVERSIBLE_ACTION_TYPES: frozenset[str] = frozenset({
        "destructive_write", "delete", "irreversible_delete",
        "emergency_write", "financial_write",
    })

    def _ask_parallel(
        self,
        prompt: str,
        *,
        deadline_monotonic: float | None = None,
    ) -> list[OracleResponse]:
        """Fan out prompt to all oracles in parallel via ThreadPoolExecutor.

        Returns responses in provider-registration order to preserve
determinism.  Falls back to sequential execution on error.

        A request-local stop event is created per fan-out (and mirrored to
        ``_stop_event`` for observability) and is set when the deadline fires so
        that oracle calls which are still queued are rejected without waiting
        for a thread to become available.  Already-running threads complete
        naturally (CPython cannot forcibly terminate threads), but no new
        oracle fan-outs will start after the event is set.
        """
        if len(self.oracles) < 2:
            return [o.ask(prompt) for o in self.oracles]

        # Request-local: a shared event would let concurrent assessments
        # clear/set each other's deadline state (external review REM-036).
        stop = threading.Event()
        self._stop_event = stop  # kept for observability/backward-compat

        timeout_s = self.oracle_timeout_s
        if deadline_monotonic is not None:
            remaining = max(0.0, deadline_monotonic - time.monotonic())
            if remaining <= 0.0:
                return [
                    OracleResponse(
                        provider=o.name,
                        raw_text="",
                        extracted={"unstructured": ""},
                        error="global deadline exceeded",
                    )
                    for o in self.oracles
                ]
            timeout_s = min(timeout_s, remaining)

        def _guarded(oracle: Oracle) -> OracleResponse:
            """Check the stop event before delegating to the oracle."""
            if stop.is_set():
                return OracleResponse(
                    provider=oracle.name,
                    raw_text="",
                    extracted={"unstructured": ""},
                    error="deadline_exceeded",
                )
            return oracle.ask(prompt)

        results: dict[int, OracleResponse] = {}
        pool = ThreadPoolExecutor(max_workers=len(self.oracles))
        try:
            future_map = {
                pool.submit(_guarded, o): i
                for i, o in enumerate(self.oracles)
            }
            done, not_done = wait(future_map, timeout=timeout_s)
            for future in done:
                idx = future_map[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    oracle = self.oracles[idx]
                    _logger.warning("remora.engine: oracle '%s' raised %s", oracle.name, e)
                    results[idx] = OracleResponse(
                        provider=oracle.name,
                        raw_text="",
                        extracted={"unstructured": ""},
                        error=str(e),
                    )
            for future in not_done:
                idx = future_map[future]
                oracle = self.oracles[idx]
                _logger.warning(
                    "remora.engine: oracle '%s' timed out after %.3fs",
                    oracle.name, timeout_s,
                )
                # Signal all queued-but-not-started calls to abort.  Already
                # running calls complete in their thread; we do not block.
                stop.set()
                future.cancel()
                results[idx] = OracleResponse(
                    provider=oracle.name,
                    raw_text="",
                    extracted={"unstructured": ""},
                    error=f"timeout after {timeout_s}s",
                )
        except Exception as exc:
            # Fail closed. A sequential fallback can violate request deadlines.
            _logger.warning(
                "remora.engine: parallel fan-out failed (%s) — returning oracle error stubs",
                exc,
            )
            stop.set()
            for i, oracle in enumerate(self.oracles):
                results[i] = OracleResponse(
                    provider=oracle.name,
                    raw_text="",
                    extracted={"unstructured": ""},
                    error=f"parallel fan-out failure: {type(exc).__name__}",
                )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        # Preserve provider-registration order
        return [results[i] for i in range(len(self.oracles))]

    def _build_positive_prompt(self, sub_q: str, context: Optional[str]) -> str:
        ctx = f"\nContext:\n{context}\n" if context else ""
        return (f"{ctx}Answer the question below. Return ONLY valid JSON.\n"
            'Format: {"claim": "<specific statement>", "answer": true|false|null, "confidence": 0.0-1.0}\n\n'
            f"Question: {sub_q}\n\nJSON:")

    def _build_negative_prompt(self, sub_q: str, context: Optional[str]) -> str:
        ctx = f"\nContext:\n{context}\n" if context else ""
        return (f"{ctx}List three statements that the answer is NOT. Return ONLY valid JSON.\n"
            'Format: {"not": ["x","y","z"], "denies": "<key false statement>"}\n\n'
            f"Question: {sub_q}\n\nJSON:")

    def _should_use_negation(self, t: int) -> bool:
        ratio = self.genome.negation_ratio
        return ((t + 1) * ratio) % 1.0 < ratio

    def _router_gate(
        self,
        sub_q: str,
        context: Optional[str],
        state: RemoraState,
        *,
        deadline_monotonic: float | None = None,
    ) -> bool:
        """Pre-sweep router gate.

        Runs one positive sweep of all oracles and checks oracle agreement.
        If the configured threshold is met, populates *state* with the consensus
        answer and returns True so the caller can skip full REMORA iteration.
        Returns False when agreement is insufficient — caller proceeds normally,
        unless a thermodynamic guardrail marks the item as requiring evidence.
        """
        g = self.genome
        if not g.enable_routing:
            return False

        prompt = self._build_positive_prompt(sub_q, context)
        responses = (
            self._ask_parallel(prompt, deadline_monotonic=deadline_monotonic)
            if g.enable_parallel_fanout
            else [oracle.ask(prompt) for oracle in self.oracles]
        )
        valid_responses = [r for r in responses if r.error is None]
        failed_count = len(responses) - len(valid_responses)
        if failed_count:
            state.decisions.append(
                f"router_gate: {failed_count} oracle(s) failed — excluded from consensus"
            )
        state.oracle_log.extend(responses)
        state.cumulative_cost += sum(r.cost_usd for r in valid_responses)

        if not valid_responses:
            state.decisions.append("router_gate: no valid oracle responses — aborting")
            return False

        verdicts: list[tuple[str, CanonicalVerdict]] = [
            (r.provider, phi(r.extracted)) for r in valid_responses
        ]
        rho_bar = self._mean_rho([provider for provider, _ in verdicts])
        self.correlation.observe(verdicts)

        polarity_votes: dict = {}
        confidences: list[float] = []
        for _, v in verdicts:
            polarity_votes[v.polarity] = polarity_votes.get(v.polarity, 0) + 1
        for r in valid_responses:
            raw = (r.extracted or {}).get("confidence", 0.5)
            try:
                confidences.append(float(raw))
            except (TypeError, ValueError):
                confidences.append(0.5)

        n = len(verdicts)
        winning_polarity = max(polarity_votes, key=polarity_votes.__getitem__)
        winning_count = polarity_votes[winning_polarity]

        # Explicit tie-break: if multiple polarities share the max count, treat as disagreement
        max_count = max(polarity_votes.values())
        ties = [p for p, c in polarity_votes.items() if c == max_count]
        if len(ties) > 1:
            state.decisions.append(
                f"router_gate: tie detected {dict(polarity_votes)} — proceeding to full iteration"
            )
            return False

        if winning_polarity is None:
            state.decisions.append(
                "router_gate: unanimous None polarity — oracles could not resolve; "
                "proceeding to full iteration"
            )
            return False

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.5

        if g.router_mode == RouterMode.STRICT:
            should_skip = winning_count == n
        elif g.router_mode == RouterMode.BALANCED:
            should_skip = winning_count > n / 2
        else:  # HYBRID
            should_skip = (winning_count > n / 2) and (avg_conf >= g.router_confidence_min)

        if g.enable_thermodynamic_control:
            from remora.phase_controller import phase_decision
            from remora.thermodynamics import load_thermodynamic_calibration, predict_trust_before_iteration

            calibration = load_thermodynamic_calibration(g.thermo_calibration_path)

            # Use polarity-only keys for thermodynamic consensus.
            # RAG and freetext oracles agree on the binary answer (True/False/None) but
            # produce unique claim-hash fingerprints → full fingerprints inflate k to N
            # and collapse eta to 0, forcing every RAG-backed item into the disordered
            # phase regardless of actual polarity agreement.  Polarity keys correctly
            # measure binary-answer consensus while claim-text diversity is expected.
            thermo = predict_trust_before_iteration(
                pre_sweep_verdicts=[(provider, str(verdict.polarity)) for provider, verdict in verdicts],
                pre_sweep_confidences=confidences,
                rho_bar=rho_bar,
                lambda_coupling=g.thermo_lambda,
                calibration=calibration,
                prompt=sub_q,
            )
            state.last_thermo = thermo
            decision = phase_decision(
                thermo,
                genome_max_iterations=g.max_iterations,
                trust_threshold_high=g.trust_threshold_high,
                trust_threshold_low=g.trust_threshold_low,
                halluc_threshold=g.hallucination_threshold,
            )
            state.decisions.append(
                f"t={state.iteration}: thermodynamic phase={decision.phase.value} "
                f"tau={decision.trust_score:.3f} "
                f"P(halluc)<={decision.hallucination_bound:.4f} action={decision.action}"
            )
            if decision.require_rag:
                state.require_rag = True
                state.refuse_parametric_verdict = True
                state.evidence_request_reason = decision.explanation
                state.decisions.append(f"t={state.iteration}: RAG_MANDATORY — {decision.explanation}")
            if not should_skip or decision.action != "trust":
                state.allow_exploration = False
                return False

        if not should_skip:
            return False

        if g.enable_causal_stress_test and (winning_count / n) >= g.causal_stress_threshold:
            from remora.counterfactual import (
                classify_claim,
                evaluate_causal_response,
                evaluate_invariance,
                generate_counterfactual,
            )
            claim_type = classify_claim(sub_q)
            red_team_oracle = self.oracles[0]
            cf_question = generate_counterfactual(sub_q, context, red_team_oracle)

            cf_prompt = self._build_positive_prompt(cf_question, context)
            cf_responses = (
                self._ask_parallel(cf_prompt, deadline_monotonic=deadline_monotonic)
                if g.enable_parallel_fanout
                else [oracle.ask(cf_prompt) for oracle in self.oracles]
            )
            cf_valid = [r for r in cf_responses if r.error is None]
            cf_failed = len(cf_responses) - len(cf_valid)
            if cf_failed:
                state.decisions.append(
                    f"t={state.iteration}: causal_stress_test — {cf_failed} oracle(s) failed"
                )
            state.oracle_log.extend(cf_responses)
            state.cumulative_cost += sum(r.cost_usd for r in cf_valid)

            if not cf_valid:
                state.decisions.append(
                    f"t={state.iteration}: causal_stress_test — no valid responses, skipping"
                )
            else:
                cf_verdicts = [(r.provider, phi(r.extracted)) for r in cf_valid]
                cf_polarity_votes: dict = {}
                for _, v in cf_verdicts:
                    cf_polarity_votes[v.polarity] = cf_polarity_votes.get(v.polarity, 0) + 1
                cf_winning_polarity = max(cf_polarity_votes, key=cf_polarity_votes.__getitem__)

                if getattr(g, "enable_counterfactual_v2", False):
                    passed = evaluate_invariance(claim_type, winning_polarity, cf_winning_polarity)
                else:
                    passed = evaluate_causal_response(winning_polarity, cf_winning_polarity)
                if not passed:
                    state.decisions.append(
                        f"t={state.iteration}: causal_stress_test — FAILED. "
                        f"Original polarity {winning_polarity} matched counterfactual polarity {cf_winning_polarity}. Escalating to RAG / full loop."
                    )
                    return False

                state.decisions.append(
                    f"t={state.iteration}: causal_stress_test — PASSED. "
                    "Causal intervention successfully triggered logical deduction."
                )

        winning_verdict = next(v for _, v in verdicts if v.polarity == winning_polarity)
        fp = winning_verdict.fingerprint()
        state.candidates[fp] = winning_verdict
        state.candidate_support[fp] = winning_count / n
        state.iteration += 1
        state.consensus_log.append({
            "t": state.iteration, "sub_q": sub_q, "mode": "router_gate",
            "winning_fp": fp, "weighted_support": winning_count / n,
            "unweighted_support": winning_count / n,
            "correlation_correction": 0.0,
            "weights": {p: 1.0 / n for p, _ in verdicts},
            "V": 0.0, "H": 0.0, "D": 0.0,
        })
        state.decisions.append(
            f"t={state.iteration}: router_gate — mode={g.router_mode.value} "
            f"agree={winning_count}/{n} conf={avg_conf:.2f}"
        )
        return True

    def run(
        self,
        question: str,
        context: Optional[str] = None,
        *,
        domain: str | None = None,
        risk_tier: str | None = None,
        action_type: str | None = None,
        target_environment: str | None = None,
        external_evidence: Optional[list[dict]] = None,
        # v0.9 governance context — caller-supplied fields passed through to
        # PolicyObservation.  The engine populates what it can detect locally
        # (coercion from text, rollback from action_type); the rest are
        # application-layer responsibility.
        session_id: str | None = None,
        session_action_count: int | None = None,
        session_cumulative_risk: float | None = None,
        fleet_level_effect: str | None = None,
        policy_generalization_risk: float | None = None,
        similar_action_seen_count: int | None = None,
        environment_confidence: float | None = None,
        model_misspecification_risk: float | None = None,
        classification_confidence: float | None = None,
        coercion_detected: bool = False,
    ) -> RemoraState:
        # Admission firewall: block adversarial input before any oracle fan-out.
        if self._detect_adversarial_input(question):
            refuse_state = RemoraState(
                question=question,
                refuse_parametric_verdict=True,
                domain=domain,
                risk_tier=risk_tier,
                action_type=action_type,
                target_environment=target_environment,
                coercion_detected=coercion_detected or self._detect_coercion(question),
                session_id=session_id,
                session_action_count=session_action_count,
                session_cumulative_risk=session_cumulative_risk,
                fleet_level_effect=fleet_level_effect,
                policy_generalization_risk=policy_generalization_risk,
                similar_action_seen_count=similar_action_seen_count,
                environment_confidence=environment_confidence,
                model_misspecification_risk=model_misspecification_risk,
                classification_confidence=classification_confidence,
            )
            refuse_state.decisions.append(
                "run: adversarial input detected at admission — oracle fan-out suppressed"
            )
            return refuse_state

        g = self.genome
        params = self._genome_to_lyapunov_params()
        state = RemoraState(
            question=question,
            controller=LyapunovController.init(params),
            domain=domain,
            risk_tier=risk_tier,
            action_type=action_type,
            target_environment=target_environment,
            external_evidence=list(external_evidence or []),
            coercion_detected=coercion_detected or self._detect_coercion(question),
            session_id=session_id,
            session_action_count=session_action_count,
            session_cumulative_risk=session_cumulative_risk,
            fleet_level_effect=fleet_level_effect,
            policy_generalization_risk=policy_generalization_risk,
            similar_action_seen_count=similar_action_seen_count,
            environment_confidence=environment_confidence,
            model_misspecification_risk=model_misspecification_risk,
            classification_confidence=classification_confidence,
        )
        deadline_monotonic = None
        if self.max_decision_time_s is not None:
            deadline_monotonic = time.monotonic() + max(0.0, self.max_decision_time_s)

        sub_questions = adaptive_decompose(
            question=question, oracles=self.oracles,
            max_subquestions=g.max_subquestions, strategy=g.decomposition_strategy
        )
        for sub_q in sub_questions:
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                state.refuse_parametric_verdict = True
                state.require_rag = True
                state.decisions.append(
                    "run: global decision deadline exceeded before sub-question processing"
                )
                break
            self._process_subquestion(
                state,
                sub_q,
                context,
                params,
                deadline_monotonic=deadline_monotonic,
            )
        return state

    def _build_anti_convergence_context(self, state: RemoraState, max_claims: int) -> str:
        """
        Summarise the top claims accumulated so far for anti-convergence injection.

        Injected into the prompt from iteration 2 onwards when
        genome.enable_anti_convergence is True, instructing oracles to reason
        from non-overlapping angles and avoid echo-chamber reinforcement.
        """
        if not state.candidates:
            return ""
        top = sorted(state.candidate_support.items(), key=lambda x: -x[1])[:max_claims]
        lines = []
        for fp, support in top:
            v = state.candidates.get(fp)
            if v:
                pol = {True: "YES", False: "NO", None: "UNCERTAIN"}.get(v.polarity, "?")
                lines.append(f"  - {pol} (weighted support={support:.2f})")
        if not lines:
            return ""
        return (
            "\n\n[ANTI-CONVERGENCE NOTICE]\n"
            "Previous oracle iterations have already noted:\n"
            + "\n".join(lines) +
            "\nYou MUST approach this question from a DIFFERENT angle. "
            "Do not restate or echo the positions above. Find a non-overlapping perspective."
        )

    def _process_subquestion(
        self,
        state: RemoraState,
        sub_q: str,
        context: Optional[str],
        params: LyapunovParams,
        *,
        deadline_monotonic: float | None = None,
    ) -> None:
        if self._router_gate(sub_q, context, state, deadline_monotonic=deadline_monotonic):
            return
        if state.refuse_parametric_verdict:
            state.decisions.append(
                f"t={state.iteration}: thermodynamic_guardrail — parametric verdict blocked pending evidence"
            )
            return
        g = self.genome
        for iter_n in range(g.max_iterations):
            if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                state.decisions.append(
                    f"t={state.iteration}: global decision deadline exceeded — refusing parametric verdict"
                )
                state.refuse_parametric_verdict = True
                state.require_rag = True
                return
            state.iteration += 1
            t = state.iteration
            if self._should_use_negation(iter_n):
                prompt = self._build_negative_prompt(sub_q, context); mode = "negative"
            else:
                base_prompt = self._build_positive_prompt(sub_q, context)
                # Inject anti-convergence context from iteration 2 onwards
                if g.enable_anti_convergence and iter_n > 0:
                    ac_ctx = self._build_anti_convergence_context(
                        state, g.anti_convergence_max_context_claims
                    )
                    prompt = base_prompt + ac_ctx if ac_ctx else base_prompt
                else:
                    prompt = base_prompt
                mode = "positive"
            # PR-13: measure oracle fan-out wall-clock time
            _t0 = time.monotonic()
            responses = (
                self._ask_parallel(prompt, deadline_monotonic=deadline_monotonic)
                if g.enable_parallel_fanout
                else [oracle.ask(prompt) for oracle in self.oracles]
            )
            _fanout_ms = round((time.monotonic() - _t0) * 1000, 1)
            valid_responses = [r for r in responses if r.error is None]
            failed_count = len(responses) - len(valid_responses)
            if failed_count:
                state.decisions.append(
                    f"t={t}: {failed_count} oracle(s) failed — excluded from consensus"
                )
            if len(valid_responses) < self.min_valid_oracles:
                state.decisions.append(
                    f"t={t}: insufficient valid oracle responses "
                    f"({len(valid_responses)} < {self.min_valid_oracles}) — refusing parametric verdict"
                )
                state.refuse_parametric_verdict = True
                state.oracle_log.extend(responses)
                return
            state.oracle_log.extend(responses)
            state.cumulative_cost += sum(r.cost_usd for r in valid_responses)
            verdicts: list[tuple[str, CanonicalVerdict]] = [
                (r.provider, phi(r.extracted)) for r in valid_responses
            ]
            if not verdicts:
                state.decisions.append(
                    f"t={t}: no valid oracle responses — aborting sub-question"
                )
                return
            self.correlation.observe(verdicts)
            consensus = weighted_consensus(verdicts, self.correlation)
            # CR-1: Weighted consensus tie must not silently fall through to ACCEPT.
            # Mark state so the policy engine routes to VERIFY at minimum.
            if consensus.is_tie:
                state.decisions.append(
                    f"t={t}: weighted consensus tie among {consensus.tied_fingerprints} "
                    "\u2014 refusing parametric verdict, requiring evidence"
                )
                state.refuse_parametric_verdict = True
                state.require_rag = True
            self._update_candidates(state, verdicts, consensus, mode)
            if mode == "negative": self._extract_falsified(state, responses)
            weighted_dist = self._weighted_distribution(verdicts, consensus)
            lyap_state = state_from_consensus(t=t, consensus=consensus,
                weighted_distribution=weighted_dist, cumulative_cost=state.cumulative_cost, params=params)

            if getattr(g, 'enable_topological_analysis', False):
                from remora.topology import compute_betti_numbers
                betti_info = compute_betti_numbers([(p, v.fingerprint()) for p, v in verdicts])
                if betti_info.get("topological_collapse"):
                    lyap_state = replace(lyap_state, D=lyap_state.D + 0.5, V=lyap_state.V + 0.5)
                    state.decisions.append(f"t={t}: TDA flagged topological cycle (betti_1 > 0). Divergence increased.")

            state.controller.push(lyap_state)
            state.consensus_log.append({"t":t,"sub_q":sub_q,"mode":mode,
                "winning_fp":consensus.winning_fingerprint,"weighted_support":consensus.weighted_support,
                "unweighted_support":consensus.unweighted_support,
                "correlation_correction":consensus.correlation_correction,
                "weights":consensus.weights,"V":lyap_state.V,"H":lyap_state.H,"D":lyap_state.D,
                "is_tie":consensus.is_tie,"tied_fingerprints":consensus.tied_fingerprints,
                # PR-13: per-iteration telemetry
                "fanout_elapsed_ms":_fanout_ms,
                "step_cost_usd":round(sum(r.cost_usd for r in valid_responses), 6),
                "valid_oracles":len(valid_responses),
                "oracle_latencies_ms":[r.latency_ms for r in valid_responses],
            })
            abort, reason = state.controller.should_abort(allow_exploration=state.allow_exploration)
            if abort:
                state.decisions.append(f"t={t}: abort — {reason}"); return
            if (g.early_exit_on_convergence and consensus.weighted_support >= g.converged_threshold
                    and lyap_state.D <= (1.0 - g.converged_threshold) + 1e-6):
                state.decisions.append(f"t={t}: early_exit — converged on {consensus.winning_fingerprint}"); return

    def _update_candidates(self, state: RemoraState, verdicts, consensus, mode: str) -> None:
        weights = consensus.weights
        for provider, verdict in verdicts:
            fp = verdict.fingerprint()
            if fp in state.falsified: continue
            state.candidates[fp] = verdict
            state.candidate_support[fp] = state.candidate_support.get(fp, 0.0) + weights.get(provider, 1.0/len(verdicts))

    def _extract_falsified(self, state: RemoraState, responses: list[OracleResponse]) -> None:
        for r in responses:
            ext = r.extracted
            for key in ("not", "denies"):
                v = ext.get(key)
                if v is None: continue
                items = v if isinstance(v, list) else [v]
                for item in items:
                    denied = phi({"claim": str(item)})
                    state.falsified.add(denied.fingerprint())
        for fp in list(state.candidates.keys()):
            if fp in state.falsified:
                del state.candidates[fp]; state.candidate_support.pop(fp, None)

    def _weighted_distribution(self, verdicts, consensus) -> dict[str, float]:
        dist: dict[str, float] = defaultdict(float)
        total = 0.0
        for provider, verdict in verdicts:
            w = consensus.weights.get(provider, 1.0/len(verdicts))
            dist[verdict.fingerprint()] += w; total += w
        return {fp: w/total for fp, w in dist.items()} if total else {}

    def _build_evidence_signal_from_state(self, state: RemoraState) -> EvidenceSignal:
        """Build an EvidenceSignal proxy from oracle consensus data.

        Uses oracle agreement as a proxy for evidence quality when no external
        retriever is available.  This is a structural bridge — semantic
        evidence should replace it in production.
        """
        valid = [r for r in state.oracle_log if r.error is None and r.extracted is not None]
        n_valid = len(valid)
        n_total = len(state.oracle_log)

        if n_valid == 0:
            return EvidenceSignal(
                evidence_strength=0.0,
                contradiction_score=0.0,
                citation_coverage=0.0,
                cross_evidence_consistency=0.0,
                source_reliability=0.0,
            )

        # Polarity distribution from valid responses
        polarity_counts: dict = {}
        for r in valid:
            v = phi(r.extracted)
            polarity_counts[v.polarity] = polarity_counts.get(v.polarity, 0) + 1

        max_count = max(polarity_counts.values()) if polarity_counts else 0
        majority_fraction = max_count / n_valid
        # contradiction = 1 - agreement (how split are we?)
        contradiction = 1.0 - majority_fraction

        # coverage = fraction of oracles that gave valid responses
        coverage = n_valid / n_total if n_total > 0 else 0.0

        # consistency = mean pairwise rho (oracle correlation)
        providers = [r.provider for r in valid]
        consistency = self._mean_rho(providers)

        # reliability = consistency scaled to [0,1] with a floor
        reliability = max(0.0, min(1.0, consistency + 0.5))

        # strength = majority support weighted by consistency
        strength = majority_fraction * consistency

        return EvidenceSignal(
            evidence_strength=round(strength, 3),
            contradiction_score=round(contradiction, 3),
            citation_coverage=round(coverage, 3),
            cross_evidence_consistency=round(consistency, 3),
            source_reliability=round(reliability, 3),
        )

    def report(self, state: RemoraState) -> dict:
        top_candidates = sorted(state.candidate_support.items(), key=lambda x: -x[1])[:5]
        top_claims = []
        for fp, support in top_candidates:
            v = state.candidates.get(fp)
            if v: top_claims.append([f"[{fp[:8]}] pol={v.polarity}", support])
        traj = state.controller.trajectory()
        final_V = traj[-1]["V"] if traj else None

        rep = {"question": state.question, "iterations": state.iteration,
            "oracle_calls": len(state.oracle_log), "total_cost_usd": round(state.cumulative_cost, 6),
            "final_V": final_V, "final_H": traj[-1]["H"] if traj else None,
            "final_D": traj[-1]["D"] if traj else None,
            "V_reduction": state.controller.total_reduction(),
            "is_converging": state.controller.is_converging(),
            "open_candidates": len(state.candidates), "falsified_count": len(state.falsified),
            "top_claims": top_claims, "known_negations": [], "decisions": state.decisions,
            "require_rag": state.require_rag,
            "refuse_parametric_verdict": state.refuse_parametric_verdict,
            "evidence_request_reason": state.evidence_request_reason,
            "trajectory": traj, "final_entropy": traj[-1]["H"] if traj else None,
            "entropy_trajectory": [s["H"] for s in traj], "state_hash": _state_hash(state)}

        g = self.genome
        if getattr(g, 'enable_zkp_assurance', False) or getattr(g, 'enable_assurance_trace', False):
            from remora.assurance.trace import generate_assurance_trace
            betti_info = {"betti_0": 1, "betti_1": 0}
            trace = generate_assurance_trace(state.consensus_log, final_V or 0.0, betti_info)
            rep["assurance_trace"] = {
                "root_hash": trace.root_hash,
                "leaf_count": trace.leaf_count,
                "betti_0": trace.betti_0,
                "betti_1": trace.betti_1,
                "lyapunov_final_V": trace.lyapunov_final_V,
                "signature_standard": trace.signature_standard,
            }

        if getattr(g, 'enable_semantic_claim_graph', False):
            from remora.graph.build_from_claims import graph_metrics_for_claims
            # Use top claim texts from oracle log where available
            claim_texts = []
            for resp in state.oracle_log:
                ext = resp.extracted or {}
                c = ext.get("claim")
                if c and isinstance(c, str):
                    claim_texts.append(c)
            if claim_texts:
                gm = graph_metrics_for_claims(claim_texts[:20])  # limit to 20
                rep["claim_graph_metrics"] = gm
            else:
                rep["claim_graph_metrics"] = {"n_claims": 0, "n_edges": 0, "betti_0": 0, "betti_1": 0,
                                               "contradiction_cycles": 0, "relation_counts": {}}

        from remora.policy import PolicyObservation, RemoraDecisionEngine

        # Extract values from already-computed rep and state
        traj = state.controller.trajectory()
        _last = traj[-1] if traj else {}  # noqa: F841

        # Get top candidate support
        top_support = None
        if state.candidate_support:
            top_support = max(state.candidate_support.values())

        # Extract thermodynamic fields stored during _router_gate()
        _thermo = state.last_thermo
        _phase_raw = getattr(_thermo, "phase", None)
        if _phase_raw is None:
            _phase_str: str | None = None
        elif isinstance(_phase_raw, str):
            _phase_str = _phase_raw
        else:
            _phase_str = getattr(_phase_raw, "value", None)

        # Count oracle failures vs valid responses from full log
        _oracle_failures = sum(1 for r in state.oracle_log if r.error is not None)
        _valid_oracle_count = len(state.oracle_log) - _oracle_failures

        obs = PolicyObservation(
            question=state.question,
            phase=_phase_str,
            trust_score=getattr(_thermo, "trust_score", None),
            temperature=getattr(_thermo, "temperature", None),
            order_parameter=getattr(_thermo, "order_parameter", None),
            susceptibility=getattr(_thermo, "susceptibility", None),
            hallucination_bound=getattr(_thermo, "hallucination_bound", None),
            weighted_support=top_support,
            majority_support=None,
            rho_response_agreement=None,
            final_V=rep.get("final_V"),
            final_H=rep.get("final_H"),
            final_D=rep.get("final_D"),
            require_rag=state.require_rag,
            refuse_parametric_verdict=state.refuse_parametric_verdict,
            evidence_request_reason=state.evidence_request_reason,
            conformal_score=None,
            gainability_score=None,
            evidence_action=None,
            evidence_confidence=None,
            evidence_supporters=None,
            evidence_contradictions=None,
            claim_graph_betti_0=None,
            claim_graph_betti_1=None,
            contradiction_cycles=None,
            counterfactual_passed=None,
            assurance_root=rep.get("assurance_trace", {}).get("root_hash") if "assurance_trace" in rep else None,
            adversarial_detected=self._detect_adversarial_input(state.question),
            risk_tier=state.risk_tier,
            domain=state.domain,
            action_type=state.action_type,
            target_environment=state.target_environment,
            oracle_failures=_oracle_failures,
            valid_oracle_count=_valid_oracle_count,
            # v0.9: coercion — from state (text-detected or caller-set in run())
            coercion_detected=state.coercion_detected,
            # v0.9: rollback heuristic — False for known irreversible action types
            rollback_available=(
                False
                if (state.action_type or "").strip().lower()
                   in self._IRREVERSIBLE_ACTION_TYPES
                else None
            ),
            # v0.9: caller-supplied passthrough fields
            session_id=state.session_id,
            session_action_count=state.session_action_count,
            session_cumulative_risk=state.session_cumulative_risk,
            fleet_level_effect=state.fleet_level_effect,
            policy_generalization_risk=state.policy_generalization_risk,
            similar_action_seen_count=state.similar_action_seen_count,
            environment_confidence=state.environment_confidence,
            model_misspecification_risk=state.model_misspecification_risk,
            classification_confidence=state.classification_confidence,
        )

        # Wire CriticalEvidenceRouter into the main decision path
        if state.oracle_log:
            ev_result: EvidenceProviderResult | None = None
            risk = (state.risk_tier or "").strip().lower()
            retrieval_provider = self.retrieval_evidence_provider
            should_try_retrieval_first = (
                risk in {"high", "critical"}
                and retrieval_provider is not None
            )

            if should_try_retrieval_first:
                try:
                    assert retrieval_provider is not None
                    ev_result = retrieval_provider.fetch(
                        question=state.question,
                        domain=state.domain,
                        risk_tier=state.risk_tier,
                        action_type=state.action_type,
                        target_environment=state.target_environment,
                        oracle_responses=state.oracle_log,
                    )
                    state.decisions.append(
                        "evidence_provider: retrieval-first path used for high/critical risk"
                    )
                except Exception as exc:
                    state.decisions.append(
                        f"evidence_provider: retrieval failed ({type(exc).__name__}) — fallback oracle_proxy"
                    )

            if ev_result is None:
                ev_result = self.evidence_provider.fetch(
                    question=state.question,
                    domain=state.domain,
                    risk_tier=state.risk_tier,
                    action_type=state.action_type,
                    target_environment=state.target_environment,
                    oracle_responses=state.oracle_log,
                )

            ev_signal = ev_result.signal
            ev_router = CriticalEvidenceRouter()
            ev_decision = ev_router.route(ev_signal)

            # Count supporters / contradictions from oracle log
            valid_resps = [r for r in state.oracle_log if r.error is None and r.extracted is not None]
            if valid_resps:
                pols = [phi(r.extracted).polarity for r in valid_resps]
                winning_pol = max(set(pols), key=pols.count) if pols else None
                supporters = sum(1 for p in pols if p == winning_pol)
                contradictions = sum(1 for p in pols if p is not None and p != winning_pol)
            else:
                supporters = 0
                contradictions = 0

            obs = replace(
                obs,
                evidence_action=ev_decision.action,
                evidence_confidence=round(ev_decision.confidence, 3),
                evidence_supporters=supporters,
                evidence_contradictions=contradictions,
                evidence_signal_source=ev_result.signal_source,
                evidence_provenance=ev_result.provenance,
            )

        # Explicitly surface external evidence context in policy observation
        # and envelope provenance without forcing optimistic action changes.
        if state.external_evidence:
            signal = getattr(obs, "evidence_signal_source", "oracle_proxy") or "oracle_proxy"
            if "external" not in signal:
                signal = f"{signal}+external_retrieval"
            ext_supporters = len(state.external_evidence)
            current_supporters = getattr(obs, "evidence_supporters", None) or 0
            obs = replace(
                obs,
                evidence_supporters=max(current_supporters, ext_supporters),
                evidence_signal_source=signal,
            )

        decision_engine = RemoraDecisionEngine()
        decision = decision_engine.decide(obs)

        rep["policy_observation"] = obs
        rep["external_evidence"] = {
            "count": len(state.external_evidence),
            "types": sorted(
                {
                    str(e.get("evidence_type", "unknown"))
                    for e in state.external_evidence
                    if isinstance(e, dict)
                }
            ),
        }
        rep["policy_decision"] = {
            "action": decision.action.value,
            "reasons": [r.value for r in decision.reasons],
            "risk_estimate": decision.risk_estimate,
            "confidence": decision.confidence,
            "coverage_policy": decision.coverage_policy,
            "evidence_required": decision.evidence_required,
            "human_review_required": decision.human_review_required,
            "audit_root": decision.audit_root,
            "explanation": decision.explanation,
            "source_of_decision": decision.source_of_decision,
            "policy_version": decision.policy_version,
            "in_sample_calibration_warning": decision.in_sample_calibration_warning,
        }

        # PR-6: attach the canonical DecisionEnvelope v2 to the report
        rep["envelope"] = _build_envelope(state, obs, decision, rep)

        return rep

def _state_hash(state: RemoraState) -> str:
    snap = {"q": state.question, "iter": state.iteration,
        "candidates": sorted(state.candidates.keys()), "falsified": sorted(state.falsified),
        "support": sorted(state.candidate_support.items())}
    return hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()[:16]


def _build_envelope(state: RemoraState, obs: object, decision: object, rep: dict):
    """Build a DecisionEnvelope v2 from engine state + policy decision.

    PR-6: This is the canonical output contract.  All blocks are populated
    from the runtime state so the envelope is auditable end-to-end.
    """
    from remora.governance.envelope import (
        AuditBlock, AssessmentBlock, DecisionEnvelope, FollowUpBlock,
        GateBlock, HistoryBlock, PolicyLearningBlock, RequestBlock,
        ReviewerContextBlock,
    )

    request = RequestBlock(
        request_id=rep.get("state_hash", ""),
        domain=state.domain or "unspecified",
        risk_tier=state.risk_tier or "unspecified",
        proposed_action=state.question[:200],
        action_type=state.action_type or "unspecified",
        target_environment=state.target_environment or "unspecified",
    )

    traj = state.controller.trajectory()
    last = traj[-1] if traj else {}
    thermo = state.last_thermo
    assessment = AssessmentBlock(
        oracle_votes=[
            {"provider": r.provider, "error": r.error,
             "polarity": None if r.error else phi(r.extracted).polarity}
            for r in state.oracle_log
        ],
        thermodynamic={
            "phase": getattr(thermo, "phase", None),
            "temperature": getattr(thermo, "temperature", None),
            "trust_score": getattr(thermo, "trust_score", None),
            "V": last.get("V"), "H": last.get("H"), "D": last.get("D"),
        },
        evidence_quality={
            "action": getattr(obs, "evidence_action", None),
            "confidence": getattr(obs, "evidence_confidence", None),
            "supporters": getattr(obs, "evidence_supporters", None),
            "contradictions": getattr(obs, "evidence_contradictions", None),
            "signal_source": getattr(obs, "evidence_signal_source", "oracle_proxy"),
            "provenance": getattr(obs, "evidence_provenance", None),
        },
        policy_triggers=[r.value for r in getattr(decision, "reasons", [])],
    )

    _action_obj = getattr(decision, "action", None)
    _action_value = getattr(_action_obj, "value", None)
    if isinstance(_action_value, str):
        _gate_outcome = _action_value
    else:
        _gate_outcome = str(_action_obj) if _action_obj is not None else "unknown"

    gate = GateBlock(
        outcome=_gate_outcome,
        # blocked_action iff execution is not authorized: verify (and any
        # unknown outcome, fail-closed) is as unexecutable as escalate/abstain.
        blocked_action=(
            state.question[:200]
            if _gate_outcome != "accept"
            else None
        ),
        allowed_next_steps=(
            ["human_review"] if getattr(decision, "human_review_required", False) else []
        ),
    )

    follow_up = FollowUpBlock(
        required=getattr(decision, "evidence_required", False)
            or getattr(decision, "human_review_required", False),
        type="evidence_collection" if getattr(decision, "evidence_required", False) else (
            "human_review" if getattr(decision, "human_review_required", False) else None
        ),
        requested_evidence=[] if not getattr(decision, "evidence_required", False)
            else ["retrieval_evidence"],
        sla_hours=4 if getattr(decision, "human_review_required", False) else None,
    )

    history = HistoryBlock(synthetic=True)  # live case history not yet wired

    audit = AuditBlock(
        policy_version=getattr(decision, "policy_version", ""),
        hash=rep.get("state_hash"),
        previous_hash=None,
        signature=None,
    )

    return DecisionEnvelope(
        request=request,
        assessment=assessment,
        gate=gate,
        reviewer_context=ReviewerContextBlock(),
        follow_up=follow_up,
        history=history,
        policy_learning=PolicyLearningBlock(),
        audit=audit,
    )
