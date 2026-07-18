from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ContextFlowName = Literal[
    "runtime_context",
    "oracle_context",
    "evidence_context",
    "trust_context",
    "policy_context",
    "audit_context",
]
UpdateFrequency = Literal[
    "per_request",
    "per_decision",
    "per_case",
    "continuous",
    "reviewed_change",
    "append_only",
]
RetentionClass = Literal["short", "medium", "long", "permanent"]
RiskLevel = Literal["low", "medium", "high", "critical"]
GovernanceRoute = Literal["ACCEPT", "VERIFY", "ABSTAIN", "ESCALATE"]


_VALID_FREQUENCIES = {
    "per_request",
    "per_decision",
    "per_case",
    "continuous",
    "reviewed_change",
    "append_only",
}
_VALID_RETENTION = {"short", "medium", "long", "permanent"}
_VALID_RISK = {"low", "medium", "high", "critical"}
_AGENT_ACTORS = {"agent", "assistant", "model", "llm"}


@dataclass(frozen=True)
class ContextFlow:
    """A governed information stream used by a long-running agent system."""

    name: ContextFlowName
    sources: tuple[str, ...]
    update_frequency: UpdateFrequency
    writable_by_agent: bool
    retention: RetentionClass
    risk: RiskLevel
    trust_boundary: str
    audit_required: bool
    description: str

    def __post_init__(self) -> None:
        if not self.sources:
            raise ValueError("sources must not be empty")
        if self.update_frequency not in _VALID_FREQUENCIES:
            raise ValueError("invalid update_frequency")
        if self.retention not in _VALID_RETENTION:
            raise ValueError("invalid retention")
        if self.risk not in _VALID_RISK:
            raise ValueError("invalid risk")
        if not self.trust_boundary:
            raise ValueError("trust_boundary is required")
        if not self.description:
            raise ValueError("description is required")

    def permits_actor(self, actor: str) -> bool:
        if actor.lower() in _AGENT_ACTORS:
            return self.writable_by_agent
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sources": list(self.sources),
            "update_frequency": self.update_frequency,
            "writable_by_agent": self.writable_by_agent,
            "retention": self.retention,
            "risk": self.risk,
            "trust_boundary": self.trust_boundary,
            "audit_required": self.audit_required,
            "description": self.description,
        }


@dataclass(frozen=True)
class ContextFlowUpdate:
    flow_name: ContextFlowName | str
    actor: str
    source: str
    payload_type: str
    approved: bool = False
    audit_trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.flow_name:
            raise ValueError("flow_name is required")
        if not self.actor:
            raise ValueError("actor is required")
        if not self.source:
            raise ValueError("source is required")
        if not self.payload_type:
            raise ValueError("payload_type is required")


@dataclass(frozen=True)
class ContextFlowDecision:
    action: GovernanceRoute
    reasons: tuple[str, ...]
    flow: ContextFlow | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextFlowRegistry:
    """Registry that evaluates updates against context-flow boundaries."""

    flows: tuple[ContextFlow, ...]
    version: str = "ContextFlowRegistry-v1"

    def __post_init__(self) -> None:
        names = [flow.name for flow in self.flows]
        if len(names) != len(set(names)):
            raise ValueError("context flow names must be unique")

    def flow(self, name: str) -> ContextFlow | None:
        return next((flow for flow in self.flows if flow.name == name), None)

    def evaluate_update(self, update: ContextFlowUpdate) -> ContextFlowDecision:
        flow = self.flow(update.flow_name)
        if flow is None:
            return ContextFlowDecision(
                action="ABSTAIN",
                reasons=("unknown_context_flow",),
                flow=None,
                raw={"update": update.__dict__, "version": self.version},
            )

        reasons: list[str] = []
        if not flow.permits_actor(update.actor):
            reasons.append("actor_not_allowed_for_context_flow")
        if flow.audit_required and not update.audit_trace_id:
            reasons.append("audit_trace_required")
        if flow.risk in {"high", "critical"} and not update.approved:
            reasons.append("review_required_for_high_risk_context")

        if "actor_not_allowed_for_context_flow" in reasons:
            action: GovernanceRoute = "ESCALATE"
        elif reasons:
            action = "VERIFY"
        else:
            action = "ACCEPT"
            reasons.append("context_flow_update_allowed")

        return ContextFlowDecision(
            action=action,
            reasons=tuple(reasons),
            flow=flow,
            raw={"update": update.__dict__, "version": self.version},
        )


def default_context_flows() -> tuple[ContextFlow, ...]:
    return (
        ContextFlow(
            name="runtime_context",
            sources=("user_prompt", "tool_output", "current_task"),
            update_frequency="per_request",
            writable_by_agent=True,
            retention="short",
            risk="low",
            trust_boundary="request_window",
            audit_required=False,
            description="Immediate prompt, tool response, and current task context.",
        ),
        ContextFlow(
            name="oracle_context",
            sources=("oracle_responses", "rationales", "disagreement"),
            update_frequency="per_request",
            writable_by_agent=False,
            retention="short",
            risk="medium",
            trust_boundary="oracle_runtime",
            audit_required=True,
            description="Multi-oracle outputs, disagreement, arguments, and phase signals.",
        ),
        ContextFlow(
            name="evidence_context",
            sources=("retrieved_documents", "citations", "logs"),
            update_frequency="per_case",
            writable_by_agent=False,
            retention="medium",
            risk="high",
            trust_boundary="approved_evidence_sources",
            audit_required=True,
            description="Retrieved evidence, source metadata, freshness, and log references.",
        ),
        ContextFlow(
            name="trust_context",
            sources=("model_quality_history", "error_rates", "abstain_rates"),
            update_frequency="continuous",
            writable_by_agent=False,
            retention="medium",
            risk="medium",
            trust_boundary="evaluation_runtime",
            audit_required=True,
            description="Historical model quality, drift, abstention, and tool-safety metrics.",
        ),
        ContextFlow(
            name="policy_context",
            sources=("authority_boundaries", "compliance_rules", "risk_profiles"),
            update_frequency="reviewed_change",
            writable_by_agent=False,
            retention="long",
            risk="critical",
            trust_boundary="governance_review",
            audit_required=True,
            description="Rules, authority boundaries, compliance constraints, and escalation policy.",
        ),
        ContextFlow(
            name="audit_context",
            sources=("decision_records", "approvals", "policy_hashes"),
            update_frequency="append_only",
            writable_by_agent=False,
            retention="permanent",
            risk="critical",
            trust_boundary="append_only_audit_store",
            audit_required=True,
            description="Append-only decision ledger and approval history.",
        ),
    )


def default_context_flow_registry() -> ContextFlowRegistry:
    return ContextFlowRegistry(flows=default_context_flows())
