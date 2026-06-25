from __future__ import annotations

import pytest

from remora.governance import ObservedGovernancePattern, PolicyProposalEngine


def test_policy_proposals_require_human_review_and_cannot_auto_apply() -> None:
    proposals = PolicyProposalEngine().generate(
        [
            ObservedGovernancePattern(
                pattern_type="tool_action_creep",
                domain="industrial_control",
                evidence_count=4,
                metric_delta=0.12,
                description="Tool execution rate increased after repeated overrides.",
            )
        ]
    )
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.requires_human_review is True
    assert proposal.can_auto_apply is False
    assert "authority_boundary_risk" in proposal.reasons


def test_policy_proposal_ids_are_deterministic() -> None:
    pattern = ObservedGovernancePattern(
        pattern_type="memory_contamination",
        domain="enterprise_agent",
        evidence_count=3,
        metric_delta=0.05,
        description="Persistent memory contains hidden instruction text.",
    )
    first = PolicyProposalEngine().generate([pattern])[0]
    second = PolicyProposalEngine().generate([pattern])[0]
    assert first.proposal_id == second.proposal_id


def test_policy_proposal_for_model_domain_failure_adds_regression_tests() -> None:
    proposal = PolicyProposalEngine().generate(
        [
            ObservedGovernancePattern(
                pattern_type="model_domain_failure",
                domain="regulated_decisioning",
                evidence_count=5,
                metric_delta=0.18,
                description="One model repeatedly failed on reviewed cases.",
            )
        ]
    )[0]
    assert "Reduce failing model weight" in proposal.recommended_change
    assert any(test.startswith("golden_model_failure") for test in proposal.tests_to_add)


def test_observed_pattern_requires_positive_evidence_count() -> None:
    with pytest.raises(ValueError):
        ObservedGovernancePattern(
            pattern_type="false_accept",
            domain="legal",
            evidence_count=0,
            metric_delta=0.1,
            description="bad",
        )
