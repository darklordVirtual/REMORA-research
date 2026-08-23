# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""ExecutionLease nonces must spend exactly once, durably (ADR-B).

`NonceLedger` is a threading.Lock and a set, and its docstring says so: a lease
is single-use PER PROCESS. On the Cloudflare deployment that is not a
theoretical caveat — containers are ephemeral by design and are replaced on
idle, so the one-time property of a lease has had the lifetime of a container.
A captured lease re-presented inside its expiry window after a replacement
executed a second time.

This is the same defect class as #350 (the consumed-jti ledger was in-process
on the same deployment) one layer up. The tests below are deliberately shaped
like `tests/test_gate_d1_ledger.py`, because the two ledgers must fail the same
way: refuse when unsure, and never burn a grant they could not record.

SQLite on a real file is used as the restart oracle. A reopened database is a
faithful stand-in for a replacement container reaching the same durable store,
and unlike a mock it exercises the actual UNIQUE-constraint path that provides
atomicity.
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.enforcement.lease import (  # noqa: E402
    ExecutionLease,
    GovernedToolDispatcher,
)
from remora.enforcement.nonce_store import (  # noqa: E402
    DurableNonceStore,
    InMemoryNonceStore,
    NonceStoreUnavailable,
)

ISSUED = datetime.now(UTC).isoformat()
BUNDLE = "bundle-1"
CALL = {"tool_name": "wo_close", "arguments": {"id": "WO-1"},
        "tenant_id": "acme", "target_environment": "staging"}
#: The dispatcher enforces the actor the lease was issued to, so every
#: dispatch in these tests presents it. Omitting it refuses earlier than the
#: nonce check and would make these tests pass for the wrong reason.
DISPATCH = {**CALL, "actor_identity": "agent-1", "now": ISSUED}


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    """Signed leases in the production shape, not a relaxed path."""
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "nonce-durability-test-key")


@pytest.fixture()
def db(tmp_path) -> str:
    return str(tmp_path / "execution-state.db")


@pytest.fixture()
def store(db) -> DurableNonceStore:
    return DurableNonceStore(db_path=db)


def _lease() -> ExecutionLease:
    return ExecutionLease.issue(
        decision="accept", actor_identity="agent-1",
        policy_bundle_hash=BUNDLE, issued_at=ISSUED, **CALL)


def _dispatcher(store, calls: list) -> GovernedToolDispatcher:
    d = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE,
                               nonce_store=store)
    d.register("wo_close", lambda args: calls.append(args) or "closed")
    return d


# ── the store itself ────────────────────────────────────────────────────────

def test_a_nonce_consumes_exactly_once(store):
    assert store.try_consume("n-1", tenant_id="acme") is True
    assert store.try_consume("n-1", tenant_id="acme") is False


def test_consumption_survives_a_new_store_over_the_same_database(db):
    """The restart scenario. This is the whole point of the change.

    With the in-process ledger the second instance starts empty and the
    captured lease is good again.
    """
    first = DurableNonceStore(db_path=db)
    assert first.try_consume("n-restart", tenant_id="acme") is True

    replacement = DurableNonceStore(db_path=db)
    assert replacement.try_consume("n-restart", tenant_id="acme") is False


def test_the_in_process_ledger_does_not_survive_that(monkeypatch):
    """The control. Named so the difference is visible, not assumed.

    If this ever starts passing, InMemoryNonceStore has quietly become durable
    and the test above has stopped proving anything.
    """
    first = InMemoryNonceStore()
    assert first.try_consume("n-restart", tenant_id="acme") is True
    assert InMemoryNonceStore().try_consume("n-restart", tenant_id="acme") is True


def test_tenants_do_not_share_a_nonce_namespace(store):
    """Tenant A must not be able to spend, or block, tenant B's grant."""
    assert store.try_consume("same-nonce", tenant_id="acme") is True
    assert store.try_consume("same-nonce", tenant_id="globex") is True
    assert store.consumed_count(tenant_id="acme") == 1
    assert store.consumed_count(tenant_id="globex") == 1


def test_an_unscoped_nonce_is_refused(store):
    """An empty tenant would put every unattributed lease in one namespace."""
    with pytest.raises(ValueError):
        store.try_consume("n-1", tenant_id="")


def test_concurrent_consumption_admits_exactly_one(db):
    """Atomicity comes from the database, so race it against itself."""
    winners: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def attempt() -> None:
        s = DurableNonceStore(db_path=db)
        barrier.wait()
        try:
            got = s.try_consume("n-race", tenant_id="acme")
        except NonceStoreUnavailable:
            got = False          # a locked-out writer is a refusal, not a win
        with lock:
            winners.append(got)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert winners.count(True) == 1, (
        f"exactly one consumer must win, got {winners.count(True)}")


