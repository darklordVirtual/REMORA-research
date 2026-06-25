"""Data types for evidence-grounded routing decisions."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class EvidenceLabel(str, Enum):
    """Possible evidence relations between a retrieved passage and a claim.

    Mirrors the NLI label space (entailment / neutral / contradiction) so
    that any NLI model output, FEVER-style verdict, or BM25/vector-store
    retrieval confidence can be mapped into the routing pipeline.
    """

    SUPPORTS = "supports"
    INSUFFICIENT = "insufficient"
    CONTRADICTS = "contradicts"


@dataclass(frozen=True)
class EvidenceSignal:
    """Quantitative evidence quality signals derived from retrieval results.

    All fields are in [0, 1].

    Attributes
    ----------
    evidence_strength:
        How strongly the retrieved passages support or refute the claim.
        High when passages are topically relevant and confidently scored.
    contradiction_score:
        Degree to which retrieved passages contradict the oracle consensus.
        Low for supporting evidence, high when passages refute the claim.
    citation_coverage:
        Fraction of the claim's key entities / propositions covered by
        at least one retrieved passage.
    cross_evidence_consistency:
        Agreement among retrieved passages.  Low when passages conflict.
    source_reliability:
        Quality or authority of the underlying source corpus
        (e.g. 0.90 for Wikipedia, lower for social media).
    """

    evidence_strength: float
    contradiction_score: float
    citation_coverage: float
    cross_evidence_consistency: float
    source_reliability: float

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_strength",
            "contradiction_score",
            "citation_coverage",
            "cross_evidence_consistency",
            "source_reliability",
        ):
            v = getattr(self, field_name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(
                    f"EvidenceSignal.{field_name} must be in [0, 1], got {v!r}"
                )


@dataclass(frozen=True)
class EvidenceDecision:
    """Routing verdict produced by :class:`CriticalEvidenceRouter`.

    Attributes
    ----------
    action:
        ``"evidence_accept"``  — evidence strongly supports the claim;
            safe to answer without human escalation.
        ``"abstain"``          — evidence contradicts the claim;
            safe to reject or flag as likely false without escalation.
        ``"escalate"``         — insufficient or conflicting evidence;
            route to a human reviewer.
    reason:
        Human-readable explanation of why this action was chosen.
    signal:
        The :class:`EvidenceSignal` that triggered this decision.
    confidence:
        Routing confidence in [0, 1].  Lower values indicate the signal
        was close to a decision boundary.
    """

    action: Literal["evidence_accept", "abstain", "escalate"]
    reason: str
    signal: EvidenceSignal
    confidence: float

    def __post_init__(self) -> None:
        if self.action not in ("evidence_accept", "abstain", "escalate"):
            raise ValueError(f"Unknown action: {self.action!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"EvidenceDecision.confidence must be in [0, 1], "
                f"got {self.confidence!r}"
            )
