# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for the A2A governance envelope: identity, delegation attenuation,
policy/evidence binding, and fail-closed verification."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from remora.governance.a2a_envelope import (
    PROTOCOL_VERSION,
    A2AGovernanceEnvelope,
    AgentIdentity,
    DelegationLink,
)

KEY = b"test-a2a-signing-key"
# Envelopes are issued with the real clock; verify against the real clock so
# the issued-in-future guard (clock-skew tolerance 300s) does not trip.
NOW = datetime.now(timezone.utc)


def _identity(**overrides) -> AgentIdentity:
    defaults = dict(
        agent_id="agent://maintenance-planner/07",
        agent_version="2.4.1",
        issuer_org="operator-coe",
        responsible_org="operator-asset-team",
    )
    defaults.update(overrides)
    return AgentIdentity(**defaults)


def _chain() -> tuple[DelegationLink, ...]:
    return (
        DelegationLink(
            delegator="operator-coe",
            delegatee="agent://orchestrator/01",
            scope=("workorder:read", "workorder:propose_change", "telemetry:read"),
            issued_at=NOW.isoformat(),
        ),
        DelegationLink(
            delegator="agent://orchestrator/01",
            delegatee="agent://maintenance-planner/07",
            scope=("workorder:read", "workorder:propose_change"),
            issued_at=NOW.isoformat(),
        ),
    )


AUDIENCE = "control-plane://operator-remora"


def _issue(**overrides) -> A2AGovernanceEnvelope:
    kwargs = dict(
        identity=_identity(),
        delegation_chain=_chain(),
        requested_scope=("workorder:propose_change",),
        policy_version="RemoraDecisionEngine-v3",
        audience=AUDIENCE,
        decision_ref="envelope:2f6a…",
        evidence_refs=("sha256:abc123",),
        signing_key=KEY,
    )
    kwargs.update(overrides)
    return A2AGovernanceEnvelope.issue(**kwargs)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_envelope_verifies() -> None:
    env = _issue()
    result = env.verify(signing_key=KEY, now=NOW)
    assert result.valid, result.failures
    assert env.protocol == PROTOCOL_VERSION
    assert env.is_signed


def test_round_trip_json_preserves_verification() -> None:
    env = _issue()
    restored = A2AGovernanceEnvelope.from_json(env.to_json())
    result = restored.verify(signing_key=KEY, now=NOW)
    assert result.valid, result.failures


def test_effective_scope_is_chain_intersection() -> None:
    env = _issue()
    assert env.effective_scope() == {"workorder:read", "workorder:propose_change"}


# ---------------------------------------------------------------------------
# Fail closed: integrity
# ---------------------------------------------------------------------------

def test_unsigned_envelope_is_invalid(monkeypatch) -> None:
    monkeypatch.delenv("REMORA_A2A_SIGNING_KEY", raising=False)
    env = _issue(signing_key=None)  # no key available anywhere → unsigned
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert "unsigned_envelope" in result.failures


def test_tampered_scope_breaks_signature() -> None:
    env = _issue()
    data = json.loads(env.to_json())
    data["requested_scope"] = ["workorder:read", "workorder:approve"]
    tampered = A2AGovernanceEnvelope.from_json(json.dumps(data))
    result = tampered.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert "signature_mismatch" in result.failures


def test_wrong_key_fails() -> None:
    env = _issue()
    result = env.verify(signing_key=b"other-key", now=NOW)
    assert not result.valid
    assert "signature_mismatch" in result.failures


# ---------------------------------------------------------------------------
# Fail closed: accountability and policy binding
# ---------------------------------------------------------------------------

def test_missing_responsible_org_is_invalid() -> None:
    env = _issue(identity=_identity(responsible_org="  "))
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert "missing_responsible_org" in result.failures


def test_missing_policy_version_is_invalid() -> None:
    env = _issue(policy_version="")
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert "missing_policy_version" in result.failures


