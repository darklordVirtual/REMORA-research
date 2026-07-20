# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for ExecutionLease + GovernedToolDispatcher (REM-024 groundwork).

Every non-accept decision must be technically unexecutable: no lease can be
issued for it, and the dispatcher refuses every call without a valid lease.
"""
from __future__ import annotations

import dataclasses

import pytest

from remora.enforcement.lease import (
    DEFAULT_LEASE_TTL_SECONDS,
    ExecutionLease,
    GovernedToolDispatcher,
    LeaseRefused,
    NonceLedger,
)
from remora.policy.observation import canonical_tool_call_hash

ISSUED_AT = "2026-07-20T12:00:00+00:00"
BEFORE_EXPIRY = "2026-07-20T12:01:00+00:00"
AFTER_EXPIRY = "2026-07-20T13:30:00+00:00"

TOOL = "unifi_set_vlan"
ARGS = {"site": "hq", "vlan_id": 42, "ports": ["eth0", "eth1"]}
TENANT = "luftfiber"
TARGET = "production"
BUNDLE = "sha256:policybundle01"


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "unit-test-lease-key")


def _issue(**overrides) -> ExecutionLease:
    params = dict(
        decision="accept",
        tenant_id=TENANT,
        actor_identity="agent-7",
        tool_name=TOOL,
        arguments=ARGS,
        target_environment=TARGET,
        policy_bundle_hash=BUNDLE,
        issued_at=ISSUED_AT,
    )
    params.update(overrides)
    return ExecutionLease.issue(**params)


def _dispatcher(**kwargs) -> GovernedToolDispatcher:
    calls: list[dict] = []

    def tool_fn(arguments: dict) -> str:
        calls.append(arguments)
        return "vlan-configured"

    d = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE, **kwargs)
    d.register(TOOL, tool_fn)
    d._test_calls = calls  # type: ignore[attr-defined]
    return d


# ── Issuance is fail-closed ────────────────────────────────────────────────


@pytest.mark.parametrize("decision", ["verify", "abstain", "escalate", "", "ACCEPT-ish"])
def test_issue_refuses_every_non_accept_decision(decision: str) -> None:
    with pytest.raises(LeaseRefused):
        _issue(decision=decision)


def test_issue_rejects_ttl_out_of_bounds() -> None:
    with pytest.raises(ValueError):
        _issue(expires_at=ISSUED_AT)  # ttl == 0
    with pytest.raises(ValueError):
        _issue(expires_at="2026-07-22T12:00:00+00:00")  # > max ttl


def test_issue_defaults_to_short_ttl_and_unique_nonce() -> None:
    a, b = _issue(), _issue()
    assert a.nonce and b.nonce and a.nonce != b.nonce
    assert a.expires_at == "2026-07-20T12:02:00+00:00"  # 120 s default
    assert DEFAULT_LEASE_TTL_SECONDS == 120
    assert a.is_signed


# ── Happy path ─────────────────────────────────────────────────────────────


def test_valid_lease_dispatches_exactly_once() -> None:
    d = _dispatcher()
    lease = _issue()
    out = d.dispatch(
        lease, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET, now=BEFORE_EXPIRY
    )
    assert out.executed is True
    assert out.refusal_reason is None
    assert out.result == "vlan-configured"
    assert d._test_calls == [ARGS]

    replay = d.dispatch(
        lease, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET, now=BEFORE_EXPIRY
    )
    assert replay.executed is False
    assert replay.refusal_reason == "nonce_already_consumed"
    assert d._test_calls == [ARGS]  # not executed twice


# ── Refusals ───────────────────────────────────────────────────────────────


def test_missing_lease_refused() -> None:
    d = _dispatcher()
    out = d.dispatch(None, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET)
    assert out.executed is False
    assert out.refusal_reason == "missing_lease"
    assert d._test_calls == []


def test_expired_lease_refused() -> None:
    d = _dispatcher()
    out = d.dispatch(
        _issue(), TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET, now=AFTER_EXPIRY
    )
    assert out.executed is False
    assert out.refusal_reason == "lease_expired"


def test_future_dated_lease_is_not_yet_valid() -> None:
    """A future-dated issued_at must not extend the usable lifetime.

    Regression (2026-07-20 adversarial verify): without a not-before check,
    issue(issued_at=now+10h) minted a lease dispatchable immediately AND for
    ten more hours — the TTL cap bounded only (expires_at - issued_at)."""
    d = _dispatcher()
    future = _issue(issued_at="2026-07-20T22:00:00+00:00")  # 10 h ahead of 'now'
    out = d.dispatch(
        future, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET, now=BEFORE_EXPIRY
    )
    assert out.executed is False
    assert out.refusal_reason == "lease_not_yet_valid"
    # Inside its declared window the same lease works.
    ok = d.dispatch(
        future, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET,
        now="2026-07-20T22:01:00+00:00",
    )
    assert ok.executed is True


def test_mutated_arguments_refused() -> None:
    """An accepted lease must not authorize different arguments."""
    d = _dispatcher()
    mutated = {**ARGS, "ports": ["eth0", "eth1", "uplink"]}
    out = d.dispatch(
        _issue(), TOOL, mutated, tenant_id=TENANT, target_environment=TARGET, now=BEFORE_EXPIRY
    )
    assert out.executed is False
    assert out.refusal_reason == "tool_args_hash_mismatch"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"tenant_id": "other-tenant"}, "tenant_mismatch"),
        ({"target_environment": "staging"}, "target_environment_mismatch"),
    ],
)
def test_context_mismatch_refused(kwargs: dict, reason: str) -> None:
    d = _dispatcher()
    call = dict(tenant_id=TENANT, target_environment=TARGET, now=BEFORE_EXPIRY)
    call.update(kwargs)
    out = d.dispatch(_issue(), TOOL, ARGS, **call)
    assert out.executed is False
    assert out.refusal_reason == reason


def test_unknown_tool_refused() -> None:
    d = _dispatcher()
    lease = _issue(tool_name="never_registered", arguments={})
    out = d.dispatch(
        lease, "never_registered", {}, tenant_id=TENANT, target_environment=TARGET,
        now=BEFORE_EXPIRY,
    )
    assert out.executed is False
    assert out.refusal_reason == "unknown_tool"


def test_policy_bundle_mismatch_refused() -> None:
    d = _dispatcher()
    stale = _issue(policy_bundle_hash="sha256:stale-bundle")
    out = d.dispatch(
        stale, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET, now=BEFORE_EXPIRY
    )
    assert out.executed is False
    assert out.refusal_reason == "policy_bundle_mismatch"


def test_tampered_fields_invalidate_signature() -> None:
    d = _dispatcher()
    lease = _issue()
    tampers = {
        "decision": "accept",  # baseline sanity: replaced below per-field
        "tenant_id": "other",
        "actor_identity": "evil-agent",
        "tool_name": "delete_everything",
        "tool_args_hash": canonical_tool_call_hash(
            name=TOOL, arguments={"x": 1}, tenant=TENANT, target=TARGET
        ),
        "target_environment": "staging",
        "policy_bundle_hash": "sha256:forged",
        "expires_at": "2026-07-20T23:59:00+00:00",
        "nonce": "forged-nonce",
    }
    for field, forged_value in tampers.items():
        if field == "decision":
            continue
        forged = dataclasses.replace(lease, **{field: forged_value})
        # Present the forged lease with call parameters matching its claims,
        # so only the signature check can catch it.
        out = d.dispatch(
            forged,
            forged.tool_name,
            ARGS if field != "tool_args_hash" else {"x": 1},
            tenant_id=forged.tenant_id,
            target_environment=forged.target_environment,
            now=BEFORE_EXPIRY,
        )
        assert out.executed is False, f"tampered {field} must not execute"
        assert out.refusal_reason in {
            "signature_invalid",
            "unknown_tool",
            "policy_bundle_mismatch",
        }, f"tampered {field}: {out.refusal_reason}"
        # The signature itself must never verify after tampering.
        assert not forged.verify(
            tool_name=forged.tool_name,
            arguments=ARGS if field != "tool_args_hash" else {"x": 1},
            tenant_id=forged.tenant_id,
            target_environment=forged.target_environment,
            now=BEFORE_EXPIRY,
        ).verified


def test_unsigned_lease_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REMORA_LEASE_SIGNING_KEY", raising=False)
    monkeypatch.delenv("REMORA_PDP_SIGNING_KEY", raising=False)
    unsigned = _issue()
    assert unsigned.is_signed is False

    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "unit-test-lease-key")
    d = _dispatcher()
    out = d.dispatch(
        unsigned, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET, now=BEFORE_EXPIRY
    )
    assert out.executed is False
    assert out.refusal_reason == "lease_not_signed"


def test_pdp_key_fallback_signs_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REMORA_LEASE_SIGNING_KEY", raising=False)
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "pdp-fallback-key")
    lease = _issue()
    assert lease.is_signed is True
    res = lease.verify(
        tool_name=TOOL, arguments=ARGS, tenant_id=TENANT,
        target_environment=TARGET, now=BEFORE_EXPIRY,
    )
    assert res.verified


def test_unparseable_expiry_fails_closed() -> None:
    lease = dataclasses.replace(_issue(), expires_at="not-a-timestamp")
    res = lease.verify(
        tool_name=TOOL, arguments=ARGS, tenant_id=TENANT,
        target_environment=TARGET, now=BEFORE_EXPIRY,
    )
    assert res.verified is False
    # Tampered expiry breaks the signature before expiry parsing is reached.
    assert res.reason in {"signature_invalid", "expiry_unparseable"}


# ── Serialization ──────────────────────────────────────────────────────────


def test_round_trip_and_unknown_field_rejection() -> None:
    lease = _issue()
    restored = ExecutionLease.from_dict(lease.to_dict())
    assert restored == lease
    with pytest.raises(ValueError):
        ExecutionLease.from_dict({**lease.to_dict(), "extra": 1})


def test_nonce_ledger_is_atomic_single_use() -> None:
    ledger = NonceLedger()
    assert ledger.consume("n-1") is True
    assert ledger.consume("n-1") is False
    assert ledger.consume("n-2") is True
