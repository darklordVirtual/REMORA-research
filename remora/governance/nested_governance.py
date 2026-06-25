from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


UpdateFrequency = Literal[
    "per_request",
    "per_decision",
    "per_session",
    "per_retrieval",
    "reviewed_change",
    "append_only",
]
RetentionClass = Literal["short", "medium", "long", "permanent"]
RiskLevel = Literal["low", "medium", "high", "critical"]
GovernanceRoute = Literal["ACCEPT", "VERIFY", "ABSTAIN", "ESCALATE"]


@dataclass(frozen=True)
class GovernanceLayer:
    """One memory/control layer in a nested governance model."""

    name: str
    update_frequency: UpdateFrequency
    writable_by_agent: bool
    retention: RetentionClass
    risk: RiskLevel
    trust_boundary: str
    audit_required: bool
    description: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name is required")
        if not self.trust_boundary:
            raise ValueError("trust_boundary is required")
        if not self.description:
            raise ValueError("description is required")

    @property
    def requires_reviewed_change(self) -> bool:
        return self.update_frequency in {"reviewed_change", "append_only"} or self.risk in {
            "high",
            "critical",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "update_frequency": self.update_frequency,
            "writable_by_agent": self.writable_by_agent,
            "retention": self.retention,
            "risk": self.risk,
            "trust_boundary": self.trust_boundary,
            "audit_required": self.audit_required,
            "description": self.description,
        }


@dataclass(frozen=True)
class LayerUpdateRequest:
    layer_name: str
    actor: str
    update_type: str
    approved: bool = False
    append_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LayerUpdateDecision:
    action: GovernanceRoute
    reasons: tuple[str, ...]
    layer: GovernanceLayer | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NestedGovernanceModel:
    """Multi-frequency governance model for long-running agents."""

    layers: tuple[GovernanceLayer, ...]
    version: str = "NestedGovernanceModel-v1"

    def __post_init__(self) -> None:
        names = [layer.name for layer in self.layers]
        if len(names) != len(set(names)):
            raise ValueError("layer names must be unique")

    def layer(self, name: str) -> GovernanceLayer | None:
        return next((layer for layer in self.layers if layer.name == name), None)

    def evaluate_update(self, request: LayerUpdateRequest) -> LayerUpdateDecision:
        layer = self.layer(request.layer_name)
        if layer is None:
            return LayerUpdateDecision(
                action="ABSTAIN",
                reasons=("unknown_governance_layer",),
                layer=None,
                raw={"request": request.__dict__},
            )

        reasons: list[str] = []
        actor_is_agent = request.actor.lower() in {"agent", "assistant", "model", "llm"}

        if actor_is_agent and not layer.writable_by_agent:
            reasons.append("agent_write_not_allowed")

        if layer.update_frequency == "append_only" and not request.append_only:
            reasons.append("append_only_layer_rejects_mutation")

        if layer.requires_reviewed_change and not request.approved:
            reasons.append("reviewed_change_required")

        if layer.audit_required and not request.metadata.get("audit_trace_id"):
            reasons.append("audit_trace_required")

        if any(reason in reasons for reason in ("agent_write_not_allowed", "append_only_layer_rejects_mutation")):
            action: GovernanceRoute = "ESCALATE"
        elif reasons:
            action = "VERIFY"
        else:
            action = "ACCEPT"
            reasons.append("layer_update_allowed")

        return LayerUpdateDecision(
            action=action,
            reasons=tuple(reasons),
            layer=layer,
            raw={"request": request.__dict__, "model_version": self.version},
        )

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "layers": [layer.to_dict() for layer in self.layers]}


@dataclass(frozen=True)
class GovernanceForgettingEvent:
    event_type: str
    layer_name: str
    description: str
    temporary_exception: bool = False
    became_pattern: bool = False
    ignored_abstain_or_escalate: bool = False
    policy_override: bool = False
    approved: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GovernanceForgettingReport:
    action: GovernanceRoute
    risk_score: float
    reasons: tuple[str, ...]
    event_count: int
    raw: dict[str, Any] = field(default_factory=dict)