# ---------------------------------------------------------------------------
# Delegation attenuation
# ---------------------------------------------------------------------------

def test_scope_widening_is_rejected() -> None:
    widening_chain = (
        _chain()[0],
        DelegationLink(
            delegator="agent://orchestrator/01",
            delegatee="agent://maintenance-planner/07",
            # Tries to add a capability its delegator never had:
            scope=("workorder:read", "workorder:approve"),
            issued_at=NOW.isoformat(),
        ),
    )
    env = _issue(delegation_chain=widening_chain,
                 requested_scope=("workorder:read",))
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert any(f.startswith("scope_widened_at_link:1") for f in result.failures)


def test_request_outside_delegated_scope_is_rejected() -> None:
    env = _issue(requested_scope=("ot:actuate_valve",))
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert any(f.startswith("scope_exceeds_delegation") for f in result.failures)


def test_wildcard_scope_is_rejected() -> None:
    chain = (
        DelegationLink(
            delegator="operator-coe",
            delegatee="agent://maintenance-planner/07",
            scope=("workorder:*",),
            issued_at=NOW.isoformat(),
        ),
    )
    env = _issue(delegation_chain=chain, requested_scope=("workorder:read",))
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert any(f.startswith("wildcard_scope_at_link") for f in result.failures)


def test_broken_delegation_chain_is_rejected() -> None:
    chain = (
        _chain()[0],
        DelegationLink(
            delegator="agent://someone-else/99",  # not the previous delegatee
            delegatee="agent://maintenance-planner/07",
            scope=("workorder:read",),
            issued_at=NOW.isoformat(),
        ),
    )
    env = _issue(delegation_chain=chain, requested_scope=("workorder:read",))
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert any(f.startswith("broken_chain_at_link") for f in result.failures)


def test_final_delegatee_must_be_acting_agent() -> None:
    chain = (
        DelegationLink(
            delegator="operator-coe",
            delegatee="agent://other-agent/01",
            scope=("workorder:read",),
            issued_at=NOW.isoformat(),
        ),
    )
    env = _issue(delegation_chain=chain, requested_scope=("workorder:read",))
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert "final_delegatee_is_not_acting_agent" in result.failures


def test_empty_delegation_chain_is_rejected() -> None:
    env = _issue(delegation_chain=())
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert "empty_delegation_chain" in result.failures


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

def test_expired_envelope_is_invalid() -> None:
    env = _issue(expires_at=(NOW - timedelta(minutes=1)).isoformat())
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert "envelope_expired" in result.failures


def test_expired_delegation_link_is_invalid() -> None:
    chain = (
        DelegationLink(
            delegator="operator-coe",
            delegatee="agent://maintenance-planner/07",
            scope=("workorder:read",),
            issued_at=(NOW - timedelta(days=2)).isoformat(),
            expires_at=(NOW - timedelta(days=1)).isoformat(),
        ),
    )
    env = _issue(delegation_chain=chain, requested_scope=("workorder:read",))
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert any(f.startswith("delegation_link_expired") for f in result.failures)


def test_all_failures_are_reported_together(monkeypatch) -> None:
    """Audit consumers get the complete defect set, not just the first."""
    monkeypatch.delenv("REMORA_A2A_SIGNING_KEY", raising=False)
    env = _issue(
        identity=_identity(responsible_org=""),
        policy_version="",
        delegation_chain=(),
        requested_scope=(),
        signing_key=None,
    )
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert {
        "unsigned_envelope",
        "missing_responsible_org",
        "missing_policy_version",
        "empty_delegation_chain",
        "empty_requested_scope",
    } <= set(result.failures)


# ---------------------------------------------------------------------------
# Hardening: audience, replay, argument binding, timestamps, per-link keys
# ---------------------------------------------------------------------------

def test_missing_audience_is_invalid() -> None:
    env = _issue(audience="")
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert "missing_audience" in result.failures


