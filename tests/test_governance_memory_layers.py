from __future__ import annotations

from remora.governance import MemoryLayer, MemoryLayerUpdate, default_memory_policy_registry


def test_default_memory_policies_are_multi_frequency() -> None:
    registry = default_memory_policy_registry()
    frequencies = {policy.update_frequency for policy in registry.policies}
    assert "per_request" in frequencies
    assert "per_case" in frequencies
    assert "per_decision" in frequencies
    assert "reviewed_change" in frequencies
    assert "append_only" in frequencies


def test_agent_cannot_write_policy_memory_layer() -> None:
    decision = default_memory_policy_registry().evaluate_update(
        MemoryLayerUpdate(
            layer=MemoryLayer.POLICY_MEMORY,
            actor="agent",
            approved_by_human=True,
            audit_trace_id="trace-1",
        )
    )
    assert decision.action == "ESCALATE"
    assert "agent_write_not_allowed" in decision.reasons


def test_policy_memory_requires_human_review_for_service_update() -> None:
    decision = default_memory_policy_registry().evaluate_update(
        MemoryLayerUpdate(
            layer=MemoryLayer.POLICY_MEMORY,
            actor="service",
            audit_trace_id="trace-1",
        )
    )
    assert decision.action == "ESCALATE"
    assert "writer_not_in_approved_set" in decision.reasons
    assert "human_review_required" in decision.reasons


def test_human_policy_memory_update_with_audit_accepts() -> None:
    decision = default_memory_policy_registry().evaluate_update(
        MemoryLayerUpdate(
            layer=MemoryLayer.POLICY_MEMORY,
            actor="human",
            approved_by_human=True,
            audit_trace_id="trace-1",
        )
    )
    assert decision.action == "ACCEPT"


def test_audit_ledger_is_append_only() -> None:
    decision = default_memory_policy_registry().evaluate_update(
        MemoryLayerUpdate(
            layer=MemoryLayer.AUDIT_LEDGER,
            actor="service",
            write_mode="replace",
            audit_trace_id="trace-1",
        )
    )
    assert decision.action == "ESCALATE"
    assert "append_only_layer_rejects_mutation" in decision.reasons
