"""Tests for DecisionEnvelope v2 schema in remora.governance.envelope."""
from __future__ import annotations

from remora.governance.envelope import (
    AuditBlock,
    AssessmentBlock,
    DecisionEnvelope,
    FollowUpBlock,
    GateBlock,
    HistoryBlock,
    PolicyLearningBlock,
    RequestBlock,
    ReviewerContextBlock,
    load_decision_envelope_schema,
    validate_decision_envelope_dict,
)


def test_minimal_envelope_roundtrip() -> None:
    """A minimal envelope with only required blocks serialises and deserialises."""
    env = DecisionEnvelope(
        request=RequestBlock(
            request_id="req-001",
            domain="well_engineering",
            risk_tier="critical",
            proposed_action="Increase mud weight",
            action_type="production_write",
            target_environment="live",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[],
            thermodynamic={},
            evidence_quality={},
            policy_triggers=[],
        ),
        gate=GateBlock(outcome="ESCALATE"),
    )
    d = env.to_dict()
    restored = DecisionEnvelope.from_dict(d)
    assert restored.request.request_id == "req-001"
    assert restored.gate.outcome == "ESCALATE"
    assert restored.gate.blocked_action is None


def test_full_envelope_with_all_blocks() -> None:
    """All optional blocks are preserved through roundtrip."""
    env = DecisionEnvelope(
        request=RequestBlock(
            request_id="req-002",
            domain="maintenance",
            risk_tier="high",
            proposed_action="Schedule C-4101 inspection",
            action_type="maintenance_request",
            target_environment="staging",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[{"provider": "a", "polarity": True}],
            thermodynamic={"phase": "ordered", "trust": 0.8},
            evidence_quality={"strength": 0.85},
            policy_triggers=["ordered_high_trust"],
        ),
        gate=GateBlock(
            outcome="ACCEPT",
            blocked_action=None,
            allowed_next_steps=["execute", "log"],
        ),
        reviewer_context=ReviewerContextBlock(
            asset={"unit": "C-4101"},
            missing_critical_data=["vibration_trend_24h"],
        ),
        follow_up=FollowUpBlock(
            required=False,
            type=None,
            requested_evidence=[],
            sla_hours=None,
        ),
        history=HistoryBlock(
            similar_cases_found=3,
            decision_pattern={"trend": "accept_mud_weight"},
            known_blockers=["missing_pressure_reading"],
        ),
        policy_learning=PolicyLearningBlock(
            candidate_rule_update=False,
            requires_policy_owner_approval=True,
        ),
        audit=AuditBlock(
            policy_version="v3.1",
            hash="abc123",
            previous_hash="prev456",
            signature=None,
        ),
    )
    d = env.to_dict()
    restored = DecisionEnvelope.from_dict(d)
    assert restored.follow_up.required is False
    assert restored.history.similar_cases_found == 3
    assert restored.audit.hash == "abc123"
    assert restored.gate.allowed_next_steps == ["execute", "log"]


def test_envelope_serialises_to_json_friendly_dict() -> None:
    """No nested types that json.dumps cannot handle."""
    import json

    env = DecisionEnvelope(
        request=RequestBlock(
            request_id="req-003",
            domain="safety",
            risk_tier="critical",
            proposed_action="Activate ESD",
            action_type="emergency_write",
            target_environment="live",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[], thermodynamic={}, evidence_quality={},
            policy_triggers=[],
        ),
        gate=GateBlock(outcome="VERIFY"),
    )
    d = env.to_dict()
    # Should not raise
    json_str = json.dumps(d)
    assert isinstance(json_str, str)


def test_missing_optional_blocks_use_defaults() -> None:
    """Omitted optional blocks get default factories."""
    env = DecisionEnvelope(
        request=RequestBlock(
            request_id="req-004",
            domain="test",
            risk_tier="low",
            proposed_action="Read log",
            action_type="read",
            target_environment="dev",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[], thermodynamic={}, evidence_quality={},
            policy_triggers=[],
        ),
        gate=GateBlock(outcome="ACCEPT"),
    )
    assert env.reviewer_context.missing_critical_data == []
    assert env.follow_up.required is False
    assert env.history.similar_cases_found == 0
    assert env.policy_learning.candidate_rule_update is False
    assert env.audit.hash is None


def test_from_dict_with_partial_data() -> None:
    """Deserialisation tolerates missing optional keys."""
    d = {
        "request": {
            "request_id": "req-005",
            "domain": " drilling",
            "risk_tier": "high",
            "proposed_action": "X",
            "action_type": "read",
            "target_environment": "dev",
        },
        "assessment": {
            "oracle_votes": [],
            "thermodynamic": {},
            "evidence_quality": {},
            "policy_triggers": [],
        },
        "gate": {"outcome": "ABSTAIN"},
    }
    env = DecisionEnvelope.from_dict(d)
    assert env.gate.outcome == "ABSTAIN"
    assert env.follow_up.required is False


def test_schema_contract_loaded_with_expected_top_level_required() -> None:
    schema = load_decision_envelope_schema()
    assert schema["type"] == "object"
    assert schema["required"] == [
        "request",
        "assessment",
        "gate",
        "reviewer_context",
        "follow_up",
        "history",
        "policy_learning",
        "audit",
    ]


def test_validate_decision_envelope_dict_accepts_valid_payload() -> None:
    env = DecisionEnvelope(
        request=RequestBlock(
            request_id="req-006",
            domain="security",
            risk_tier="high",
            proposed_action="Rotate tokens",
            action_type="maintenance_request",
            target_environment="prod",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[{"provider": "x", "answer": True}],
            thermodynamic={"phase": "ordered"},
            evidence_quality={"signal_source": "retrieval"},
            policy_triggers=["high_risk"],
        ),
        gate=GateBlock(outcome="verify"),
    )
    errors = validate_decision_envelope_dict(env.to_dict())
    assert errors == []