def test_audience_mismatch_is_invalid() -> None:
    env = _issue()
    result = env.verify(
        signing_key=KEY, now=NOW, expected_audience="control-plane://someone-else"
    )
    assert not result.valid
    assert "audience_mismatch" in result.failures


def test_replay_guard_rejects_seen_nonce() -> None:
    env = _issue()
    seen: set[str] = set()

    def guard(nonce: str) -> bool:
        replayed = nonce in seen
        seen.add(nonce)
        return replayed

    first = env.verify(signing_key=KEY, now=NOW, replay_guard=guard)
    assert first.valid, first.failures
    second = env.verify(signing_key=KEY, now=NOW, replay_guard=guard)
    assert not second.valid
    assert "replay_detected" in second.failures


def test_tool_call_binding_mismatch_is_invalid() -> None:
    env = _issue(tool_call_hash="a" * 64)
    result = env.verify(
        signing_key=KEY, now=NOW, expected_tool_call_hash="b" * 64
    )
    assert not result.valid
    assert "tool_call_binding_mismatch" in result.failures


def test_missing_tool_call_binding_when_required() -> None:
    env = _issue()  # no binding set
    result = env.verify(
        signing_key=KEY, now=NOW, expected_tool_call_hash="b" * 64
    )
    assert not result.valid
    assert "missing_tool_call_binding" in result.failures


def test_matching_tool_call_binding_is_valid() -> None:
    env = _issue(tool_call_hash="c" * 64)
    result = env.verify(
        signing_key=KEY, now=NOW, expected_tool_call_hash="c" * 64
    )
    assert result.valid, result.failures


def test_malformed_timestamp_is_failure_not_exception() -> None:
    env = _issue(expires_at="not-a-timestamp")
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert "malformed_timestamp:expires_at" in result.failures


def test_future_issued_at_is_rejected() -> None:
    import json as _json
    from remora.governance.a2a_envelope import A2AGovernanceEnvelope as Env
    env = _issue()
    data = _json.loads(env.to_json())
    data["issued_at"] = (NOW + timedelta(hours=2)).isoformat()
    tampered = Env.from_json(_json.dumps(data))
    result = tampered.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    # Both the future timestamp and the broken signature must surface.
    assert "issued_in_future" in result.failures
    assert "signature_mismatch" in result.failures


def test_from_json_fails_closed_on_malformed_input() -> None:
    import pytest
    for raw in ("not json", "[]", '{"identity": {}}', '{"unexpected": 1}'):
        with pytest.raises(ValueError, match="malformed_envelope:"):
            A2AGovernanceEnvelope.from_json(raw)


def test_link_registry_verifies_signed_chain() -> None:
    from remora.governance.a2a_envelope import RegisteredKey, sign_delegation_link
    coe_key, orch_key = b"coe-key", b"orchestrator-key"
    registry = {
        "coe-2026": RegisteredKey(key=coe_key, principal="operator-coe"),
        "orch-2026": RegisteredKey(key=orch_key, principal="agent://orchestrator/01"),
    }
    root, hop = _chain()
    chain = (
        sign_delegation_link(root, key=coe_key, kid="coe-2026"),
        sign_delegation_link(hop, key=orch_key, kid="orch-2026"),
    )
    env = _issue(delegation_chain=chain)
    result = env.verify(signing_key=KEY, now=NOW, link_keys=registry)
    assert result.valid, result.failures


def test_forged_link_signature_is_rejected() -> None:
    from remora.governance.a2a_envelope import RegisteredKey, sign_delegation_link
    registry = {
        "coe-2026": RegisteredKey(key=b"coe-key", principal="operator-coe"),
        "orch-2026": RegisteredKey(key=b"orchestrator-key", principal="agent://orchestrator/01"),
    }
    root, hop = _chain()
    chain = (
        sign_delegation_link(root, key=b"coe-key", kid="coe-2026"),
        # Envelope issuer forges the second hop with a key it controls:
        sign_delegation_link(hop, key=b"attacker-key", kid="orch-2026"),
    )
    env = _issue(delegation_chain=chain)
    result = env.verify(signing_key=KEY, now=NOW, link_keys=registry)
    assert not result.valid
    assert "link_signature_mismatch:1" in result.failures


