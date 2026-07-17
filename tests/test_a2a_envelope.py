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
NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)


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


def _issue(**overrides) -> A2AGovernanceEnvelope:
    kwargs = dict(
        identity=_identity(),
        delegation_chain=_chain(),
        requested_scope=("workorder:propose_change",),
        policy_version="RemoraDecisionEngine-v3",
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
