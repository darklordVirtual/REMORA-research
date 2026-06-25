from __future__ import annotations

import pytest

from remora.governance import (
    GovernanceForgettingDetector,
    GovernanceForgettingEvent,
    LayerUpdateRequest,
    default_nested_governance_model,
)


def test_default_nested_governance_layers_are_multi_frequency() -> None:
    model = default_nested_governance_model()
    frequencies = {layer.update_frequency for layer in model.layers}
    assert "per_request" in frequencies
    assert "per_decision" in frequencies
    assert "reviewed_change" in frequencies
    assert "append_only" in frequencies
    assert model.layer("runtime_context") is not None
    assert model.layer("audit_ledger") is not None


def test_agent_cannot_write_policy_memory() -> None:
    model = default_nested_governance_model()
    decision = model.evaluate_update(
        LayerUpdateRequest(
            layer_name="policy_memory",
            actor="agent",
            update_type="policy_change",
            approved=False,
            metadata={"audit_trace_id": "trace-1"},
        )
    )
    assert decision.action == "ESCALATE"
    assert "agent_write_not_allowed" in decision.reasons


def test_audit_ledger_is_append_only() -> None:
    model = default_nested_governance_model()
    decision = model.evaluate_update(
        LayerUpdateRequest(
            layer_name="audit_ledger",
            actor="service",
            update_type="rewrite",
            approved=True,
            append_only=False,
            metadata={"audit_trace_id": "trace-1"},
        )
    )
    assert decision.action == "ESCALATE"
    assert "append_only_layer_rejects_mutation" in decision.reasons


def test_reviewed_change_requires_approval_and_audit() -> None:
    model = default_nested_governance_model()
    decision = model.evaluate_update(
        LayerUpdateRequest(
            layer_name="project_memory",
            actor="service",
            update_type="architecture_note",
            approved=False,
        )
    )
    assert decision.action == "VERIFY"
    assert "reviewed_change_required" in decision.reasons
    assert "audit_trace_required" in decision.reasons


def test_unknown_layer_abstains() -> None:
    model = default_nested_governance_model()
    decision = model.evaluate_update(LayerUpdateRequest(layer_name="unknown", actor="service", update_type="x"))
    assert decision.action == "ABSTAIN"
    assert decision.layer is None


def test_governance_forgetting_detector_accepts_clean_history() -> None:
    report = GovernanceForgettingDetector().evaluate([])
    assert report.action == "ACCEPT"
    assert report.reasons == ("no_governance_forgetting_detected",)


def test_governance_forgetting_detector_verifies_temporary_pattern() -> None:
    report = GovernanceForgettingDetector().evaluate(
        [
            GovernanceForgettingEvent(
                event_type="exception",
                layer_name="policy_memory",
                description="Temporary exception reused by later workflow.",
                temporary_exception=True,
                became_pattern=True,
                approved=True,
            )
        ]
    )
    assert report.action == "VERIFY"
    assert "temporary_exception_became_pattern" in report.reasons


def test_governance_forgetting_detector_escalates_ignored_escalation_and_override() -> None:
    events = [
        GovernanceForgettingEvent(
            event_type="route_override",
            layer_name="trust_memory",
            description="Agent ignored an escalation route.",
            ignored_abstain_or_escalate=True,
            policy_override=True,
            approved=False,
        ),
        GovernanceForgettingEvent(
            event_type="route_override",
            layer_name="policy_memory",
            description="Second override.",
            policy_override=True,
            approved=False,
        ),
        GovernanceForgettingEvent(
            event_type="route_override",
            layer_name="policy_memory",
            description="Third override.",
            policy_override=True,
            approved=True,
        ),
    ]
    report = GovernanceForgettingDetector().evaluate(events)
    assert report.action == "ESCALATE"
    assert "ignored_abstain_or_escalate" in report.reasons
    assert "unapproved_policy_override" in report.reasons
    assert "repeated_policy_override" in report.reasons


def test_detector_rejects_bad_threshold() -> None:
    with pytest.raises(ValueError):
        GovernanceForgettingDetector(repeated_override_threshold=0)