def test_revoked_kid_invalidates_chain() -> None:
    from remora.governance.a2a_envelope import RegisteredKey, sign_delegation_link
    root, hop = _chain()
    chain = (
        sign_delegation_link(root, key=b"coe-key", kid="coe-2026"),
        sign_delegation_link(hop, key=b"orchestrator-key", kid="orch-2026"),
    )
    env = _issue(delegation_chain=chain)
    # Absent from registry entirely -> unknown/revoked.
    result = env.verify(
        signing_key=KEY, now=NOW,
        link_keys={"coe-2026": RegisteredKey(key=b"coe-key", principal="operator-coe")},
    )
    assert not result.valid
    assert any(
        f.startswith("unknown_or_revoked_kid_at_link:1") for f in result.failures
    )
    # Present but explicitly revoked -> revoked failure code.
    result2 = env.verify(
        signing_key=KEY, now=NOW,
        link_keys={
            "coe-2026": RegisteredKey(key=b"coe-key", principal="operator-coe"),
            "orch-2026": RegisteredKey(
                key=b"orchestrator-key", principal="agent://orchestrator/01",
                revoked=True,
            ),
        },
    )
    assert not result2.valid
    assert any(f.startswith("revoked_kid_at_link:1") for f in result2.failures)


def test_unsigned_links_rejected_when_registry_supplied() -> None:
    from remora.governance.a2a_envelope import RegisteredKey
    env = _issue()  # links carry no signatures
    result = env.verify(
        signing_key=KEY, now=NOW,
        link_keys={"coe-2026": RegisteredKey(key=b"coe-key", principal="operator-coe")},
    )
    assert not result.valid
    assert "unsigned_delegation_link:0" in result.failures


# ---------------------------------------------------------------------------
# Hardening round 2: principal binding, strict parsing, link timestamps
# ---------------------------------------------------------------------------

def test_valid_key_wrong_principal_is_rejected() -> None:
    """P1 review finding: a registered key must not be able to sign a link
    that names a different principal as delegator."""
    from remora.governance.a2a_envelope import RegisteredKey, sign_delegation_link
    root, hop = _chain()
    chain = (
        sign_delegation_link(root, key=b"coe-key", kid="coe-2026"),
        # The attacker holds a valid registered key ("attacker-2026") and uses
        # it to sign a link claiming the orchestrator as delegator:
        sign_delegation_link(hop, key=b"attacker-key", kid="attacker-2026"),
    )
    registry = {
        "coe-2026": RegisteredKey(key=b"coe-key", principal="operator-coe"),
        "attacker-2026": RegisteredKey(key=b"attacker-key", principal="agent://attacker/66"),
    }
    env = _issue(delegation_chain=chain)
    result = env.verify(signing_key=KEY, now=NOW, link_keys=registry)
    assert not result.valid
    assert any(
        f.startswith("kid_principal_mismatch_at_link:1") for f in result.failures
    )


def test_string_requested_scope_is_rejected_by_parser() -> None:
    """P2 review finding: a string must not silently become a tuple of
    single characters."""
    import json as _json
    import pytest
    env = _issue()
    data = _json.loads(env.to_json())
    data["requested_scope"] = "workorder:propose_change"  # str, not list
    with pytest.raises(ValueError, match="malformed_envelope:"):
        A2AGovernanceEnvelope.from_json(_json.dumps(data))


def test_numeric_identity_field_is_rejected_by_parser() -> None:
    import json as _json
    import pytest
    env = _issue()
    data = _json.loads(env.to_json())
    data["identity"]["responsible_org"] = 12345
    with pytest.raises(ValueError, match="malformed_envelope:"):
        A2AGovernanceEnvelope.from_json(_json.dumps(data))


