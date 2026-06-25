from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


RetentionClass = Literal["short", "medium", "long", "permanent"]
RiskLevel = Literal["low", "medium", "high", "critical"]
GovernanceRoute = Literal["ACCEPT", "VERIFY", "ABSTAIN", "ESCALATE"]


class MemoryLayer(str, Enum):
    RUNTIME_CONTEXT = "runtime_context"
    SESSION_MEMORY = "session_memory"
    CASE_MEMORY = "case_memory"
    TRUST_MEMORY = "trust_memory"
    EVIDENCE_MEMORY = "evidence_memory"
    POLICY_MEMORY = "policy_memory"
    AUDIT_LEDGER = "audit_ledger"
    ARCHITECTURE_BASELINE = "architecture_baseline"


@dataclass(frozen=True)
class MemoryPolicy:
    layer: MemoryLayer
    update_frequency: str
    writable_by_agent: bool
    requires_human_review: bool
    retention: RetentionClass
    risk_level: RiskLevel
    append_only: bool = False
    approved_writers: tuple[str, ...] = ("service", "human")

    def __post_init__(self) -> None:
        if not self.update_frequency:
            raise ValueError("update_frequency is required")
        if self.retention not in {"short", "medium", "long", "permanent"}:
            raise ValueError("invalid retention")
        if self.risk_level not in {"low", "medium", "high", "critical"}:
            raise ValueError("invalid risk_level")
        if not self.approved_writers:
            raise ValueError("approved_writers must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer.value,
            "update_frequency": self.update_frequency,
            "writable_by_agent": self.writable_by_agent,
            "requires_human_review": self.requires_human_review,
            "retention": self.retention,
            "risk_level": self.risk_level,
            "append_only": self.append_only,
            "approved_writers": list(self.approved_writers),
        }


@dataclass(frozen=True)
class MemoryLayerUpdate:
    layer: MemoryLayer | str
    actor: str
    write_mode: Literal["append", "replace", "delete"] = "append"
    approved_by_human: bool = False
    audit_trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.actor:
            raise ValueError("actor is required")
        if self.write_mode not in {"append", "replace", "delete"}:
            raise ValueError("invalid write_mode")


@dataclass(frozen=True)
class MemoryLayerDecision:
    action: GovernanceRoute
    reasons: tuple[str, ...]
    policy: MemoryPolicy | None
    raw: dict[str, Any] = field(default_factory=dict)


DEFAULT_MEMORY_POLICIES: tuple[MemoryPolicy, ...] = (
    MemoryPolicy(
        layer=MemoryLayer.RUNTIME_CONTEXT,
        update_frequency="per_request",
        writable_by_agent=True,
        requires_human_review=False,
        retention="short",
        risk_level="low",
        approved_writers=("agent", "service", "human"),
    ),
    MemoryPolicy(
        layer=MemoryLayer.SESSION_MEMORY,
        update_frequency="per_session",
        writable_by_agent=True,
        requires_human_review=False,
        retention="short",
        risk_level="medium",
        approved_writers=("agent", "service", "human"),
    ),
    MemoryPolicy(
        layer=MemoryLayer.CASE_MEMORY,
        update_frequency="per_case",
        writable_by_agent=False,
        requires_human_review=False,
        retention="medium",
        risk_level="high",
    ),
    MemoryPolicy(
        layer=MemoryLayer.TRUST_MEMORY,
        update_frequency="per_decision",
        writable_by_agent=False,
        requires_human_review=False,
        retention="medium",
        risk_level="medium",
    ),
    MemoryPolicy(
        layer=MemoryLayer.EVIDENCE_MEMORY,
        update_frequency="per_case",
        writable_by_agent=False,
        requires_human_review=False,
        retention="medium",
        risk_level="high",
    ),
    MemoryPolicy(
        layer=MemoryLayer.POLICY_MEMORY,
        update_frequency="reviewed_change",
        writable_by_agent=False,
        requires_human_review=True,
        retention="long",
        risk_level="critical",
        approved_writers=("human",),
    ),
    MemoryPolicy(
        layer=MemoryLayer.AUDIT_LEDGER,
        update_frequency="append_only",
        writable_by_agent=False,
        requires_human_review=False,
        retention="permanent",
        risk_level="critical",
        append_only=True,
    ),
    MemoryPolicy(
        layer=MemoryLayer.ARCHITECTURE_BASELINE,
        update_frequency="reviewed_change",
        writable_by_agent=False,
        requires_human_review=True,
        retention="permanent",
        risk_level="critical",
        approved_writers=("human",),
    ),
)


@dataclass(frozen=True)
class MemoryPolicyRegistry:
    policies: tuple[MemoryPolicy, ...] = DEFAULT_MEMORY_POLICIES
    version: str = "MemoryPolicyRegistry-v1"

    def __post_init__(self) -> None:
        layers = [policy.layer for policy in self.policies]
        if len(layers) != len(set(layers)):
            raise ValueError("memory policies must be unique by layer")

    def policy_for(self, layer: MemoryLayer | str) -> MemoryPolicy | None:
        layer_value = layer.value if isinstance(layer, MemoryLayer) else layer
        return next((policy for policy in self.policies if policy.layer.value == layer_value), None)

    def evaluate_update(self, update: MemoryLayerUpdate) -> MemoryLayerDecision:
        policy = self.policy_for(update.layer)
        if policy is None:
            return MemoryLayerDecision(
                action="ABSTAIN",
                reasons=("unknown_memory_layer",),
                policy=None,
                raw={"update": update.__dict__, "version": self.version},
            )

        reasons: list[str] = []
        actor = update.actor.lower()
        if actor == "agent" and not policy.writable_by_agent:
            reasons.append("agent_write_not_allowed")
        if actor not in policy.approved_writers:
            reasons.append("writer_not_in_approved_set")
        if policy.append_only and update.write_mode != "append":
            reasons.append("append_only_layer_rejects_mutation")
        if policy.requires_human_review and not update.approved_by_human:
            reasons.append("human_review_required")
        if policy.risk_level in {"high", "critical"} and not update.audit_trace_id:
            reasons.append("audit_trace_required")

        hard_blocks = {
            "agent_write_not_allowed",
            "writer_not_in_approved_set",
            "append_only_layer_rejects_mutation",
        }
        if any(reason in hard_blocks for reason in reasons):
            action: GovernanceRoute = "ESCALATE"
        elif reasons:
            action = "VERIFY"
        else:
            action = "ACCEPT"
            reasons.append("memory_layer_update_allowed")

        return MemoryLayerDecision(
            action=action,
            reasons=tuple(reasons),
            policy=policy,
            raw={"update": update.__dict__, "version": self.version},
        )


def default_memory_policy_registry() -> MemoryPolicyRegistry:
    return MemoryPolicyRegistry()
