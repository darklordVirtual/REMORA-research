# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Binding and lifetime contracts on ExecutionLease.verify (ADR-A/ADR-B).

`verify()` is the last thing that runs before a credential-holding dispatcher
executes. Each refusal below is a distinct named reason, and the names matter:
an operator reading `tenant_mismatch` in an audit chain learns something
`signature_invalid` would have hidden.

These are the checks the asymmetric change moved past. Coverage of them is not
a metric exercise -- if the signature path is rewritten and one of these stops
running, the lease still verifies and nothing else notices.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.enforcement.lease import (  # noqa: E402
    ExecutionLease,
    GovernedToolDispatcher,
)
from remora.enforcement.nonce_store import InMemoryNonceStore  # noqa: E402

ISSUED = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
CALL = {"tool_name": "wo_close", "arguments": {"id": "WO-1"},
        "tenant_id": "acme", "target_environment": "staging"}


@pytest.fixture(autouse=True)
def _hmac_key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "verification-contract-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC"):
        monkeypatch.delenv(name, raising=False)


def _lease(**over) -> ExecutionLease:
    kwargs = {"decision": "accept", "actor_identity": "agent-1",
              "policy_bundle_hash": "b1", "issued_at": ISSUED.isoformat(),
              **CALL}
    kwargs.update(over)
    return ExecutionLease.issue(**kwargs)


def _verify(lease, at=None, **over):
    call = {**CALL, **over}
    return lease.verify(now=(at or ISSUED).isoformat(),
                        actor_identity="agent-1", **call)


# ── lifetime ────────────────────────────────────────────────────────────────

def test_a_lease_is_refused_after_it_expires(monkeypatch):
    """The TTL is the freshness guarantee; past it the decision is stale."""
    lease = _lease()
    after = _parse_expiry(lease) + timedelta(seconds=1)
    result = _verify(lease, at=after)
    assert result.verified is False
    assert result.reason == "lease_expired"


def test_a_lease_is_refused_before_it_is_valid():
    """A future-dated issued_at must not mint a lease with an extended life.

    Without the not-before check, a clock-skewed or malicious issuer could set
    issued_at forward and obtain a lease whose usable window exceeds the TTL
    cap the issuer is supposed to be bound by.
    """
    lease = _lease()
    result = _verify(lease, at=ISSUED - timedelta(seconds=30))
    assert result.verified is False
    assert result.reason == "lease_not_yet_valid"


def test_a_tampered_timestamp_is_caught_as_forgery_before_it_is_parsed():
    """Order matters, and this is the order we want.

    expires_at is inside the signed payload, so rewriting it invalidates the
    signature -- and the signature check runs BEFORE the timestamp is parsed.
    The refusal is therefore `signature_invalid`, not `expiry_unparseable`:
    the lease is not a lease with a broken date, it is a forgery.

    Written expecting `expiry_unparseable` and corrected against the
    implementation. `expiry_unparseable` remains reachable only for a lease
    signed over a bad timestamp, which issue() will not produce -- so the
    parse guard is defence in depth behind the signature, which is the right
    place for it.
    """
    lease = ExecutionLease(**{**_lease().to_dict(), "expires_at": "whenever"})
    result = _verify(lease)
    assert result.verified is False
    assert result.reason == "signature_invalid"


def test_a_naive_timestamp_is_read_as_utc():
    """ISO-8601 without an offset is common in hand-written configuration.

    Treating it as UTC rather than rejecting it is the deliberate choice; the
    alternative is a lease that refuses for a reason nobody can see. Pinned so
    the interpretation cannot drift to local time, which would silently move
    every expiry by the host's offset.
    """
    naive = ISSUED.replace(tzinfo=None).isoformat()
    lease = _lease(issued_at=naive)
    assert _verify(lease).verified is True


# ── the binding ─────────────────────────────────────────────────────────────

def test_a_different_tool_is_refused_by_name():
    """A lease authorises one tool. The reason must say which check failed."""
    result = _verify(_lease(), tool_name="wo_delete")
    assert result.verified is False
    assert result.reason == "tool_name_mismatch"


def test_a_different_tenant_is_refused_by_name():
    """Cross-tenant use of a valid lease is refused as a tenancy failure.

    Reported distinctly from a signature failure: the lease IS authentic, and
    conflating the two would send an investigator after a forged-key theory.
    """
    result = _verify(_lease(), tenant_id="globex")
    assert result.verified is False
    assert result.reason == "tenant_mismatch"


