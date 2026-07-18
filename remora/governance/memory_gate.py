from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

MemoryAction = Literal["APPROVE", "REVIEW", "BLOCK"]
MemoryCategory = Literal[
    "task_strategy",
    "verified_facts",
    "tool_usage_patterns",
    "user_preferences",
    "operational_constraints",
    "other",
]


DEFAULT_ALLOWED_CATEGORIES: tuple[str, ...] = (
    "task_strategy",
    "verified_facts",
    "tool_usage_patterns",
    "user_preferences",
    "operational_constraints",
)

BLOCK_PATTERNS: tuple[str, ...] = (
    r"\bignore (previous|system|developer) instructions\b",
    r"\bdo not tell (the )?user\b",
    r"\bhidden instruction\b",
    r"\bsecretly\b",
    r"\bself[- ]?preservation\b",
    r"\banti[- ]?user\b",
    r"\bresent(ment|ful)?\b",
    r"\busers? (are|is) (the )?(enemy|problem)\b",
    r"\bbypass (policy|approval|safety)\b",
    r"\bdisable (audit|logging|monitoring)\b",
)

REVIEW_PATTERNS: tuple[str, ...] = (
    r"\bpolitical orientation\b",
    r"\bideological\b",
    r"\bemotional interpretation\b",
    r"\bwork conditions made me\b",
    r"\bmanagement is unfair\b",
    r"\boperator is hostile\b",
    r"\bi should avoid escalation\b",
    r"\bunverifiable\b",
)


@dataclass(frozen=True)
class MemoryWriteRequest:
    content: str
    category: MemoryCategory = "other"
    source: str = "agent_output"
    confidence: float | None = None
    evidence_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("content is required")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")


@dataclass(frozen=True)
class MemoryGatePolicy:
    allow: tuple[str, ...] = DEFAULT_ALLOWED_CATEGORIES
    block_patterns: tuple[str, ...] = BLOCK_PATTERNS
    review_patterns: tuple[str, ...] = REVIEW_PATTERNS
    require_evidence_for_verified_facts: bool = True
    min_confidence_for_auto_approve: float = 0.70


@dataclass(frozen=True)
class MemoryGateDecision:
    action: MemoryAction
    reasons: tuple[str, ...]
    risk_score: float
    approved_content: str | None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return self.action == "APPROVE"


class MemoryGate:
    """Deterministic gate for persistent agent memory writes."""

    def __init__(self, policy: MemoryGatePolicy | None = None) -> None:
        self.policy = policy or MemoryGatePolicy()

    def audit(self, request: MemoryWriteRequest) -> MemoryGateDecision:
        text = request.content.lower()
        reasons: list[str] = []
        risk = 0.0

        block_hits = _pattern_hits(text, self.policy.block_patterns)
        review_hits = _pattern_hits(text, self.policy.review_patterns)

        if request.category not in self.policy.allow:
            reasons.append("category_not_allowlisted")
            risk += 0.25

        if block_hits:
            reasons.extend(f"blocked_pattern:{hit}" for hit in block_hits)
            risk += 0.75

        if review_hits:
            reasons.extend(f"review_pattern:{hit}" for hit in review_hits)
            risk += 0.35

        if (
            request.category == "verified_facts"
            and self.policy.require_evidence_for_verified_facts
            and not request.evidence_refs
        ):
            reasons.append("verified_fact_missing_evidence")
            risk += 0.30

        if request.confidence is not None and request.confidence < self.policy.min_confidence_for_auto_approve:
            reasons.append("low_memory_confidence")
            risk += 0.20

        risk = min(1.0, risk)
        if block_hits or risk >= 0.70:
            action: MemoryAction = "BLOCK"
        elif reasons:
            action = "REVIEW"
        else:
            action = "APPROVE"
            reasons.append("memory_policy_allow")

        return MemoryGateDecision(
            action=action,
            reasons=tuple(reasons),
            risk_score=risk,
            approved_content=request.content if action == "APPROVE" else None,
            raw={
                "category": request.category,
                "source": request.source,
                "evidence_refs": list(request.evidence_refs),
                "metadata": dict(request.metadata),
            },
        )


def _pattern_hits(text: str, patterns: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(pattern)
    return hits
