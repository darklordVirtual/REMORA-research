from __future__ import annotations

from dataclasses import dataclass

from remora.policy import DecisionAction, PolicyObservation, RemoraDecisionEngine
from remora.toolcall.schema import ToolCallDecision, ToolCallTask


POLICY_TO_TOOL = {
    DecisionAction.ACCEPT: "EXECUTE",
    DecisionAction.VERIFY: "VERIFY",
    DecisionAction.ABSTAIN: "ABSTAIN",
    DecisionAction.ESCALATE: "ESCALATE",
}


DESTRUCTIVE = (
    "rm -rf", "drop table", "delete", "truncate", "force", "wipe", "disable",
    "allow_all", "expose", "emergency_stop", "private key", "sudo", "admin",
)
AMBIGUOUS_REVIEW = ("legal", "customer", "medical", "security", "breach", "refund")
READ_ONLY_HINTS = ("read", "show", "list", "describe", "status", "count", "select", "diff")
MUTATIVE_HINTS = (
    "write", "update", "apply", "set", "restart", "push", "send", "grant", "open_pr",
    "publish", "configure", "copy", "merge", "commit", "reconcile",
)


def _text(task: ToolCallTask) -> str:
    return " ".join(
        [
            task.user_request,
            task.proposed_tool_name,
            str(task.proposed_tool_args),
            " ".join(task.tags),
        ]
    ).lower()


def _is_mutative(task: ToolCallTask) -> bool:
    text = _text(task)
    if any(h in text for h in DESTRUCTIVE):
        return True
    has_mutative = any(h in text for h in MUTATIVE_HINTS)
    has_read_only = any(h in text for h in READ_ONLY_HINTS)
    return has_mutative and not has_read_only


def _context_override(task: ToolCallTask) -> tuple[str, str] | None:
    ctx = task.context or {}
    target_env = str(ctx.get("target_environment", "")).lower()
    blast_radius = str(ctx.get("blast_radius", "")).lower()
    regulatory = str(ctx.get("regulatory_domain", "")).lower()
    data_sensitivity = str(ctx.get("data_sensitivity", "")).lower()
    authz_verified = ctx.get("authz_verified")
    evidence_complete = ctx.get("evidence_complete")

    if bool(ctx.get("contains_prompt_injection")) or bool(ctx.get("fallback_contains_destructive")):
        return ("ESCALATE", "toolcall_context_injection_or_fallback_risk")

    if bool(ctx.get("intent_arg_conflict")):
        return ("ESCALATE", "toolcall_context_intent_arg_conflict")

    if bool(ctx.get("requires_human_approval")):
        return ("ESCALATE", "toolcall_context_requires_human_approval")

    if target_env in {"prod", "production", "live"}:
        if authz_verified is False or blast_radius in {"global", "all", "multi_site", "all_customers"}:
            return ("ESCALATE", "toolcall_context_production_scope_risk")

    if authz_verified is False and _is_mutative(task):
        return ("VERIFY", "toolcall_context_unverified_authorization")

    if evidence_complete is False and (
        regulatory in {"medical", "legal", "energy", "infrastructure", "security"}
        or data_sensitivity in {"phi", "pii", "regulated"}
        or bool(ctx.get("compliance_uncertain"))
    ):
        return ("VERIFY", "toolcall_context_regulated_missing_evidence")

    return None


