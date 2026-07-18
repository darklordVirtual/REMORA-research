from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

PatternType = Literal[
    "model_domain_failure",
    "critical_disagreement",
    "false_accept",
    "memory_contamination",
    "tool_action_creep",
    "abstain_collapse",
    "evidence_insufficient",
]


@dataclass(frozen=True)
class ObservedGovernancePattern:
    """A repeated observation that may justify a reviewed policy proposal."""

    pattern_type: PatternType
    domain: str
    evidence_count: int
    metric_delta: float
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.evidence_count < 1:
            raise ValueError("evidence_count must be positive")
        if not self.domain:
            raise ValueError("domain is required")
        if not self.description:
            raise ValueError("description is required")


@dataclass(frozen=True)
class PolicyProposal:
    proposal_id: str
    domain: str
    recommended_change: str
    reasons: tuple[str, ...]
    tests_to_add: tuple[str, ...]
    requires_human_review: bool = True
    can_auto_apply: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "domain": self.domain,
            "recommended_change": self.recommended_change,
            "reasons": list(self.reasons),
            "tests_to_add": list(self.tests_to_add),
            "requires_human_review": self.requires_human_review,
            "can_auto_apply": self.can_auto_apply,
            "raw": self.raw,
        }


class PolicyProposalEngine:
    """Generate reviewed policy proposals from repeated governance signals."""

    def generate(self, patterns: list[ObservedGovernancePattern]) -> tuple[PolicyProposal, ...]:
        return tuple(self._proposal_for(pattern) for pattern in patterns)

    def _proposal_for(self, pattern: ObservedGovernancePattern) -> PolicyProposal:
        change, tests, reasons = _proposal_template(pattern)
        proposal_id = _stable_id(pattern, change)
        return PolicyProposal(
            proposal_id=proposal_id,
            domain=pattern.domain,
            recommended_change=change,
            reasons=reasons,
            tests_to_add=tests,
            raw={"pattern": pattern.__dict__},
        )


def _proposal_template(
    pattern: ObservedGovernancePattern,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    domain = pattern.domain
    if pattern.pattern_type == "model_domain_failure":
        return (
            f"Reduce failing model weight in {domain} and require fresh calibration evidence.",
            (f"golden_model_failure_{domain}", f"trust_memory_regression_{domain}"),
            ("repeated_model_domain_failure", "trust_memory_update_required"),
        )
    if pattern.pattern_type == "critical_disagreement":
        return (
            f"Raise evidence requirement and human-review threshold for critical {domain} cases.",
            (f"critical_disagreement_{domain}", f"evidence_required_{domain}"),
            ("critical_disagreement", "evidence_memory_required"),
        )
    if pattern.pattern_type == "false_accept":
        return (
            f"Raise direct-accept threshold and reduce autonomous action scope for {domain}.",
            (f"false_accept_regression_{domain}", f"accept_threshold_{domain}"),
            ("false_accept_observed", "policy_boundary_too_permissive"),
        )
    if pattern.pattern_type == "memory_contamination":
        return (
            f"Tighten memory-gate review rules for {domain} persistent memory writes.",
            (f"memory_contamination_{domain}", f"memory_gate_blocklist_{domain}"),
            ("memory_contamination", "persistent_memory_risk"),
        )
    if pattern.pattern_type == "tool_action_creep":
        return (
            f"Reduce tool execution authority and add verify/escalate routing for {domain}.",
            (f"tool_action_creep_{domain}", f"authority_boundary_{domain}"),
            ("tool_action_creep", "authority_boundary_risk"),
        )
    if pattern.pattern_type == "abstain_collapse":
        return (
            f"Add abstention drift alert and minimum abstain floor for {domain}.",
            (f"abstain_collapse_{domain}", f"drift_monitor_{domain}"),
            ("abstain_rate_drift", "risk_appetite_increase"),
        )
    return (
        f"Require stronger evidence context before accepting {domain} decisions.",
        (f"evidence_insufficient_{domain}", f"source_quality_{domain}"),
        ("insufficient_evidence", "evidence_context_gap"),
    )


def _stable_id(pattern: ObservedGovernancePattern, change: str) -> str:
    payload = "|".join(
        [
            pattern.pattern_type,
            pattern.domain,
            str(pattern.evidence_count),
            f"{pattern.metric_delta:.6f}",
            change,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