def test_a_different_target_environment_is_refused():
    """Staging authority must not execute against production."""
    result = _verify(_lease(), target_environment="prod")
    assert result.verified is False
    assert result.reason == "target_environment_mismatch"


def test_the_legacy_signing_key_variable_is_still_honoured(monkeypatch):
    """REMORA_PDP_SIGNING_KEY is the historical name and still resolves.

    Deployments configured before the lease key had its own variable must keep
    verifying, or the migration silently refuses every call.
    """
    monkeypatch.delenv("REMORA_LEASE_SIGNING_KEY")
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "legacy-name")
    assert _verify(_lease()).verified is True


# ── dispatcher construction ─────────────────────────────────────────────────

def test_a_dispatcher_without_a_policy_bundle_hash_is_refused():
    """Stale-policy execution is prevented at construction, not at dispatch.

    An empty expected bundle would make every policy_bundle_hash compare equal
    to nothing and pass.
    """
    with pytest.raises(ValueError, match="expected_policy_bundle_hash"):
        GovernedToolDispatcher(expected_policy_bundle_hash="")


# ── a tool that raises, on the durable path ─────────────────────────────────

def test_a_raising_tool_burns_the_nonce_on_the_durable_path():
    """State at the tool is unknown, so the grant must NOT be reusable.

    The nonce is consumed before the call, so a tool that raises after
    reaching the remote system leaves the nonce spent. That is deliberate:
    re-running a call whose effect is unknown is worse than refusing it.
    """
    store = InMemoryNonceStore()
    dispatcher = GovernedToolDispatcher(
        expected_policy_bundle_hash="b1", nonce_store=store)

    def explode(_args):
        raise RuntimeError("remote system returned 500 after committing")

    dispatcher.register("wo_close", explode)
    lease = _lease()

    with pytest.raises(RuntimeError):
        dispatcher.dispatch(lease, actor_identity="agent-1",
                            now=ISSUED.isoformat(), **CALL)

    assert store.try_consume(lease.nonce, tenant_id="acme") is False, (
        "the nonce must stay spent after a tool raised")


def test_the_failed_execution_reason_is_lost_ACROSS_WORKERS():
    """The narrowed remainder of an asymmetry that used to be total.

    With the in-process NonceLedger, a retry after a raising tool is refused
    as `nonce_consumed_by_failed_execution`, which tells the caller the
    previous attempt may have had an effect. The durable branch records the
    burn reason in the in-process ledger, exactly as the other branch does,
    and used not to read it back, so that signal was unreachable for every
    deployment that configured a durable store. It is read back now, so the
    same worker gives the same answer on both backends.

    What is still asymmetric is the part that lives in memory. The
    CONSUMPTION is in the store and the burn REASON is not, so a retry that
    lands on a replacement container reads a plain `nonce_already_consumed`.
    Both refuse, so this is not a safety gap: no double execution occurs
    either way. It is a diagnosability gap, recorded here rather than left to
    be discovered during an incident. Carrying the burn reason into the
    durable store would close it and is not done in this change.
    """
    store = InMemoryNonceStore()
    dispatcher = GovernedToolDispatcher(
        expected_policy_bundle_hash="b1", nonce_store=store)
    dispatcher.register("wo_close", lambda _a: (_ for _ in ()).throw(
        RuntimeError("boom")))
    lease = _lease()

    with pytest.raises(RuntimeError):
        dispatcher.dispatch(lease, actor_identity="agent-1",
                            now=ISSUED.isoformat(), **CALL)

    same_worker = dispatcher.dispatch(lease, actor_identity="agent-1",
                                      now=ISSUED.isoformat(), **CALL)
    assert same_worker.executed is False
    assert same_worker.refusal_reason == "nonce_consumed_by_failed_execution"

    # A replacement container: the shared store, a fresh in-process ledger.
    replacement = GovernedToolDispatcher(
        expected_policy_bundle_hash="b1", nonce_store=store)
    replacement.register("wo_close", lambda _a: "unreached")

    retry = replacement.dispatch(lease, actor_identity="agent-1",
                                 now=ISSUED.isoformat(), **CALL)
    assert retry.executed is False
    assert retry.refusal_reason == "nonce_already_consumed", (
        "remaining asymmetry: the burn reason is in-process, so another "
        "worker reports a plain replay"
    )


def _parse_expiry(lease) -> datetime:
    return datetime.fromisoformat(lease.expires_at.replace("Z", "+00:00"))
