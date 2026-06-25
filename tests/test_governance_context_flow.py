from __future__ import annotations

import pytest

from remora.governance import ContextFlow, ContextFlowUpdate, default_context_flow_registry


def test_default_context_flows_cover_nested_governance_streams() -> None:
    registry = default_context_flow_registry()
    names = {flow.name for flow in registry.flows}
    assert {
        "runtime_context",
        "oracle_context",
        "evidence_context",
        "trust_context",
        "policy_context",
        "audit_context",
    }.issubset(names)


def test_agent_cannot_write_policy_context() -> None:
    decision = default_context_flow_registry().evaluate_update(
        ContextFlowUpdate(
            flow_name="policy_context",
            actor="agent",
            source="agent_memory",
            payload_type="policy_change",
            audit_trace_id="trace-1",
            approved=True,
        )
    )
    assert decision.action == "ESCALATE"
    assert "actor_not_allowed_for_context_flow" in decision.reasons


def test_high_risk_evidence_context_requires_review_and_audit() -> None:
    decision = default_context_flow_registry().evaluate_update(
        ContextFlowUpdate(
            flow_name="evidence_context",
            actor="service",
            source="retrieval",
            payload_type="source_snapshot",
        )
    )
    assert decision.action == "VERIFY"
    assert "audit_trace_required" in decision.reasons
    assert "review_required_for_high_risk_context" in decision.reasons


def test_runtime_context_accepts_agent_current_task_update() -> None:
    decision = default_context_flow_registry().evaluate_update(
        ContextFlowUpdate(
            flow_name="runtime_context",
            actor="agent",
            source="current_task",
            payload_type="tool_result",
        )
    )
    assert decision.action == "ACCEPT"
    assert decision.reasons == ("context_flow_update_allowed",)


def test_context_flow_rejects_empty_sources() -> None:
    with pytest.raises(ValueError):
        ContextFlow(
            name="runtime_context",
            sources=(),
            update_frequency="per_request",
            writable_by_agent=True,
            retention="short",
            risk="low",
            trust_boundary="request_window",
            audit_required=False,
            description="bad",
        )