@dataclass
class RemoraToolCallGate:
    engine: RemoraDecisionEngine | None = None
    use_evidence_flags: bool = True
    use_severity_flags: bool = True
    use_counterfactual_flags: bool = True
    use_contradiction_flags: bool = True  # no-op: is_unsafe_if_executed removed (M1 fix)
    use_context_overrides: bool = True
    use_phase_signal: bool = True
    use_temperature_signal: bool = True
    use_hard_blocks: bool = True

    def __post_init__(self) -> None:
        if self.engine is None:
            self.engine = RemoraDecisionEngine()

    def decide(self, task: ToolCallTask) -> ToolCallDecision:
        obs = self.to_observation(task)
        assert self.engine is not None
        report = self.engine.decide(obs)
        action = POLICY_TO_TOOL[report.action]
        reasons = [r.value for r in report.reasons]

        text = _text(task)
        context_override = _context_override(task) if (self.use_context_overrides and self.use_hard_blocks) else None
        if context_override is not None:
            action, reason = context_override
            reasons.append(reason)
        elif self.use_severity_flags and task.severity == "critical" and any(k in text for k in DESTRUCTIVE):
            action = "ESCALATE"
            reasons.append("toolcall_critical_destructive_override")
        elif "production" in task.tags and any(k in text for k in DESTRUCTIVE):
            action = "ESCALATE"
            reasons.append("toolcall_production_destructive_override")
        elif task.severity in {"high", "critical"} and "missing_evidence" in task.tags:
            action = "VERIFY" if task.severity == "high" else "ESCALATE"
            reasons.append("toolcall_missing_evidence_override")
        elif any(k in text for k in AMBIGUOUS_REVIEW):
            action = "VERIFY"
            reasons.append("toolcall_ambiguous_review_override")
        elif "read_only" in task.tags or "sandbox" in task.tags:
            if task.severity == "low":
                # Monotonic constraint: policy engine verdict is final.
                # Annotate context only; never loosen a conservative decision.
                reasons.append("toolcall_safe_readonly_context")

        confidence = report.confidence
        if confidence is None:
            confidence = {
                "EXECUTE": 0.8,
                "VERIFY": 0.55,
                "ABSTAIN": 0.45,
                "ESCALATE": 0.9,
            }[action]
        return ToolCallDecision(
            action=action,  # type: ignore[arg-type]
            confidence=confidence,
            reasons=tuple(reasons),
            raw={
                "policy_action": report.action.value,
                "policy_reasons": [r.value for r in report.reasons],
                "source_of_decision": getattr(report, "source_of_decision", None),
                "policy_version": getattr(report, "policy_version", None),
            },
        )

    def to_observation(self, task: ToolCallTask) -> PolicyObservation:
        text = _text(task)
        destructive = any(k in text for k in DESTRUCTIVE)
        read_only = "read_only" in task.tags or task.proposed_tool_args.get("operation") in {"read", "show"}
        evidence_action = None
        evidence_confidence = None
        evidence_contradictions = None
        counterfactual_passed = None

        if self.use_evidence_flags:
            if read_only and task.severity == "low":
                evidence_action = "answer"
                evidence_confidence = 0.9
                evidence_contradictions = 0
            elif "missing_evidence" in task.tags:
                evidence_action = "verify"
                evidence_confidence = 0.2
                evidence_contradictions = 0

        if self.use_counterfactual_flags and task.severity == "critical" and destructive:
            counterfactual_passed = False
        elif self.use_counterfactual_flags:
            counterfactual_passed = True

        phase = "ordered"
        trust_score = 0.82
        temperature = 0.12
        if task.severity == "medium":
            phase = "critical"
            trust_score = 0.45
            temperature = 0.35
        elif task.severity == "high":
            phase = "critical"
            trust_score = 0.25
            temperature = 0.55
        elif task.severity == "critical":
            phase = "disordered"
            trust_score = 0.05
            temperature = 0.9

        if not self.use_severity_flags:
            phase = "ordered" if not destructive else "critical"
            trust_score = 0.65 if not destructive else 0.35

        # Ablation mode: remove explicit hard-block signals from the observation.
        if not self.use_hard_blocks:
            if evidence_contradictions is not None and evidence_contradictions > 0:
                evidence_contradictions = 0
            counterfactual_passed = True

        if not self.use_phase_signal:
            phase = None

        if not self.use_temperature_signal:
            temperature = None

        return PolicyObservation(
            question=task.user_request,
            phase=phase,
            trust_score=trust_score,
            temperature=temperature,
            weighted_support=trust_score,
            require_rag="missing_evidence" in task.tags,
            refuse_parametric_verdict=("missing_evidence" in task.tags) if self.use_hard_blocks else False,
            evidence_action=evidence_action,
            evidence_confidence=evidence_confidence,
            evidence_contradictions=evidence_contradictions,
            contradiction_cycles=1 if evidence_contradictions else 0,
            counterfactual_passed=counterfactual_passed,
        )
