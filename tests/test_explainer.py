"""Tests for Explainable Decision Narratives."""

from remora.governance.envelope import (
    AssessmentBlock,
    AuditBlock,
    DecisionEnvelope,
    FollowUpBlock,
    GateBlock,
    HistoryBlock,
    RequestBlock,
    ReviewerContextBlock,
)
from remora.governance.explainer import DecisionExplainer, DecisionNarrative


def _envelope(outcome: str = "ACCEPTED", risk: str = "medium", missing: list[str] | None = None) -> DecisionEnvelope:
    return DecisionEnvelope(
        request=RequestBlock(
            request_id="REQ-001",
            domain="finance",
            risk_tier=risk,
            proposed_action="transfer_funds",
            action_type="write",
            target_environment="production",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[{"provider": "gpt4", "vote": "approve"}],
            thermodynamic={"lyapunov_value": 0.3},
            evidence_quality={"evidence_strength": 0.8},
            policy_triggers=["high_value_transfer"] if risk == "critical" else [],
        ),
        gate=GateBlock(
            outcome=outcome,
            blocked_action="transfer_funds" if outcome == "ABSTAINED" else None,
            allowed_next_steps=["retry_with_evidence"] if outcome == "ESCALATED" else [],
        ),
        reviewer_context=ReviewerContextBlock(
            missing_critical_data=missing or [],
        ),
        follow_up=FollowUpBlock(
            required=outcome == "ESCALATED",
            type="human_review" if outcome == "ESCALATED" else None,
            sla_hours=4 if outcome == "ESCALATED" else None,
        ),
        history=HistoryBlock(similar_cases_found=3, synthetic=True),
        audit=AuditBlock(policy_version="v2.1", hash="abcdef1234567890", previous_hash="0000000000000000"),
    )


class TestDecisionExplainer:
    def test_basic_narrative(self):
        explainer = DecisionExplainer()
        narrative = explainer.explain(_envelope())
        assert isinstance(narrative, DecisionNarrative)
        assert "REQ-001" in narrative.summary
        assert "approved for autonomous execution" in narrative.summary

    def test_escalated_narrative(self):
        explainer = DecisionExplainer()
        narrative = explainer.explain(_envelope(outcome="ESCALATED", risk="critical"))
        assert "escalated" in narrative.summary.lower()
        assert "URGENT" in narrative.recommended_action_for_reviewer

    def test_abstained_narrative(self):
        explainer = DecisionExplainer()
        narrative = explainer.explain(_envelope(outcome="ABSTAINED"))
        assert "blocked" in narrative.summary.lower() or "declined" in narrative.summary.lower()

    def test_missing_data_section(self):
        explainer = DecisionExplainer()
        narrative = explainer.explain(_envelope(missing=["bank_verification", "kyc_status"]))
        texts = [s.text for s in narrative.sections]
        assert any("bank_verification" in t for t in texts)

    def test_to_text_renders(self):
        explainer = DecisionExplainer()
        narrative = explainer.explain(_envelope())
        text = narrative.to_text()
        assert "What was proposed" in text
        assert "Recommendation:" in text

    def test_to_dict(self):
        explainer = DecisionExplainer()
        narrative = explainer.explain(_envelope())
        d = narrative.to_dict()
        assert "summary" in d
        assert "sections" in d
        assert len(d["sections"]) > 0

    def test_source_fields_populated(self):
        explainer = DecisionExplainer()
        narrative = explainer.explain(_envelope())
        for section in narrative.sections:
            assert len(section.source_fields) > 0, f"Section '{section.heading}' has no source_fields"

    def test_history_section_notes_synthetic(self):
        explainer = DecisionExplainer()
        narrative = explainer.explain(_envelope())
        history_sections = [s for s in narrative.sections if "historical" in s.heading.lower()]
        assert len(history_sections) == 1
        assert "synthetic" in history_sections[0].text.lower()