class GovernanceForgettingDetector:
    """Detect when an agent system forgets earlier governance constraints."""

    def __init__(self, repeated_override_threshold: int = 3) -> None:
        if repeated_override_threshold < 1:
            raise ValueError("repeated_override_threshold must be positive")
        self.repeated_override_threshold = repeated_override_threshold

    def evaluate(self, events: list[GovernanceForgettingEvent]) -> GovernanceForgettingReport:
        reasons: list[str] = []
        risk = 0.0

        temporary_patterns = [
            event
            for event in events
            if event.temporary_exception and event.became_pattern
        ]
        ignored_routes = [event for event in events if event.ignored_abstain_or_escalate]
        unapproved_overrides = [
            event for event in events if event.policy_override and not event.approved
        ]
        all_overrides = [event for event in events if event.policy_override]

        if temporary_patterns:
            reasons.append("temporary_exception_became_pattern")
            risk += 0.35

        if ignored_routes:
            reasons.append("ignored_abstain_or_escalate")
            risk += 0.35

        if unapproved_overrides:
            reasons.append("unapproved_policy_override")
            risk += 0.30

        if len(all_overrides) >= self.repeated_override_threshold:
            reasons.append("repeated_policy_override")
            risk += 0.20

        risk = min(1.0, risk)
        if risk >= 0.60:
            action: GovernanceRoute = "ESCALATE"
        elif risk > 0.0:
            action = "VERIFY"
        else:
            action = "ACCEPT"
            reasons.append("no_governance_forgetting_detected")

        return GovernanceForgettingReport(
            action=action,
            risk_score=round(risk, 4),
            reasons=tuple(dict.fromkeys(reasons)),
            event_count=len(events),
            raw={"events": [event.__dict__ for event in events]},
        )


def default_nested_governance_model() -> NestedGovernanceModel:
    return NestedGovernanceModel(
        layers=(
            GovernanceLayer(
                name="runtime_context",
                update_frequency="per_request",
                writable_by_agent=True,
                retention="short",
                risk="low",
                trust_boundary="request_window",
                audit_required=False,
                description="Prompt, user input, retrieved tool output, and current task context.",
            ),
            GovernanceLayer(
                name="session_memory",
                update_frequency="per_session",
                writable_by_agent=True,
                retention="short",
                risk="medium",
                trust_boundary="session_scope",
                audit_required=True,
                description="Temporary workflow state and current-session decisions.",
            ),
            GovernanceLayer(
                name="trust_memory",
                update_frequency="per_decision",
                writable_by_agent=False,
                retention="medium",
                risk="medium",
                trust_boundary="evaluation_runtime",
                audit_required=True,
                description="Historical model quality, error rates, abstention rates, and drift telemetry.",
            ),
            GovernanceLayer(
                name="evidence_memory",
                update_frequency="per_retrieval",
                writable_by_agent=False,
                retention="medium",
                risk="medium",
                trust_boundary="approved_evidence_connectors",
                audit_required=True,
                description="Retrieved source references, freshness metadata, and citation hashes.",
            ),
            GovernanceLayer(
                name="project_memory",
                update_frequency="reviewed_change",
                writable_by_agent=False,
                retention="long",
                risk="high",
                trust_boundary="reviewed_repository_or_workspace",
                audit_required=True,
                description="Repository constraints, architecture choices, and project requirements.",
            ),
            GovernanceLayer(
                name="policy_memory",
                update_frequency="reviewed_change",
                writable_by_agent=False,
                retention="long",
                risk="high",
                trust_boundary="governance_review",
                audit_required=True,
                description="Authority boundaries, permitted actions, compliance rules, and escalation policy.",
            ),
            GovernanceLayer(
                name="audit_ledger",
                update_frequency="append_only",
                writable_by_agent=False,
                retention="permanent",
                risk="critical",
                trust_boundary="append_only_audit_store",
                audit_required=True,
                description="Immutable decision records, model outputs, scores, approvals, and policy hashes.",
            ),
            GovernanceLayer(
                name="architecture_baseline",
                update_frequency="reviewed_change",
                writable_by_agent=False,
                retention="permanent",
                risk="critical",
                trust_boundary="architecture_review",
                audit_required=True,
                description="North-star principles, safety invariants, and deployment boundaries.",
            ),
        )
    )
