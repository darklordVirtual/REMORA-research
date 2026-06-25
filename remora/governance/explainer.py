"""Explainable Decision Narratives for REMORA.

Auto-generates human-readable natural-language explanations for each
DecisionEnvelope, suitable for audit review, compliance reporting,
and non-technical stakeholder communication.

The explainer does NOT hallucinate or add information — it translates
the structured envelope data into clear prose. Every sentence maps
back to a specific field in the envelope.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from remora.governance.envelope import DecisionEnvelope


@dataclass(frozen=True)
class NarrativeSection:
    """One section of an explanation."""

    heading: str
    text: str
    source_fields: list[str] = field(default_factory=list)  # which envelope fields this is derived from
    severity: str = "info"  # info, warning, critical


@dataclass(frozen=True)
class DecisionNarrative:
    """Complete human-readable narrative for a DecisionEnvelope."""

    summary: str
    sections: list[NarrativeSection]
    risk_level: str
    recommended_action_for_reviewer: str
    envelope_hash: str = ""

    def to_text(self) -> str:
        """Render as plain text for reports."""
        lines = [self.summary, ""]
        for s in self.sections:
            marker = {"info": "", "warning": "[!] ", "critical": "[!!] "}.get(s.severity, "")
            lines.append(f"## {marker}{s.heading}")
            lines.append(s.text)
            lines.append("")
        lines.append(f"Recommendation: {self.recommended_action_for_reviewer}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "sections": [{"heading": s.heading, "text": s.text, "severity": s.severity, "source_fields": s.source_fields} for s in self.sections],
            "risk_level": self.risk_level,
            "recommended_action": self.recommended_action_for_reviewer,
        }


class DecisionExplainer:
    """Generates human-readable narratives from DecisionEnvelopes.

    Every sentence is traceable to a specific envelope field.
    No inference, no hallucination — just structured translation.
    """

    _OUTCOME_VERBS = {
        "ACCEPTED": "approved for autonomous execution",
        "VERIFIED": "approved pending human verification",
        "ABSTAINED": "blocked — REMORA declined to act",
        "ESCALATED": "escalated to human review",
    }

    _RISK_DESCRIPTIONS = {
        "low": "a low-risk action with minimal potential for harm",
        "medium": "a medium-risk action requiring standard governance checks",
        "high": "a high-risk action requiring elevated scrutiny",
        "critical": "a critical-risk action requiring maximum governance oversight",
    }

    def explain(self, envelope: DecisionEnvelope) -> DecisionNarrative:
        """Generate a complete narrative for the given envelope."""
        sections: list[NarrativeSection] = []

        # 1. Request context
        req = envelope.request
        outcome_desc = self._OUTCOME_VERBS.get(envelope.gate.outcome, envelope.gate.outcome)
        risk_desc = self._RISK_DESCRIPTIONS.get(req.risk_tier, f"a {req.risk_tier}-risk action")

        summary = (
            f"Decision {req.request_id}: The proposed action '{req.proposed_action}' "
            f"in the {req.domain} domain was {outcome_desc}."
        )

        sections.append(NarrativeSection(
            heading="What was proposed",
            text=(
                f"An agent proposed to perform '{req.proposed_action}' "
                f"(type: {req.action_type}) targeting the {req.target_environment} environment. "
                f"This is classified as {risk_desc}."
            ),
            source_fields=["request.proposed_action", "request.action_type", "request.risk_tier", "request.target_environment"],
        ))

        # 2. Assessment
        assess = envelope.assessment
        oracle_count = len(assess.oracle_votes)
        sections.append(NarrativeSection(
            heading="How the decision was made",
            text=(
                f"{oracle_count} oracle(s) were consulted. "
                f"Thermodynamic analysis: {self._describe_thermodynamic(assess.thermodynamic)}. "
                f"Evidence quality: {self._describe_evidence(assess.evidence_quality)}."
                + (f" Policy triggers fired: {', '.join(assess.policy_triggers)}." if assess.policy_triggers else "")
            ),
            source_fields=["assessment.oracle_votes", "assessment.thermodynamic", "assessment.evidence_quality", "assessment.policy_triggers"],
            severity="warning" if assess.policy_triggers else "info",
        ))

        # 3. Gate decision
        gate = envelope.gate
        gate_section = NarrativeSection(
            heading="The decision",
            text=(
                f"Outcome: {gate.outcome}."
                + (f" The action '{gate.blocked_action}' was blocked." if gate.blocked_action else "")
                + (f" Allowed next steps: {', '.join(gate.allowed_next_steps)}." if gate.allowed_next_steps else "")
            ),
            source_fields=["gate.outcome", "gate.blocked_action", "gate.allowed_next_steps"],
            severity="critical" if gate.outcome in ("ABSTAINED", "ESCALATED") else "info",
        )
        sections.append(gate_section)

        # 4. Missing data
        reviewer = envelope.reviewer_context
        if reviewer.missing_critical_data:
            sections.append(NarrativeSection(
                heading="Missing information",
                text=f"The following critical data was unavailable: {', '.join(reviewer.missing_critical_data)}. This increased uncertainty in the decision.",
                source_fields=["reviewer_context.missing_critical_data"],
                severity="warning",
            ))

        # 5. Follow-up
        fu = envelope.follow_up
        if fu.required:
            sla = f" within {fu.sla_hours} hours" if fu.sla_hours else ""
            sections.append(NarrativeSection(
                heading="Follow-up required",
                text=(
                    f"A follow-up action of type '{fu.type}' is required{sla}."
                    + (f" Requested evidence: {', '.join(fu.requested_evidence)}." if fu.requested_evidence else "")
                ),
                source_fields=["follow_up.type", "follow_up.sla_hours", "follow_up.requested_evidence"],
                severity="warning",
            ))

        # 6. History
        hist = envelope.history
        if hist.similar_cases_found > 0:
            synthetic_note = " (Note: case history is synthetic/demo data.)" if hist.synthetic else ""
            sections.append(NarrativeSection(
                heading="Historical context",
                text=(
                    f"{hist.similar_cases_found} similar past cases were found."
                    + (f" Known blockers from history: {', '.join(hist.known_blockers)}." if hist.known_blockers else "")
                    + synthetic_note
                ),
                source_fields=["history.similar_cases_found", "history.known_blockers", "history.synthetic"],
            ))

        # 7. Audit
        audit = envelope.audit
        if audit.hash:
            sections.append(NarrativeSection(
                heading="Audit trail",
                text=(
                    f"Policy version: {audit.policy_version}. "
                    f"Decision hash: {audit.hash[:16]}... "
                    f"Chain link: {audit.previous_hash[:16] + '...' if audit.previous_hash else 'genesis'}."
                ),
                source_fields=["audit.policy_version", "audit.hash", "audit.previous_hash"],
            ))

        # Recommendation for reviewer
        recommendation = self._recommend(envelope)

        return DecisionNarrative(
            summary=summary,
            sections=sections,
            risk_level=req.risk_tier,
            recommended_action_for_reviewer=recommendation,
            envelope_hash=audit.hash or "",
        )

    def _describe_thermodynamic(self, td: dict[str, Any]) -> str:
        if not td:
            return "no thermodynamic data available"
        lyap = td.get("lyapunov_value") or td.get("V")
        if lyap is not None:
            trend = "converging" if float(lyap) < 0.5 else "diverging"
            return f"Lyapunov value {lyap:.3f} ({trend})"
        return "thermodynamic analysis completed"

    def _describe_evidence(self, eq: dict[str, Any]) -> str:
        if not eq:
            return "no evidence data available"
        strength = eq.get("evidence_strength", eq.get("strength"))
        if strength is not None:
            level = "strong" if float(strength) > 0.7 else "moderate" if float(strength) > 0.4 else "weak"
            return f"{level} (strength={strength})"
        return "evidence quality assessed"

    def _recommend(self, envelope: DecisionEnvelope) -> str:
        outcome = envelope.gate.outcome
        risk = envelope.request.risk_tier
        missing = envelope.reviewer_context.missing_critical_data

        if outcome == "ESCALATED":
            if risk == "critical":
                return "URGENT: This critical-risk action requires immediate human review before proceeding."
            return "Please review the assessment details and approve or reject this action."
        if outcome == "ABSTAINED":
            return "REMORA declined to act. Review the blocking reasons and determine if the action should be retried with additional evidence."
        if outcome == "VERIFIED" and missing:
            return f"Action was approved for verification. Prioritize obtaining: {', '.join(missing[:3])}."
        if outcome == "VERIFIED":
            return "Spot-check the oracle assessments and confirm the action."
        return "No reviewer action needed — this was autonomously approved within policy bounds."