def test_validate_decision_envelope_dict_rejects_missing_required_block() -> None:
    env = DecisionEnvelope(
        request=RequestBlock(
            request_id="req-007",
            domain="security",
            risk_tier="high",
            proposed_action="Rotate tokens",
            action_type="maintenance_request",
            target_environment="prod",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[],
            thermodynamic={},
            evidence_quality={},
            policy_triggers=[],
        ),
        gate=GateBlock(outcome="verify"),
    )
    payload = env.to_dict()
    del payload["audit"]

    errors = validate_decision_envelope_dict(payload)
    assert any("missing required property 'audit'" in err for err in errors)


def test_audit_block_enterprise_fields_roundtrip_and_flat_dict() -> None:
    """All 7 enterprise AuditBlock fields survive to_dict/from_dict and appear in to_flat_dict."""
    env = DecisionEnvelope(
        request=RequestBlock(
            request_id="req-ent-001",
            domain="security",
            risk_tier="critical",
            proposed_action="Rotate API keys",
            action_type="maintenance_request",
            target_environment="prod",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[{"provider": "alpha", "vote": "ACCEPT"}],
            thermodynamic={"trust_score": 0.91, "entropy_H": 0.4, "dissensus_D": 0.1},
            evidence_quality={"score": 0.88},
            policy_triggers=["key_rotation_required"],
        ),
        gate=GateBlock(outcome="ACCEPT"),
        audit=AuditBlock(
            policy_version="v4.0",
            hash="hashval",
            previous_hash="prevhash",
            signature="sig",
            schema_version="2",
            timestamp_utc="2026-06-08T12:00:00+00:00",
            tenant_id="tenant-42",
            actor_identity="svc-account@remora.dev",
            policy_bundle_hash="sha256:bundle-abc123",
            tool_args_hash="sha256:toolargs-abc",
            data_classification="confidential",
            retention_policy="7y",
        ),
    )

    d = env.to_dict()
    restored = DecisionEnvelope.from_dict(d)

    assert restored.audit.schema_version == "2"
    assert restored.audit.timestamp_utc == "2026-06-08T12:00:00+00:00"
    assert restored.audit.tenant_id == "tenant-42"
    assert restored.audit.actor_identity == "svc-account@remora.dev"
    assert restored.audit.policy_bundle_hash == "sha256:bundle-abc123"
    assert restored.audit.tool_args_hash == "sha256:toolargs-abc"
    assert restored.audit.data_classification == "confidential"
    assert restored.audit.retention_policy == "7y"

    flat = env.to_flat_dict()
    assert flat["schema_version"] == "2"
    assert flat["timestamp_utc"] == "2026-06-08T12:00:00+00:00"
    assert flat["tenant_id"] == "tenant-42"
    assert flat["actor_identity"] == "svc-account@remora.dev"
    assert flat["policy_bundle_hash"] == "sha256:bundle-abc123"
    assert flat["tool_args_hash"] == "sha256:toolargs-abc"
    assert flat["data_classification"] == "confidential"
    assert flat["retention_policy"] == "7y"

    errors = validate_decision_envelope_dict(d)
    assert errors == [], f"Unexpected schema validation errors: {errors}"


def test_audit_block_enterprise_fields_have_backward_compatible_defaults() -> None:
    """Old code that creates AuditBlock() with no kwargs still works; new fields default correctly."""
    audit = AuditBlock(policy_version="v3", hash="h", previous_hash=None, signature=None)
    assert audit.schema_version == "2"
    assert audit.timestamp_utc is None
    assert audit.tenant_id is None
    assert audit.actor_identity is None
    assert audit.policy_bundle_hash is None
    assert audit.tool_args_hash is None
    assert audit.data_classification is None
    assert audit.retention_policy is None

    env = DecisionEnvelope(
        request=RequestBlock(
            request_id="r", domain="d", risk_tier="low",
            proposed_action="x", action_type="read", target_environment="dev",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[], thermodynamic={}, evidence_quality={}, policy_triggers=[],
        ),
        gate=GateBlock(outcome="ACCEPT"),
        audit=audit,
    )
    errors = validate_decision_envelope_dict(env.to_dict())
    assert errors == [], f"Backward-compat envelope failed schema: {errors}"


def test_tool_args_hash_is_deterministic_sha256() -> None:
    """tool_args_hash must be a deterministic 64-char hex SHA-256 string."""
    import hashlib
    import json as _json

    proposed_action = "Rotate API keys"
    action_type = "maintenance_request"
    expected_canonical = _json.dumps(
        {"action_type": action_type, "proposed_action": proposed_action},
        sort_keys=True,
        separators=(",", ":"),
    )
    expected_hash = hashlib.sha256(expected_canonical.encode("utf-8")).hexdigest()

    audit = AuditBlock(tool_args_hash=expected_hash)
    assert len(audit.tool_args_hash) == 64
    assert audit.tool_args_hash == expected_hash

    # Verify it survives roundtrip
    env = DecisionEnvelope(
        request=RequestBlock(
            request_id="r", domain="d", risk_tier="low",
            proposed_action=proposed_action, action_type=action_type,
            target_environment="dev",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[], thermodynamic={}, evidence_quality={}, policy_triggers=[],
        ),
        gate=GateBlock(outcome="ACCEPT"),
        audit=audit,
    )
    errors = validate_decision_envelope_dict(env.to_dict())
    assert errors == [], f"tool_args_hash envelope failed schema: {errors}"
    flat = env.to_flat_dict()
    assert flat["tool_args_hash"] == expected_hash
