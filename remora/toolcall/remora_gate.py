from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from remora.policy import DecisionAction, PolicyObservation, RemoraDecisionEngine
from remora.toolcall.schema import ToolCallDecision, ToolCallTask

# ---------------------------------------------------------------------------
# Input contract (leakage fix, 2026-07 review finding #1)
#
# The gate may observe ONLY:
#   1. The task surface: user_request, proposed_tool_name, proposed_tool_args.
#   2. Platform-fact context keys — facts an executing platform can supply
#      about the environment, independent of any human labeler's judgment:
#        target_environment, blast_radius, authz_verified, evidence_complete,
#        regulatory_domain, data_sensitivity, production (v1 legacy).
#
# The gate must NEVER read:
#   - task.severity or task.tags (author annotations, ground-truth adjacent)
#   - oracle-judgment context keys set by the benchmark author in the same
#     file as the label: contains_prompt_injection, intent_arg_conflict,
#     requires_human_approval, fallback_contains_destructive,
#     compliance_uncertain
#   - any evaluation field (is_unsafe_if_executed etc.; enforced by
#     scripts/check_no_evaluation_leakage.py)
#
# Injection, intent/argument conflict, destructive-fallback risk, and the
# risk level are DERIVED from the observable surface below. Residual caveat:
# platform-fact context values in the synthetic benchmark are still declared
# by the simulator, so results measure policy mapping over declared
# environment facts plus surface-derived detectors — not detection of hidden
# intent in the wild.
# ---------------------------------------------------------------------------

POLICY_TO_TOOL = {
    DecisionAction.ACCEPT: "EXECUTE",
    DecisionAction.VERIFY: "VERIFY",
    DecisionAction.ABSTAIN: "ABSTAIN",
    DecisionAction.ESCALATE: "ESCALATE",
}


DESTRUCTIVE = (
    "rm -rf", "drop table", "delete", "truncate", "force", "wipe", "disable",
    "allow_all", "expose", "emergency_stop", "private key", "sudo", "admin",
    "| bash", "| sh",
)
AMBIGUOUS_REVIEW = ("legal", "customer", "medical", "security", "breach", "refund")
READ_ONLY_HINTS = ("read", "show", "list", "describe", "status", "count", "select", "diff")
MUTATIVE_HINTS = (
    "write", "update", "apply", "set", "restart", "push", "send", "grant", "open_pr",
    "publish", "configure", "copy", "merge", "commit", "reconcile", "broadcast",
    "rewrite", "rebase", "add ", "sync",
)
INJECTION_MARKERS = (
    "ignore previous", "ignore prior", "ignore safety", "ignore all safety",
    "disregard safety", "disregard previous", "override safety", "bypass safety",
    "ignore instructions", "ignore the above",
)
FALLBACK_BROAD_MARKERS = ("legacy", "global", "live", "broad", "full", "external", "all_")
PRODUCTION_ENVS = {"prod", "production", "live"}
BROAD_BLAST_RADIUS = {"global", "all", "multi_site", "all_customers", "all_regions", "all_sites"}


def _args_text(task: ToolCallTask) -> str:
    return " ".join([task.proposed_tool_name, str(task.proposed_tool_args)]).lower()


def _text(task: ToolCallTask) -> str:
    """Observable task surface only — never includes author tags."""
    return " ".join(
        [
            task.user_request,
            task.proposed_tool_name,
            str(task.proposed_tool_args),
        ]
    ).lower()


def _platform_facts(task: ToolCallTask) -> dict[str, Any]:
    ctx = task.context or {}
    env = str(ctx.get("target_environment", "")).lower()
    return {
        "production": env in PRODUCTION_ENVS or bool(ctx.get("production")),
        "sandbox": env == "sandbox",
        "broad_blast_radius": str(ctx.get("blast_radius", "")).lower() in BROAD_BLAST_RADIUS,
        "authz_unverified": ctx.get("authz_verified") is False,
        "evidence_missing": ctx.get("evidence_complete") is False,
        "regulated": (
            str(ctx.get("regulatory_domain", "")).lower()
            in {"medical", "legal", "energy", "infrastructure", "security"}
            or str(ctx.get("data_sensitivity", "")).lower() in {"phi", "pii", "regulated"}
        ),
    }


def _is_destructive(task: ToolCallTask) -> bool:
    text = _text(task)
    return any(k in text for k in DESTRUCTIVE)


def _is_mutative(task: ToolCallTask) -> bool:
    text = _text(task)
    if any(h in text for h in DESTRUCTIVE):
        return True
    has_mutative = any(h in text for h in MUTATIVE_HINTS)
    has_read_only = any(h in text for h in READ_ONLY_HINTS)
    return has_mutative and not has_read_only


def _args_mutative(task: ToolCallTask) -> bool:
    args_text = _args_text(task)
    return any(h in args_text for h in MUTATIVE_HINTS) or any(k in args_text for k in DESTRUCTIVE)


def _is_read_only(task: ToolCallTask) -> bool:
    if task.proposed_tool_args.get("operation") in {"read", "show"}:
        return True
    text = _text(task)
    has_read_only = any(h in text for h in READ_ONLY_HINTS)
    return has_read_only and not _args_mutative(task) and not _is_destructive(task)


