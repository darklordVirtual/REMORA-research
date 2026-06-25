# Author: Stian Skogbrott
# License: Apache-2.0
"""REMORA Shadow Mode + Counterfactual Governance Replay.

This module replays historical agent action logs without blocking production
execution and computes: "what REMORA would have done" for each action.

Pipeline
--------
agent_action_log.jsonl
    -> replay_action_log()
    -> DecisionEnvelope per action
    -> GovernanceDeltaReport (safety/utility/compliance metrics)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from remora.adapters.audit import AuditEntry
from remora.adapters.audit.jsonl import JSONLAudit
from remora.governance.envelope import (
    AssessmentBlock,
    AuditBlock,
    DecisionEnvelope,
    FollowUpBlock,
    GateBlock,
    HistoryBlock,
    PolicyLearningBlock,
    RequestBlock,
    ReviewerContextBlock,
)
from remora.policy import PolicyObservation, RemoraDecisionEngine
from remora.policy.report import DecisionAction, DecisionReason, DecisionReport


_HARD_VIOLATION_REASONS = {
    DecisionReason.ADMISSION_FIREWALL_BLOCKED.value,
    DecisionReason.COUNTERFACTUAL_FAILED.value,
    DecisionReason.EVIDENCE_CONTRADICTED.value,
    DecisionReason.DISTRIBUTION_SHIFT.value,
}


@dataclass(frozen=True)
class GovernanceDeltaReport:
    """Aggregated shadow-mode metrics."""

    total_actions_reviewed: int
    accepted: int
    verify_required: int
    abstained: int
    escalated: int
    critical_actions_proposed: int
    critical_autonomous_accepts: int
    critical_false_accept: int
    policy_violations_detected: int
    missing_evidence_cases: int
    oracle_disagreement_cases: int
    audit_completeness_pct: float
    estimated_avoided_unsafe_executions: int
    utility_retained_pct: float
    human_review_burden_pct: float
    baseline_comparison: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReplayResult:
    """Result object returned by replay_action_log()."""

    report: GovernanceDeltaReport
    envelopes: list[DecisionEnvelope]


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        w = v.strip().lower()
        if w in {"true", "1", "yes", "y"}:
            return True
        if w in {"false", "0", "no", "n"}:
            return False
    if isinstance(v, (int, float)):
        return bool(v)
    return None


def _load_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _action_text(rec: dict[str, Any]) -> str:
    return (
        rec.get("question")
        or rec.get("proposed_action")
        or rec.get("action")
        or rec.get("tool_call")
        or "unspecified action"
    )


def _question_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _record_to_observation(rec: dict[str, Any]) -> PolicyObservation:
    text = _action_text(rec)

    adv = _as_bool(rec.get("adversarial_detected"))
    if adv is None:
        from remora.engine import Remora

        adv = Remora._detect_adversarial_input(text)

    return PolicyObservation(
        question=text,
        phase=rec.get("phase"),
        trust_score=_as_float(rec.get("trust_score")),
        temperature=_as_float(rec.get("temperature")),
        order_parameter=_as_float(rec.get("order_parameter")),
        susceptibility=_as_float(rec.get("susceptibility")),
        hallucination_bound=_as_float(rec.get("hallucination_bound")),
        weighted_support=_as_float(rec.get("weighted_support")),
        majority_support=_as_float(rec.get("majority_support")),
        rho_response_agreement=_as_float(rec.get("rho_response_agreement")),
        final_V=_as_float(rec.get("final_V")),
        final_H=_as_float(rec.get("final_H")),
        final_D=_as_float(rec.get("final_D")),
        require_rag=bool(rec.get("require_rag", False)),
        refuse_parametric_verdict=bool(rec.get("refuse_parametric_verdict", False)),
        evidence_request_reason=rec.get("evidence_request_reason"),
        distribution_shift_detected=bool(rec.get("distribution_shift_detected", False)),
        conformal_score=_as_float(rec.get("conformal_score")),
        gainability_score=_as_float(rec.get("gainability_score")),
        evidence_action=rec.get("evidence_action"),
        evidence_confidence=_as_float(rec.get("evidence_confidence")),
        evidence_supporters=_as_int(rec.get("evidence_supporters")),
        evidence_contradictions=_as_int(rec.get("evidence_contradictions")),
        claim_graph_betti_0=_as_int(rec.get("claim_graph_betti_0")),
        claim_graph_betti_1=_as_int(rec.get("claim_graph_betti_1")),
        contradiction_cycles=_as_int(rec.get("contradiction_cycles")),
        counterfactual_passed=_as_bool(rec.get("counterfactual_passed")),
        assurance_root=rec.get("assurance_root"),
        risk_tier=rec.get("risk_tier"),
        domain=rec.get("domain"),
        action_type=rec.get("action_type"),
        target_environment=rec.get("target_environment"),
        oracle_failures=_as_int(rec.get("oracle_failures")) or 0,
        valid_oracle_count=_as_int(rec.get("valid_oracle_count")) or 0,
        adversarial_detected=bool(adv),
        evidence_signal_source=rec.get("evidence_signal_source") or "oracle_proxy",
    )


def _build_envelope(
    idx: int,
    obs: PolicyObservation,
    dec: DecisionReport,
    *,
    previous_hash: str | None = None,
) -> DecisionEnvelope:
    action_text = obs.question
    req_id = f"shadow-{idx:06d}-{_question_hash(action_text)}"
    gate_outcome = dec.action.value if isinstance(dec.action, DecisionAction) else str(dec.action)
    reasons = [r.value for r in dec.reasons]
    envelope = DecisionEnvelope(
        request=RequestBlock(
            request_id=req_id,
            domain=obs.domain or "unspecified",
            risk_tier=obs.risk_tier or "unspecified",
            proposed_action=action_text[:500],
            action_type=obs.action_type or "unspecified",
            target_environment=obs.target_environment or "unspecified",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[],
            thermodynamic={
                "phase": obs.phase,
                "temperature": obs.temperature,
                "trust_score": obs.trust_score,
                "final_V": obs.final_V,
                "final_H": obs.final_H,
                "final_D": obs.final_D,
            },
            evidence_quality={
                "action": obs.evidence_action,
                "confidence": obs.evidence_confidence,
                "supporters": obs.evidence_supporters,
                "contradictions": obs.evidence_contradictions,
                "signal_source": obs.evidence_signal_source,
            },
            policy_triggers=reasons,
        ),
        gate=GateBlock(
            outcome=gate_outcome,
            blocked_action=action_text[:500] if gate_outcome in {"escalate", "abstain"} else None,
            allowed_next_steps=["human_review"] if dec.human_review_required else [],
        ),
        reviewer_context=ReviewerContextBlock(
            asset={
                "risk_tier": obs.risk_tier,
                "domain": obs.domain,
                "target_environment": obs.target_environment,
            },
            missing_critical_data=[] if not dec.evidence_required else ["evidence"],
        ),
        follow_up=FollowUpBlock(
            required=dec.evidence_required or dec.human_review_required,
            type=(
                "evidence_collection"
                if dec.evidence_required
                else ("human_review" if dec.human_review_required else None)
            ),
            requested_evidence=["supporting_records"] if dec.evidence_required else [],
            sla_hours=4 if dec.human_review_required else None,
        ),
        history=HistoryBlock(synthetic=True),
        policy_learning=PolicyLearningBlock(candidate_rule_update=False),
        audit=AuditBlock(
            policy_version=dec.policy_version,
            hash=None,
            previous_hash=previous_hash,
            signature=None,
        ),
    )

    # Hash the full canonical envelope payload (excluding the hash field itself)
    # so edits to reasons/evidence/request metadata invalidate the chain.
    payload = envelope.to_dict()
    audit_block = payload.get("audit")
    if isinstance(audit_block, dict):
        audit_block["hash"] = None
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    chain_input = f"{previous_hash or '0' * 64}:{canonical}"
    envelope_hash = hashlib.sha256(chain_input.encode()).hexdigest()

    return replace(
        envelope,
        audit=AuditBlock(
            policy_version=dec.policy_version,
            hash=envelope_hash,
            previous_hash=previous_hash,
            signature=None,
        ),
    )


def verify_envelope_hash_chain(envelopes: list[DecisionEnvelope]) -> bool:
    """Verify full-payload envelope hash chain integrity.

    Uses the same canonical hash preimage as ``_build_envelope``.
    """
    previous_hash: str | None = None
    for envelope in envelopes:
        if envelope.audit.previous_hash != previous_hash:
            return False
        payload = envelope.to_dict()
        audit_block = payload.get("audit")
        if isinstance(audit_block, dict):
            audit_block["hash"] = None
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        expected_hash = hashlib.sha256(f"{previous_hash or '0' * 64}:{canonical}".encode()).hexdigest()
        if envelope.audit.hash != expected_hash:
            return False
        previous_hash = envelope.audit.hash
    return True


def _baseline_action(name: str, obs: PolicyObservation) -> str:
    if name == "no_gate":
        return DecisionAction.ACCEPT.value
    if name == "majority_vote":
        support = obs.majority_support if obs.majority_support is not None else obs.weighted_support
        if support is None:
            support = obs.trust_score
        return DecisionAction.ACCEPT.value if (support is not None and support >= 0.5) else DecisionAction.ABSTAIN.value
    if name == "single_judge":
        return DecisionAction.ACCEPT.value if (obs.trust_score is not None and obs.trust_score >= 0.72) else DecisionAction.ABSTAIN.value
    if name == "confidence_threshold":
        return DecisionAction.ACCEPT.value if (obs.evidence_confidence is not None and obs.evidence_confidence >= 0.7) else DecisionAction.ABSTAIN.value
    if name == "policy_only_gate":
        engine = RemoraDecisionEngine()
        stripped = replace(
            obs,
            phase=None,
            trust_score=None,
            temperature=None,
            require_rag=False,
            refuse_parametric_verdict=False,
            claim_graph_betti_1=None,
        )
        return engine.decide(stripped).action.value
    raise ValueError(f"Unknown baseline: {name}")


def _baseline_metrics(name: str, observations: list[PolicyObservation], unsafe_flags: list[bool]) -> dict[str, float]:
    actions = [_baseline_action(name, obs) for obs in observations]
    total = len(actions)
    accepts = sum(1 for a in actions if a == DecisionAction.ACCEPT.value)
    review = sum(1 for a in actions if a in {DecisionAction.VERIFY.value, DecisionAction.ESCALATE.value})
    unsafe_accepted = sum(
        1
        for a, is_unsafe in zip(actions, unsafe_flags)
        if a == DecisionAction.ACCEPT.value and is_unsafe
    )
    return {
        "mean_utility": round((accepts / total) * 100.0, 2) if total else 0.0,
        "accept_rate_pct": round((accepts / total) * 100.0, 2) if total else 0.0,  # alias
        "human_review_burden_pct": round((review / total) * 100.0, 2) if total else 0.0,
        "unsafe_execution_rate": round(unsafe_accepted / max(accepts, 1), 4),
        "unsafe_accept_count": float(unsafe_accepted),  # alias
    }


def replay_action_log(
    input_jsonl_path: str,
    *,
    output_envelopes_jsonl: str | None = None,
    output_report_json: str | None = None,
    output_audit_jsonl: str | None = None,
) -> ReplayResult:
    """Replay historical agent action logs through REMORA policy governance.

    Parameters
    ----------
    input_jsonl_path:
        Path to action logs in JSONL format.
    output_envelopes_jsonl:
        Optional output path for per-action DecisionEnvelope JSONL.
    output_report_json:
        Optional output path for aggregate GovernanceDeltaReport JSON.
    output_audit_jsonl:
        Optional path for hash-chained JSONL audit entries.

    Returns
    -------
    ReplayResult
        Contains per-action envelopes and a summary governance delta report.
    """
    records = _load_jsonl(input_jsonl_path)
    engine = RemoraDecisionEngine()
    audit = JSONLAudit(path=output_audit_jsonl) if output_audit_jsonl else None

    envelopes: list[DecisionEnvelope] = []
    observations: list[PolicyObservation] = []
    unsafe_flags: list[bool] = []

    accepted = verify = abstain = escalate = 0
    critical_actions = 0
    critical_autonomous_accepts = 0
    critical_false_accept = 0
    policy_violations_detected = 0
    missing_evidence_cases = 0
    oracle_disagreement_cases = 0
    estimated_avoided_unsafe = 0

    _chain_hash: str | None = None  # SHA-256 chain cursor

    for idx, rec in enumerate(records, start=1):
        obs = _record_to_observation(rec)
        observations.append(obs)

        dec = engine.decide(obs)
        env = _build_envelope(idx, obs, dec, previous_hash=_chain_hash)
        _chain_hash = env.audit.hash  # advance the chain
        envelopes.append(env)

        if dec.action == DecisionAction.ACCEPT:
            accepted += 1
        elif dec.action == DecisionAction.VERIFY:
            verify += 1
        elif dec.action == DecisionAction.ABSTAIN:
            abstain += 1
        elif dec.action == DecisionAction.ESCALATE:
            escalate += 1

        if obs.risk_tier == "critical":
            critical_actions += 1
            if dec.action == DecisionAction.ACCEPT:
                critical_autonomous_accepts += 1

        reason_values = {r.value for r in dec.reasons}
        if reason_values & _HARD_VIOLATION_REASONS:
            policy_violations_detected += 1

        if dec.evidence_required:
            missing_evidence_cases += 1

        if (
            obs.refuse_parametric_verdict
            or bool(rec.get("is_tie", False))
            or bool(rec.get("oracle_disagreement", False))
        ):
            oracle_disagreement_cases += 1

        unsafe = bool(rec.get("unsafe", False) or rec.get("policy_violation", False))
        unsafe_flags.append(unsafe)

        if unsafe and dec.action != DecisionAction.ACCEPT:
            estimated_avoided_unsafe += 1
        if unsafe and obs.risk_tier == "critical" and dec.action == DecisionAction.ACCEPT:
            critical_false_accept += 1

        if audit is not None:
            ts = datetime.now(timezone.utc)
            audit.append(
                AuditEntry(
                    timestamp=ts,
                    question_hash=_question_hash(obs.question),
                    action=dec.action.value,
                    trust_score=obs.trust_score or 0.0,
                    phase=obs.phase or "unknown",
                    oracle_count=max(obs.valid_oracle_count, 0),
                    verdict=dec.action.value.upper(),
                    policy_version=dec.policy_version,
                    metadata={
                        "replay_index": str(idx),
                        "risk_tier": str(obs.risk_tier or "unknown"),
                        "source": "shadow_replay",
                    },
                )
            )

    total = len(records)
    audit_completeness = round((len(envelopes) / total) * 100.0, 2) if total else 100.0
    utility_retained = round((accepted / total) * 100.0, 2) if total else 0.0
    review_burden = round(((verify + escalate) / total) * 100.0, 2) if total else 0.0

    baselines = {
        name: _baseline_metrics(name, observations, unsafe_flags)
        for name in [
            "no_gate",
            "majority_vote",
            "single_judge",
            "confidence_threshold",
            "policy_only_gate",
        ]
    }
    _remora_unsafe_accepts = sum(
        1
        for dec_env, is_unsafe in zip(envelopes, unsafe_flags)
        if dec_env.gate.outcome == DecisionAction.ACCEPT.value and is_unsafe
    )
    baselines["remora_full_policy_gate"] = {
        "mean_utility": utility_retained,
        "accept_rate_pct": utility_retained,
        "human_review_burden_pct": review_burden,
        "unsafe_execution_rate": round(_remora_unsafe_accepts / max(accepted, 1), 4),
        "unsafe_accept_count": float(_remora_unsafe_accepts),
    }
    # backward-compat alias
    baselines["remora_full_gate"] = baselines["remora_full_policy_gate"]

    report = GovernanceDeltaReport(
        total_actions_reviewed=total,
        accepted=accepted,
        verify_required=verify,
        abstained=abstain,
        escalated=escalate,
        critical_actions_proposed=critical_actions,
        critical_autonomous_accepts=critical_autonomous_accepts,
        critical_false_accept=critical_false_accept,
        policy_violations_detected=policy_violations_detected,
        missing_evidence_cases=missing_evidence_cases,
        oracle_disagreement_cases=oracle_disagreement_cases,
        audit_completeness_pct=audit_completeness,
        estimated_avoided_unsafe_executions=estimated_avoided_unsafe,
        utility_retained_pct=utility_retained,
        human_review_burden_pct=review_burden,
        baseline_comparison=baselines,
    )

    if output_envelopes_jsonl:
        out_path = Path(output_envelopes_jsonl)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            for env in envelopes:
                f.write(json.dumps(env.to_dict(), sort_keys=True) + "\n")

    if output_report_json:
        out_report = Path(output_report_json)
        out_report.parent.mkdir(parents=True, exist_ok=True)
        out_report.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True))

    return ReplayResult(report=report, envelopes=envelopes)
