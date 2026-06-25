"""Evidence-grounded routing logic for critical-phase oracle decisions.

The :class:`CriticalEvidenceRouter` implements the evidence arm of the
REMORA routing hierarchy::

    critical + strong evidence  → EVIDENCE_ACCEPT
    critical + conflicting evidence → ABSTAIN
    critical + no / weak evidence   → ESCALATE

Motivation
----------
Trust scores in the critical phase anti-correlate with correctness
(Q4 high-trust items: 50 % correct vs Q1 low-trust: 75 % correct).
Oracle consensus in this region reflects groupthink, not accuracy.
An independent evidence channel derived from retrieval or NLI can
break the groupthink and recover coverage without sacrificing precision.

Thresholds
----------
accept_threshold : float (default 0.80)
    Minimum ``evidence_strength`` required for an evidence-accept decision.
    Stricter than the accept_min because critical-phase errors are costly.
contradiction_limit : float (default 0.15)
    Maximum ``contradiction_score`` allowed for an evidence-accept decision.
    If the evidence contradicts the oracle, accept is blocked.
contradiction_floor : float (default 0.50)
    ``contradiction_score`` above this triggers ABSTAIN (not just ESCALATE).
    This means the evidence actively refutes the claim.
coverage_minimum : float (default 0.50)
    Minimum ``citation_coverage`` required for any non-ESCALATE decision.
    Claims whose key entities are uncovered are escalated regardless.
reliability_minimum : float (default 0.60)
    Minimum ``source_reliability`` required for an evidence-accept decision.
    Low-reliability sources (e.g. social media) cannot trigger an accept.
"""
from __future__ import annotations

from dataclasses import dataclass

from remora.evidence.evidence_types import EvidenceDecision, EvidenceSignal


@dataclass
class CriticalEvidenceRouter:
    """Route critical-phase items based on retrieved-evidence quality.

    Parameters
    ----------
    accept_threshold:
        Minimum evidence strength to issue an EVIDENCE_ACCEPT.
    contradiction_limit:
        Maximum contradiction score allowed for an EVIDENCE_ACCEPT.
    contradiction_floor:
        Contradiction score above which ABSTAIN is issued.
    coverage_minimum:
        Minimum citation coverage required for non-ESCALATE decisions.
    reliability_minimum:
        Minimum source reliability required for EVIDENCE_ACCEPT.
    """

    accept_threshold: float = 0.80
    contradiction_limit: float = 0.15
    contradiction_floor: float = 0.50
    coverage_minimum: float = 0.50
    reliability_minimum: float = 0.60

    def __post_init__(self) -> None:
        for attr, val in [
            ("accept_threshold", self.accept_threshold),
            ("contradiction_limit", self.contradiction_limit),
            ("contradiction_floor", self.contradiction_floor),
            ("coverage_minimum", self.coverage_minimum),
            ("reliability_minimum", self.reliability_minimum),
        ]:
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{attr} must be in [0, 1], got {val!r}")
        if self.contradiction_limit >= self.contradiction_floor:
            raise ValueError(
                "contradiction_limit must be strictly less than "
                "contradiction_floor"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(self, signal: EvidenceSignal) -> EvidenceDecision:
        """Return the appropriate routing decision for one critical item.

        Decision logic (evaluated top-to-bottom, first match wins):

        1. **Coverage gate** — if citation coverage is below the minimum,
           the evidence is too thin for any definitive decision → ESCALATE.
        2. **Contradiction block** — if contradiction score exceeds the
           floor, the evidence actively refutes the claim → ABSTAIN.
        3. **Accept gate** — if evidence strength and reliability meet
           their thresholds and contradiction is below the limit → EVIDENCE_ACCEPT.
        4. **Fallback** — ESCALATE with a reason explaining which
           condition was closest to being met.
        """
        # 1. Coverage gate — must be checked first
        if signal.citation_coverage < self.coverage_minimum:
            return EvidenceDecision(
                action="escalate",
                reason=(
                    f"Insufficient citation coverage "
                    f"({signal.citation_coverage:.2f} < {self.coverage_minimum:.2f}); "
                    "evidence does not cover key claim entities."
                ),
                signal=signal,
                confidence=1.0 - signal.citation_coverage,
            )

        # 2. Contradiction block
        if signal.contradiction_score > self.contradiction_floor:
            return EvidenceDecision(
                action="abstain",
                reason=(
                    f"Evidence contradicts oracle consensus "
                    f"(contradiction_score={signal.contradiction_score:.2f} "
                    f"> floor {self.contradiction_floor:.2f})."
                ),
                signal=signal,
                confidence=signal.contradiction_score,
            )

        # 3. Evidence-accept gate
        if (
            signal.evidence_strength >= self.accept_threshold
            and signal.contradiction_score <= self.contradiction_limit
            and signal.source_reliability >= self.reliability_minimum
        ):
            confidence = (
                signal.evidence_strength
                * signal.cross_evidence_consistency
                * signal.source_reliability
            )
            return EvidenceDecision(
                action="evidence_accept",
                reason=(
                    f"Strong, consistent evidence supports the claim "
                    f"(strength={signal.evidence_strength:.2f}, "
                    f"contradiction={signal.contradiction_score:.2f}, "
                    f"reliability={signal.source_reliability:.2f})."
                ),
                signal=signal,
                confidence=min(1.0, confidence),
            )

        # 4. Fallback — escalate with diagnostic reason
        parts = []
        if signal.evidence_strength < self.accept_threshold:
            parts.append(
                f"evidence_strength={signal.evidence_strength:.2f} "
                f"< {self.accept_threshold:.2f}"
            )
        if signal.contradiction_score > self.contradiction_limit:
            parts.append(
                f"contradiction_score={signal.contradiction_score:.2f} "
                f"> {self.contradiction_limit:.2f}"
            )
        if signal.source_reliability < self.reliability_minimum:
            parts.append(
                f"source_reliability={signal.source_reliability:.2f} "
                f"< {self.reliability_minimum:.2f}"
            )
        reason = "Insufficient evidence for safe routing: " + "; ".join(parts) + "."
        return EvidenceDecision(
            action="escalate",
            reason=reason,
            signal=signal,
            confidence=0.5,
        )
