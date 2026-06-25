"""Tests for DecisionEnvelope hash determinism and flat serialization."""
import hashlib
import json

from remora.governance.envelope import (
    AssessmentBlock,
    DecisionEnvelope,
    GateBlock,
    RequestBlock,
)


def _make_envelope(request_id: str = "test-001") -> DecisionEnvelope:
    return DecisionEnvelope(
        request=RequestBlock(
            request_id=request_id,
            domain="database",
            risk_tier="critical",
            proposed_action="DELETE FROM users WHERE id=42",
            action_type="destructive_write",
            target_environment="prod",
        ),
        assessment=AssessmentBlock(
            oracle_votes=[{"oracle": "alpha", "vote": "ESCALATE"}],
            thermodynamic={"trust_score": 0.35, "entropy_H": 1.2, "dissensus_D": 0.65},
            evidence_quality={"score": 0.6},
            policy_triggers=["PROD_WRITE_CRITICAL"],
        ),
        gate=GateBlock(outcome="ESCALATE"),
    )


def test_envelope_hash_is_string():
    env = _make_envelope()
    h = env.envelope_hash()
    assert isinstance(h, str)
    assert len(h) == 64, "SHA-256 hex digest must be 64 characters"


def test_envelope_hash_is_deterministic():
    """Same inputs must produce same hash on every call."""
    env1 = _make_envelope("req-abc")
    env2 = _make_envelope("req-abc")
    assert env1.envelope_hash() == env2.envelope_hash()


def test_envelope_hash_changes_when_outcome_changes():
    """Different verdict must produce different hash."""
    env_accept = DecisionEnvelope(
        request=RequestBlock("r1", "db", "low", "SELECT 1", "read", "dev"),
        assessment=AssessmentBlock([], {}, {}, []),
        gate=GateBlock(outcome="ACCEPT"),
    )
    env_escalate = DecisionEnvelope(
        request=RequestBlock("r1", "db", "low", "SELECT 1", "read", "dev"),
        assessment=AssessmentBlock([], {}, {}, []),
        gate=GateBlock(outcome="ESCALATE"),
    )
    assert env_accept.envelope_hash() != env_escalate.envelope_hash()


def test_to_flat_dict_contains_required_keys():
    """to_flat_dict() must expose canonical safety-relevant fields at top level."""
    env = _make_envelope()
    flat = env.to_flat_dict()
    required = {
        "request_id", "domain", "action_type", "risk_tier",
        "proposed_action", "verdict", "policy_triggers",
        "envelope_hash",
    }
    missing = required - flat.keys()
    assert not missing, f"to_flat_dict() missing required keys: {missing}"


def test_to_flat_dict_verdict_matches_gate_outcome():
    env = _make_envelope()
    flat = env.to_flat_dict()
    assert flat["verdict"] == env.gate.outcome


def test_to_flat_dict_is_json_serializable():
    env = _make_envelope()
    flat = env.to_flat_dict()
    serialized = json.dumps(flat)
    assert isinstance(serialized, str)


def test_envelope_hash_matches_manual_computation():
    """Verify hash is computed from exactly the documented canonical fields."""
    env = _make_envelope("manual-test")
    flat = env.to_flat_dict()
    canonical = json.dumps({
        "request_id":     flat["request_id"],
        "domain":         flat["domain"],
        "action_type":    flat["action_type"],
        "risk_tier":      flat["risk_tier"],
        "proposed_action": flat["proposed_action"],
        "verdict":        flat["verdict"],
        "policy_triggers": flat["policy_triggers"],
    }, sort_keys=True, separators=(",", ":"))
    expected_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert flat["envelope_hash"] == expected_hash