def test_an_unreachable_store_raises_rather_than_reporting_unused(db, monkeypatch):
    """Unreachable never means unspent — assuming so IS the double-spend."""
    store = DurableNonceStore(db_path=db)

    def broken(*_a, **_k):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(sqlite3, "connect", broken)
    with pytest.raises(NonceStoreUnavailable):
        store.try_consume("n-outage", tenant_id="acme")


# ── the dispatcher, which is where it matters ───────────────────────────────

def test_a_replayed_lease_is_refused_by_a_replacement_dispatcher(db):
    """End to end: the captured-lease-after-container-replacement attack."""
    lease = _lease()
    calls: list = []

    first = _dispatcher(DurableNonceStore(db_path=db), calls)
    assert first.dispatch(lease, **DISPATCH).executed is True
    assert len(calls) == 1

    # The container is replaced. Same durable store, new process.
    replacement = _dispatcher(DurableNonceStore(db_path=db), calls)
    result = replacement.dispatch(lease, **DISPATCH)
    assert result.executed is False
    assert result.refusal_reason == "nonce_already_consumed"
    assert len(calls) == 1, "the tool must not have run a second time"


def test_an_unavailable_store_refuses_without_burning_the_grant(db, monkeypatch):
    """Failing closed must not destroy the authorization it could not record.

    An outage that silently consumed the nonce would turn a transient fault
    into a permanently unusable authorization — the same property pinned for
    the jti ledger in tests/test_gate_d1_ledger.py.
    """
    lease = _lease()
    calls: list = []
    dispatcher = _dispatcher(DurableNonceStore(db_path=db), calls)

    real_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: (_ for _ in ()).throw(
        sqlite3.OperationalError("store unreachable")))

    result = dispatcher.dispatch(lease, **DISPATCH)
    assert result.executed is False
    assert result.refusal_reason == "nonce_store_unavailable"
    assert calls == []

    # The store recovers; the grant was never spent, so it still works.
    monkeypatch.setattr(sqlite3, "connect", real_connect)
    recovered = dispatcher.dispatch(lease, **DISPATCH)
    assert recovered.executed is True, (
        "an outage must not permanently destroy a valid authorization")


def test_the_durable_store_takes_precedence_over_the_in_process_ledger(db):
    """A configured durable store must not be shadowed by the default set.

    This is the shape of the #350 defect: a durable backend present in the
    configuration and never actually consulted.
    """
    lease = _lease()
    calls: list = []
    dispatcher = _dispatcher(DurableNonceStore(db_path=db), calls)
    assert dispatcher.dispatch(lease, **DISPATCH).executed is True

    probe = DurableNonceStore(db_path=db)
    assert probe.try_consume(lease.nonce, tenant_id=lease.tenant_id) is False, (
        "the consumption was recorded in the in-process set, not the store")


# ── the deployed wiring, which is where the #350 defect class lives ─────────

def test_the_execution_api_builds_a_durable_store_for_every_admitted_backend(
        monkeypatch):
    """The defect class, pinned at the wiring rather than at the store.

    tests/test_gate_d1_ledger.py pins the same property for the jti ledger:
    a durable backend that the durability guard admits and the consumer never
    learns to use is worse than no backend, because the deployment passes its
    own check and then silently uses memory.

    This asserts the lease nonce store is built from the SAME three variables.
    If a fourth backend is ever added to the guard, this test is where it must
    also be given to the dispatcher.
    """
    import importlib

    from servers import execution_api

    for backend, kwarg in (("REMORA_PG_DSN", "_dsn"),
                           ("REMORA_CHAIN_DB", "_db_path"),
                           ("REMORA_STATE_ENDPOINT", "_state_endpoint")):
        for name in ("REMORA_PG_DSN", "REMORA_CHAIN_DB",
                     "REMORA_STATE_ENDPOINT"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(backend, "configured-value")
        importlib.reload(execution_api) if False else None
        store = execution_api._lease_nonce_store()
        assert store is not None, (
            f"{backend} is admitted by the durability guard but produced no "
            f"lease nonce store; the dispatcher would fall back to the "
            f"in-process NonceLedger"
        )
        assert getattr(store, kwarg) == "configured-value"


def test_no_durable_backend_leaves_the_in_process_ledger(monkeypatch):
    """Library and research use keeps the honest in-process ledger."""
    from servers import execution_api

    for name in ("REMORA_PG_DSN", "REMORA_CHAIN_DB", "REMORA_STATE_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    assert execution_api._lease_nonce_store() is None
