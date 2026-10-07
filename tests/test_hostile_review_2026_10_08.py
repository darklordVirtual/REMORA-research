# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regressions for the hostile security review of 2026-10-08 (H-01, H-03, H-06).

Each finding was checked against the code at 322541c before a change. Three
were concrete enough to close in code:

- H-01: a GovernedToolDispatcher without a durable nonce store fell back to
  the in-process NonceLedger under a strict profile, so a library or
  misconfigured deployment could get single-use per process only. A strict
  profile now refuses to dispatch on a process-local ledger
  (``nonce_store_not_durable``), before anything is recorded or consumed.
- H-03: a revoked lease signing key kept verifying v2 leases until they
  expired. ``REMORA_LEASE_REVOKED_KIDS`` names derived key ids that no longer
  authorize (``lease_key_revoked``).
- H-06: argument nesting had no bound, so a deep enough payload raised
  RecursionError instead of a refusal. ``_require_json_domain`` refuses
  nesting deeper than ``MAX_ARGUMENT_DEPTH``.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("cryptography")

from remora.crypto import SignatureDomain, SigningKey  # noqa: E402
from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher  # noqa: E402
from remora.enforcement.nonce_store import DurableNonceStore  # noqa: E402
from remora.policy.observation import (  # noqa: E402
    MAX_ARGUMENT_DEPTH,
    canonical_tool_call_hash,
)

SEED = "77" * 32
ARGS = {"id": "WO-1"}


def _public() -> str:
    return SigningKey.from_text(SEED, [SignatureDomain.EXECUTION_LEASE]) \
        .verification_key().public_bytes.hex()


@pytest.fixture
def v2(monkeypatch):
    for name in ("REMORA_LEASE_SIGNING_KEY", "REMORA_PDP_SIGNING_KEY",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_LEASE_REVOKED_KIDS",
                 "REMORA_RUNTIME_PROFILE", "REMORA_LEASE_SIGNING_KID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE", SEED)
    return monkeypatch


def _lease() -> ExecutionLease:
    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-1", tool_name="wo_close",
        arguments=ARGS, target_environment="prod", policy_bundle_hash="b1",
        issued_at=datetime.now(UTC).isoformat())


def _dispatch(dispatcher, lease):
    return dispatcher.dispatch(lease, "wo_close", ARGS, tenant_id="acme",
                               target_environment="prod", actor_identity="agent-1")


def _dispatcher(**kwargs) -> GovernedToolDispatcher:
    dispatcher = GovernedToolDispatcher("b1", **kwargs)
    dispatcher.register("wo_close", lambda args: "ok")
    return dispatcher


# -- H-01 --------------------------------------------------------------------------------------

def test_a_strict_profile_refuses_a_process_local_nonce_ledger(v2) -> None:
    lease = _lease()
    v2.setenv("REMORA_RUNTIME_PROFILE", "review/v1")
    v2.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
    dispatcher = _dispatcher()
    result = _dispatch(dispatcher, lease)
    assert result.refusal_reason == "nonce_store_not_durable"
    assert not result.executed and not result.dispatch_began
    assert lease.nonce not in dispatcher._ledger._consumed


def test_a_strict_profile_dispatches_on_a_durable_store(v2, tmp_path) -> None:
    lease = _lease()
    v2.setenv("REMORA_RUNTIME_PROFILE", "review/v1")
    v2.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
    dispatcher = _dispatcher(nonce_store=DurableNonceStore(db_path=str(tmp_path / "n.db")))
    result = _dispatch(dispatcher, lease)
    assert result.refusal_reason in (None, "runtime_identity_undeclared")


def test_research_keeps_the_in_process_ledger(v2) -> None:
    assert _dispatch(_dispatcher(), _lease()).executed


# -- H-03 --------------------------------------------------------------------------------------

def test_a_revoked_lease_key_no_longer_authorizes(v2) -> None:
    lease = _lease()
    assert lease.verify_authenticity().verified
    v2.setenv("REMORA_LEASE_REVOKED_KIDS", f"ed25519-other, {lease.kid}")
    assert lease.verify_authenticity().reason == "lease_key_revoked"
    assert not _dispatch(_dispatcher(), lease).executed


def test_revoking_another_key_changes_nothing(v2) -> None:
    lease = _lease()
    v2.setenv("REMORA_LEASE_REVOKED_KIDS", "ed25519-" + "0" * 64)
    assert lease.verify_authenticity().verified


def test_a_revoked_key_is_still_readable_as_history(v2) -> None:
    lease = _lease()
    v2.setenv("REMORA_LEASE_REVOKED_KIDS", lease.kid)
    assert lease.verify_historical().reason == "ok"


# -- H-06 --------------------------------------------------------------------------------------

def _nested(depth: int):
    value: object = "leaf"
    for _ in range(depth):
        value = {"k": value}
    return value


def test_deep_arguments_refuse_instead_of_recursing() -> None:
    canonical_tool_call_hash(name="t", arguments=_nested(MAX_ARGUMENT_DEPTH - 1))
    with pytest.raises(ValueError, match="nesting"):
        canonical_tool_call_hash(name="t", arguments=_nested(MAX_ARGUMENT_DEPTH + 1))
    with pytest.raises(ValueError, match="nesting"):
        canonical_tool_call_hash(name="t", arguments=_nested(5000))


def test_a_deep_call_is_refused_at_verify_not_crashed(v2) -> None:
    lease = _lease()
    result = _dispatcher().dispatch(lease, "wo_close", _nested(5000), tenant_id="acme",
                                    target_environment="prod", actor_identity="agent-1")
    assert not result.executed and result.refusal_reason is not None
