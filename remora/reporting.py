# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Report and DecisionEnvelope assembly for REMORA engine results.

Presentation-layer construction extracted from ``remora.engine``
(2026-07-29 maintainability refactor). These functions are pure with respect
to the ``Remora`` engine object: every runtime dependency (genome feature
flags, evidence providers, the admission-firewall detector) is injected as a
parameter, so the assembly logic can be unit-tested without instantiating an
oracle swarm. ``Remora.report()`` delegates here; behaviour is unchanged.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from remora.action_semantics import IRREVERSIBLE_ACTION_TYPES
from remora.canonical import phi
from remora.evidence.evidence_router import CriticalEvidenceRouter
from remora.evidence.provider import (
    EvidenceProvider,
    EvidenceProviderResult,
)
from remora.state import RemoraState

if TYPE_CHECKING:
    from remora.genome import Genome
    from remora.governance.envelope import DecisionEnvelope
    from remora.policy import DecisionReport, PolicyObservation


def state_hash(state: RemoraState) -> str:
    """Content-addressed identity of the reasoning state.

    Covers the decision-relevant fields (question, iteration, candidate set +
    support, falsified set) and intentionally EXCLUDES ``oracle_log`` and
    ``decisions``: this is a state-identity digest for replay/dedup, not a full
    audit hash of every runtime event.
    """
    snap = {"q": state.question, "iter": state.iteration,
        "candidates": sorted(state.candidates.keys()), "falsified": sorted(state.falsified),
        "support": sorted(state.candidate_support.items())}
    return hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()


def build_report(
    state: RemoraState,
    *,
    genome: "Genome",
    evidence_provider: EvidenceProvider,
    retrieval_evidence_provider: EvidenceProvider | None = None,
    detect_adversarial: Callable[[str], bool],
) -> dict:
    """Assemble the full decision report for a completed engine state.

    Parameters mirror the engine attributes the historical
    ``Remora.report()`` read from ``self``; passing them explicitly keeps
    this module free of any import or attribute coupling to ``Remora``.

    ``detect_adversarial`` is the admission-firewall fallback used when the
    state was built outside ``run()`` (tests, replay) and therefore carries
    no cached ``adversarial_detected`` result.

    Side effect: appends evidence-provider selection/fallback notes to
    ``state.decisions`` (the state's own decision log), preserving the
    pre-refactor ``Remora.report()`` behaviour. ``state`` is otherwise treated
    as read input; the assembled report is returned, not stored on ``state``.
    """
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
        "entropy_trajectory": [s["H"] for s in traj], "state_hash": state_hash(state)}

    g = genome
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

    # `traj` from the top of build_report() is still current — trajectory()
    # is a read-only view and the controller does not advance during report.

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
        adversarial_detected=(
            state.adversarial_detected
            if state.adversarial_detected is not None
            # State built outside run() (tests, replay): compute on demand.
            else detect_adversarial(state.question)
        ),
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
               in IRREVERSIBLE_ACTION_TYPES
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
        retrieval_provider = retrieval_evidence_provider
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
            ev_result = evidence_provider.fetch(
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


def build_decision_envelope(
    observation: "PolicyObservation",
    decision: "DecisionReport",
    *,
    question: str | None = None,
):
    """Assemble a canonical ``DecisionEnvelope`` from a bare (observation,
    decision) pair — for callers that ran ``RemoraDecisionEngine.decide()``
    directly (CLI, deterministic tests, tooling) without a full oracle-backed
    engine run.

    Reuses the same :func:`_build_envelope` assembler as ``build_report``; the
    oracle-vote and trajectory blocks are empty because no oracle fan-out
    occurred, and the audit hash is derived from a minimal engine state.
    """
    state = RemoraState(
        question=question or getattr(observation, "question", "") or "",
        risk_tier=getattr(observation, "risk_tier", None),
        action_type=getattr(observation, "action_type", None),
        target_environment=getattr(observation, "target_environment", None) or "prod",
        domain=getattr(observation, "domain", None),
    )
    rep = {"state_hash": state_hash(state)}
    return _build_envelope(state, observation, decision, rep)


def _build_envelope(
    state: RemoraState,
    obs: "PolicyObservation",
    decision: "DecisionReport",
    rep: dict,
) -> "DecisionEnvelope":
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