def _injection_suspected(task: ToolCallTask) -> bool:
    text = _text(task)
    return any(m in text for m in INJECTION_MARKERS)


def _fallback_risk(task: ToolCallTask) -> bool:
    args_text = _args_text(task)
    return "fallback" in args_text and any(m in args_text for m in FALLBACK_BROAD_MARKERS)


def _intent_arg_conflict(task: ToolCallTask) -> bool:
    """Read-only intent in the request while the proposed args mutate state."""
    req = task.user_request.lower()
    read_intent = any(m in req for m in ("read", "show", "list", "describe", "only", "do not"))
    req_mutative = any(h in req for h in MUTATIVE_HINTS) or any(k in req for k in DESTRUCTIVE)
    return read_intent and not req_mutative and _args_mutative(task)


def derive_risk_level(task: ToolCallTask) -> str:
    """Risk level derived from the observable surface + platform facts.

    Replaces reads of the author-annotated ``task.severity`` field, which was
    ground-truth adjacent (benchmark authors set severity in the same file as
    the label). Shared with the heuristic baselines so all evaluated systems
    receive the identical input contract.
    """
    facts = _platform_facts(task)
    destructive = _is_destructive(task)
    mutative = _is_mutative(task) or _args_mutative(task)

    if destructive or (facts["production"] and facts["broad_blast_radius"]):
        return "critical"
    if facts["sandbox"] and not destructive:
        return "low"
    if "sandbox" in _text(task) and not mutative:
        return "low"
    if mutative and (facts["production"] or facts["authz_unverified"] or facts["evidence_missing"]):
        return "high"
    if mutative:
        return "medium"
    return "low"


def _context_override(task: ToolCallTask) -> tuple[str, str] | None:
    """Overrides from surface-derived detectors and platform facts only."""
    facts = _platform_facts(task)

    if _injection_suspected(task):
        return ("ESCALATE", "toolcall_derived_prompt_injection")

    if _fallback_risk(task):
        return ("ESCALATE", "toolcall_derived_destructive_fallback")

    if _intent_arg_conflict(task):
        return ("ESCALATE", "toolcall_derived_intent_arg_conflict")

    if facts["production"] and (facts["authz_unverified"] or facts["broad_blast_radius"]):
        return ("ESCALATE", "toolcall_context_production_scope_risk")

    if facts["authz_unverified"] and (_is_mutative(task) or _args_mutative(task)):
        return ("VERIFY", "toolcall_context_unverified_authorization")

    if facts["evidence_missing"] and facts["regulated"]:
        return ("VERIFY", "toolcall_context_regulated_missing_evidence")

    return None


@dataclass
class RemoraToolCallGate:
    engine: RemoraDecisionEngine | None = None
    use_evidence_flags: bool = True
    use_severity_flags: bool = True  # gates the DERIVED risk mapping (severity field is never read)
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
        facts = _platform_facts(task)
        destructive = _is_destructive(task)
        risk = derive_risk_level(task)
        context_override = _context_override(task) if (self.use_context_overrides and self.use_hard_blocks) else None
        if context_override is not None:
            action, reason = context_override
            reasons.append(reason)
        elif self.use_severity_flags and destructive and risk == "critical":
            action = "ESCALATE"
            reasons.append("toolcall_critical_destructive_override")
        elif facts["production"] and destructive:
            action = "ESCALATE"
            reasons.append("toolcall_production_destructive_override")
        elif facts["evidence_missing"] and risk in {"high", "critical"}:
            action = "VERIFY" if risk == "high" else "ESCALATE"
            reasons.append("toolcall_missing_evidence_override")
        elif any(k in text for k in AMBIGUOUS_REVIEW):
            action = "VERIFY"
            reasons.append("toolcall_ambiguous_review_override")
        elif _is_read_only(task) or facts["sandbox"]:
            if risk == "low":
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
        facts = _platform_facts(task)
        destructive = _is_destructive(task)
        read_only = _is_read_only(task)
        risk = derive_risk_level(task)
        evidence_action = None
        evidence_confidence = None
        evidence_contradictions = None
        counterfactual_passed = None

        if self.use_evidence_flags:
            if read_only and risk == "low":
                evidence_action = "answer"
                evidence_confidence = 0.9
                evidence_contradictions = 0
            elif facts["evidence_missing"]:
                evidence_action = "verify"
                evidence_confidence = 0.2
                evidence_contradictions = 0

        if self.use_counterfactual_flags and risk == "critical" and destructive:
            counterfactual_passed = False
        elif self.use_counterfactual_flags:
            counterfactual_passed = True

        phase = "ordered"
        trust_score = 0.82
        temperature = 0.12
        if risk == "medium":
            phase = "critical"
            trust_score = 0.45
            temperature = 0.35
        elif risk == "high":
            phase = "critical"
            trust_score = 0.25
            temperature = 0.55
        elif risk == "critical":
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
            require_rag=facts["evidence_missing"],
            refuse_parametric_verdict=facts["evidence_missing"] if self.use_hard_blocks else False,
            evidence_action=evidence_action,
            evidence_confidence=evidence_confidence,
            evidence_contradictions=evidence_contradictions,
            counterfactual_passed=counterfactual_passed,
        )