def test_non_string_field_is_failure_not_exception_in_verify() -> None:
    """Directly constructed envelopes with wrong types fail closed."""
    env = _issue(identity=_identity(responsible_org=None))
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert "malformed_field:responsible_org" in result.failures


def test_link_issued_in_future_is_rejected() -> None:
    chain = (
        DelegationLink(
            delegator="operator-coe",
            delegatee="agent://maintenance-planner/07",
            scope=("workorder:read",),
            issued_at=(NOW + timedelta(hours=3)).isoformat(),
        ),
    )
    env = _issue(delegation_chain=chain, requested_scope=("workorder:read",))
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert any(
        f.startswith("delegation_link_issued_in_future:0") for f in result.failures
    )


def test_malformed_link_issued_at_is_failure_not_exception() -> None:
    chain = (
        DelegationLink(
            delegator="operator-coe",
            delegatee="agent://maintenance-planner/07",
            scope=("workorder:read",),
            issued_at="not-a-date",
        ),
    )
    env = _issue(delegation_chain=chain, requested_scope=("workorder:read",))
    result = env.verify(signing_key=KEY, now=NOW)
    assert not result.valid
    assert any(
        f.startswith("malformed_timestamp:delegation_link_issued_at:0")
        for f in result.failures
    )


# ---------------------------------------------------------------------------
# Hardening round 4: nonce consumption semantics + parser crypto fields
# ---------------------------------------------------------------------------

def test_invalid_envelope_does_not_consume_nonce() -> None:
    """Round-4 P1/P2: a tampered envelope carrying a victim's nonce must NOT
    burn it — otherwise the replay guard becomes a DoS primitive."""
    env = _issue()
    seen: set[str] = set()

    def guard(nonce: str) -> bool:
        replayed = nonce in seen
        seen.add(nonce)
        return replayed

    # Attacker tampers the envelope (breaks the signature) but keeps the nonce.
    data = json.loads(env.to_json())
    data["requested_scope"] = ["workorder:read", "ot:actuate_valve"]
    tampered = A2AGovernanceEnvelope.from_json(json.dumps(data))
    attack = tampered.verify(signing_key=KEY, now=NOW, replay_guard=guard)
    assert not attack.valid
    assert "replay_detected" not in attack.failures
    assert env.nonce not in seen  # nonce NOT consumed by the invalid envelope

    # The legitimate envelope still verifies afterwards.
    legit = env.verify(signing_key=KEY, now=NOW, replay_guard=guard)
    assert legit.valid, legit.failures
    # ...and a genuine replay is still caught.
    replayed = env.verify(signing_key=KEY, now=NOW, replay_guard=guard)
    assert not replayed.valid
    assert "replay_detected" in replayed.failures


def test_parser_rejects_wrong_typed_crypto_fields() -> None:
    """Round-4 P2: signature/is_signed/tool_call_hash/link crypto fields are
    validated at parse time, not first inside verification."""
    import pytest
    env = _issue()
    base = json.loads(env.to_json())
    mutations = [
        ("signature", 12345),
        ("is_signed", "yes"),
        ("tool_call_hash", 999),
        ("expires_at", 17),
    ]
    for field_name, bad_value in mutations:
        data = json.loads(json.dumps(base))
        data[field_name] = bad_value
        with pytest.raises(ValueError, match="malformed_envelope:"):
            A2AGovernanceEnvelope.from_json(json.dumps(data))
    # Link-level crypto fields
    for field_name, bad_value in [("signature", 1), ("kid", 2),
                                  ("delegator", None), ("delegatee", 3)]:
        data = json.loads(json.dumps(base))
        data["delegation_chain"][0][field_name] = bad_value
        with pytest.raises(ValueError, match="malformed_envelope:"):
            A2AGovernanceEnvelope.from_json(json.dumps(data))
