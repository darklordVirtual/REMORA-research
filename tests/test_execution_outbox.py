# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""FT-02 slice 1: the crash-consistent execution outbox store.

The outbox is the durable record of DISPATCH INTENT: a row written in the
same transaction that authorizes a call, claimed by exactly one worker,
and driven to a terminal state that is never auto-retried once a side
effect may have happened. This suite pins the store's contract for both
the in-process reference and the SQLite adapter (parametrized — an
adapter that diverges is a defect, not a variant).

Declared scope: the store and its state machine. Wiring it into
``/v1/execution`` is slice 2; the reconciler policy for stale
``DISPATCHING`` rows is exercised here as a store operation, not as a
running daemon.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remora.enforcement.outbox import (
    ExecutionOutbox,
    OutboxState,
    SQLiteExecutionOutbox,
    idempotency_key,
)

PROPOSAL = "11111111-2222-3333-4444-555555555555"
CALL_HASH = "a" * 64


@pytest.fixture(params=["memory", "sqlite"])
def outbox(request, tmp_path):
    if request.param == "memory":
        return ExecutionOutbox()
    return SQLiteExecutionOutbox(str(tmp_path / "outbox.db"))


def _intent(outbox, *, proposal_id=PROPOSAL, tenant="acme", attempt_no=1,
            tool_name="store_artifact", tool_call_hash=CALL_HASH,
            item_id="item-1", grant_jti="jti-1"):
    return outbox.record_intent(
        proposal_id=proposal_id,
        tenant_id=tenant,
        item_id=item_id,
        tool_name=tool_name,
        tool_call_hash=tool_call_hash,
        grant_jti=grant_jti,
        attempt_no=attempt_no,
    )


# ── Idempotency key ─────────────────────────────────────────────────────────

def test_idempotency_key_is_deterministic_and_attempt_scoped() -> None:
    k1 = idempotency_key(PROPOSAL, CALL_HASH, 1)
    assert k1 == idempotency_key(PROPOSAL, CALL_HASH, 1)
    assert k1 != idempotency_key(PROPOSAL, CALL_HASH, 2)
    assert k1 != idempotency_key(PROPOSAL, "b" * 64, 1)
    assert len(k1) == 64


@settings(max_examples=200, deadline=None)
@given(
    proposal=st.text(min_size=1, max_size=40),
    call_hash=st.text(min_size=1, max_size=40),
    attempt=st.integers(min_value=1, max_value=50),
    other_attempt=st.integers(min_value=1, max_value=50),
)
def test_key_collides_only_on_identical_inputs(
    proposal: str, call_hash: str, attempt: int, other_attempt: int
) -> None:
    """Searched validation over the declared input domain: two keys are
    equal iff every component is equal. No counterexample found."""
    a = idempotency_key(proposal, call_hash, attempt)
    b = idempotency_key(proposal, call_hash, other_attempt)
    assert (a == b) == (attempt == other_attempt)


# ── Intent recording is exactly-once per attempt ────────────────────────────

def test_intent_starts_dispatch_pending(outbox) -> None:
    row = _intent(outbox)
    assert row.state is OutboxState.DISPATCH_PENDING
    assert row.idempotency_key == idempotency_key(PROPOSAL, CALL_HASH, 1)
    assert row.attempt_no == 1


def test_duplicate_intent_returns_the_same_row(outbox) -> None:
    """A retried authorize must not create a second dispatch intent."""
    first = _intent(outbox)
    second = _intent(outbox)
    assert second.outbox_id == first.outbox_id
    assert len(outbox.pending("acme")) == 1


def test_reapproval_attempt_gets_its_own_row(outbox) -> None:
    first = _intent(outbox)
    second = _intent(outbox, attempt_no=2)
    assert second.outbox_id != first.outbox_id
    assert len(outbox.pending("acme")) == 2


def test_tenants_are_isolated(outbox) -> None:
    _intent(outbox, tenant="acme")
    _intent(outbox, tenant="globex")
    assert len(outbox.pending("acme")) == 1
    assert len(outbox.pending("globex")) == 1


# ── Claiming is exclusive ───────────────────────────────────────────────────

def test_claim_is_exclusive(outbox) -> None:
    row = _intent(outbox)
    claimed = outbox.claim(row.outbox_id, worker_id="worker-a")
    assert claimed is not None
    assert claimed.state is OutboxState.DISPATCHING
    assert claimed.worker_id == "worker-a"
    # A second worker must lose the race, not steal an in-flight dispatch.
    assert outbox.claim(row.outbox_id, worker_id="worker-b") is None


def test_claimed_row_leaves_the_pending_set(outbox) -> None:
    row = _intent(outbox)
    outbox.claim(row.outbox_id, worker_id="worker-a")
    assert outbox.pending("acme") == []


# ── Terminal states are absorbing; UNKNOWN never auto-retries ──────────────

@pytest.mark.parametrize("state", [
    OutboxState.SUCCEEDED, OutboxState.FAILED,
    OutboxState.REFUSED, OutboxState.UNKNOWN,
])
def test_terminal_states_reject_further_transitions(outbox, state) -> None:
    row = _intent(outbox)
    outbox.claim(row.outbox_id, worker_id="w")
    outbox.settle(row.outbox_id, state, detail="done")
    with pytest.raises(ValueError):
        outbox.settle(row.outbox_id, OutboxState.SUCCEEDED, detail="again")
    with pytest.raises(ValueError):
        outbox.claim(row.outbox_id, worker_id="w2")


def test_settle_requires_a_claimed_row(outbox) -> None:
    row = _intent(outbox)
    with pytest.raises(ValueError):
        outbox.settle(row.outbox_id, OutboxState.SUCCEEDED, detail="never claimed")


def test_stale_dispatching_reconciles_to_unknown_not_retry(outbox) -> None:
    """F-02 window (c): after a possible effect, UNKNOWN is the honest
    terminal — the row must never return to the pending set."""
    row = _intent(outbox)
    outbox.claim(row.outbox_id, worker_id="w",
                 now=datetime(2026, 1, 1, tzinfo=UTC))
    stale = outbox.reconcile_stale(
        "acme",
        older_than=timedelta(minutes=5),
        now=datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
    )
    assert [r.outbox_id for r in stale] == [row.outbox_id]
    assert outbox.get(row.outbox_id).state is OutboxState.UNKNOWN
    assert outbox.pending("acme") == []


def test_fresh_dispatching_is_not_reconciled(outbox) -> None:
    row = _intent(outbox)
    outbox.claim(row.outbox_id, worker_id="w",
                 now=datetime(2026, 1, 1, tzinfo=UTC))
    stale = outbox.reconcile_stale(
        "acme",
        older_than=timedelta(minutes=5),
        now=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
    )
    assert stale == []
    assert outbox.get(row.outbox_id).state is OutboxState.DISPATCHING


# ── Durability: the SQLite adapter survives a restart ──────────────────────

def test_sqlite_rows_survive_a_new_instance(tmp_path) -> None:
    path = str(tmp_path / "outbox.db")
    first = SQLiteExecutionOutbox(path)
    row = _intent(first)
    first.claim(row.outbox_id, worker_id="w")

    reopened = SQLiteExecutionOutbox(path)
    restored = reopened.get(row.outbox_id)
    assert restored.state is OutboxState.DISPATCHING
    assert restored.worker_id == "w"
    # And the uniqueness constraint still holds across the "restart".
    again = _intent(reopened)
    assert again.outbox_id == row.outbox_id


# ── The store's states are the lifecycle model's states ────────────────────

def test_outbox_states_are_declared_in_the_lifecycle_schema() -> None:
    from remora.governance.lifecycle import default_model

    model = default_model()
    for state in OutboxState:
        assert state.value in model.states, state


def test_concurrent_claims_have_exactly_one_winner(outbox) -> None:
    """The safety property: N workers race, at most one dispatches.

    Threaded rather than simulated — a lock that only works in theory is
    the failure mode this test exists to catch.
    """
    import threading

    row = _intent(outbox)
    winners: list[str] = []
    barrier = threading.Barrier(8)

    def worker(name: str) -> None:
        barrier.wait()
        claimed = outbox.claim(row.outbox_id, worker_id=name)
        if claimed is not None:
            winners.append(name)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(winners) == 1, winners
    assert outbox.get(row.outbox_id).worker_id == winners[0]


# ── Enlistment: the row lives or dies with the caller's transaction ─────────
#
# This is the atomicity property FT-02 needs from the store: "outbox row
# written in the SAME transaction that authorizes the call" is only true if
# a rollback of that transaction also removes the row. Proven here at store
# level, independent of the execution API, so the wiring slice inherits a
# verified guarantee instead of asserting one.

def test_enlisted_intent_commits_with_the_callers_transaction(tmp_path) -> None:
    import sqlite3

    path = str(tmp_path / "shared.db")
    outbox = SQLiteExecutionOutbox(path)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("CREATE TABLE IF NOT EXISTS caller_state (k TEXT PRIMARY KEY)")

    conn.execute("BEGIN IMMEDIATE")
    row = outbox.record_intent_enlisted(
        conn,
        proposal_id=PROPOSAL, tenant_id="acme", item_id="item-1",
        tool_name="store_artifact", tool_call_hash=CALL_HASH,
        grant_jti="jti-1",
    )
    conn.execute("INSERT INTO caller_state (k) VALUES ('authorized')")
    conn.execute("COMMIT")
    conn.close()

    assert outbox.get(row.outbox_id).state is OutboxState.DISPATCH_PENDING
    assert len(outbox.pending("acme")) == 1


def test_enlisted_intent_rolls_back_with_the_callers_transaction(tmp_path) -> None:
    """The load-bearing case: authorization aborts, no dispatch intent
    survives — the client can safely re-call, exactly crash-matrix row 1."""
    import sqlite3

    path = str(tmp_path / "shared.db")
    outbox = SQLiteExecutionOutbox(path)
    conn = sqlite3.connect(path, isolation_level=None)

    conn.execute("BEGIN IMMEDIATE")
    row = outbox.record_intent_enlisted(
        conn,
        proposal_id=PROPOSAL, tenant_id="acme", item_id="item-1",
        tool_name="store_artifact", tool_call_hash=CALL_HASH,
        grant_jti="jti-1",
    )
    conn.execute("ROLLBACK")
    conn.close()

    assert outbox.pending("acme") == []
    with pytest.raises(KeyError):
        outbox.get(row.outbox_id)


def test_enlisted_intent_is_idempotent_within_the_transaction(tmp_path) -> None:
    import sqlite3

    path = str(tmp_path / "shared.db")
    outbox = SQLiteExecutionOutbox(path)
    conn = sqlite3.connect(path, isolation_level=None)

    conn.execute("BEGIN IMMEDIATE")
    first = outbox.record_intent_enlisted(
        conn, proposal_id=PROPOSAL, tenant_id="acme", item_id="item-1",
        tool_name="store_artifact", tool_call_hash=CALL_HASH, grant_jti="j",
    )
    second = outbox.record_intent_enlisted(
        conn, proposal_id=PROPOSAL, tenant_id="acme", item_id="item-1",
        tool_name="store_artifact", tool_call_hash=CALL_HASH, grant_jti="j",
    )
    conn.execute("COMMIT")
    conn.close()

    assert second.outbox_id == first.outbox_id
    assert len(outbox.pending("acme")) == 1


def test_enlisted_intent_sees_a_committed_row_from_another_connection(tmp_path) -> None:
    """A retried authorize on a fresh connection must find the prior row."""
    import sqlite3

    path = str(tmp_path / "shared.db")
    outbox = SQLiteExecutionOutbox(path)
    first = _intent(outbox)

    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("BEGIN IMMEDIATE")
    again = outbox.record_intent_enlisted(
        conn, proposal_id=PROPOSAL, tenant_id="acme", item_id="item-1",
        tool_name="store_artifact", tool_call_hash=CALL_HASH, grant_jti="jti-1",
    )
    conn.execute("COMMIT")
    conn.close()
    assert again.outbox_id == first.outbox_id


def test_memory_outbox_refuses_enlistment_rather_than_faking_it() -> None:
    """The in-process store cannot join a database transaction; saying so
    is the honest answer, not silently ignoring the connection."""
    outbox = ExecutionOutbox()
    with pytest.raises(NotImplementedError):
        outbox.record_intent_enlisted(
            object(), proposal_id=PROPOSAL, tenant_id="acme", item_id="i",
            tool_name="t", tool_call_hash=CALL_HASH, grant_jti="j",
        )


# ── Postgres adapter: contract-tested against a real service ───────────────
#
# DSN-gated like the tenant-chain contract tests; the CI job that provides a
# real Postgres service runs them with a hard no-skip check, so "the
# multi-worker adapter is unverified" can never quietly become true again.

pg_dsn = pytest.mark.skipif(
    not __import__("os").environ.get("REMORA_PG_DSN", "").strip(),
    reason="REMORA_PG_DSN not set (contract test needs a real Postgres)",
)


@pytest.fixture()
def pg_outbox():
    import os
    import uuid as _uuid

    from remora.enforcement.outbox import PostgresExecutionOutbox

    dsn = os.environ["REMORA_PG_DSN"]
    outbox = PostgresExecutionOutbox(dsn)
    # Tenant per test: the table is shared, isolation must not be assumed.
    return outbox, f"acme-{_uuid.uuid4().hex[:8]}"


@pg_dsn
def test_postgres_intent_is_idempotent_per_attempt(pg_outbox) -> None:
    outbox, tenant = pg_outbox
    first = _intent(outbox, tenant=tenant)
    second = _intent(outbox, tenant=tenant)
    assert second.outbox_id == first.outbox_id
    assert len(outbox.pending(tenant)) == 1
    third = _intent(outbox, tenant=tenant, attempt_no=2)
    assert third.outbox_id != first.outbox_id


@pg_dsn
def test_postgres_claim_is_exclusive(pg_outbox) -> None:
    outbox, tenant = pg_outbox
    row = _intent(outbox, tenant=tenant)
    assert outbox.claim(row.outbox_id, worker_id="a") is not None
    assert outbox.claim(row.outbox_id, worker_id="b") is None
    assert outbox.get(row.outbox_id).worker_id == "a"


@pg_dsn
def test_postgres_terminal_states_are_absorbing(pg_outbox) -> None:
    outbox, tenant = pg_outbox
    row = _intent(outbox, tenant=tenant)
    outbox.claim(row.outbox_id, worker_id="a")
    outbox.settle(row.outbox_id, OutboxState.SUCCEEDED, detail="ok")
    with pytest.raises(ValueError):
        outbox.settle(row.outbox_id, OutboxState.FAILED, detail="again")
    with pytest.raises(ValueError):
        outbox.claim(row.outbox_id, worker_id="b")


@pg_dsn
def test_postgres_stale_dispatching_reconciles_to_unknown(pg_outbox) -> None:
    outbox, tenant = pg_outbox
    row = _intent(outbox, tenant=tenant)
    outbox.claim(row.outbox_id, worker_id="a",
                 now=datetime(2026, 1, 1, tzinfo=UTC))
    stale = outbox.reconcile_stale(
        tenant, older_than=timedelta(minutes=5),
        now=datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
    )
    assert [r.outbox_id for r in stale] == [row.outbox_id]
    assert outbox.get(row.outbox_id).state is OutboxState.UNKNOWN
    assert outbox.pending(tenant) == []


@pg_dsn
def test_postgres_enlisted_intent_rolls_back_with_the_caller(pg_outbox) -> None:
    """The multi-worker atomicity property: authorization aborts, the
    dispatch intent goes with it."""
    import os

    import psycopg

    outbox, tenant = pg_outbox
    with psycopg.connect(os.environ["REMORA_PG_DSN"]) as conn:
        # psycopg rolls the block back on Rollback — the idiomatic
        # equivalent of an authorization that aborts mid-transaction.
        with conn.transaction():
            outbox.record_intent_enlisted(
                conn, proposal_id=PROPOSAL, tenant_id=tenant, item_id="i",
                tool_name="store_artifact", tool_call_hash=CALL_HASH,
                grant_jti="j",
            )
            raise psycopg.Rollback
    assert outbox.pending(tenant) == []


@pg_dsn
def test_postgres_enlisted_intent_commits_with_the_caller(pg_outbox) -> None:
    import os

    import psycopg

    outbox, tenant = pg_outbox
    with psycopg.connect(os.environ["REMORA_PG_DSN"]) as conn:
        with conn.transaction():
            row = outbox.record_intent_enlisted(
                conn, proposal_id=PROPOSAL, tenant_id=tenant, item_id="i",
                tool_name="store_artifact", tool_call_hash=CALL_HASH,
                grant_jti="j",
            )
    assert outbox.get(row.outbox_id).state is OutboxState.DISPATCH_PENDING


# ── State-machine refusals (self-review 2026-08-20) ─────────────────────────
#
# outbox.py is the file that decides whether a dispatch intent may be settled,
# and it was the second-least-covered file in the trusted computing base
# (69.7% with branches). These cover the refusal branches: every one of them
# exists so a row cannot be moved to a state that misrepresents what actually
# happened to the side effect.


def test_settling_an_unclaimed_row_through_the_normal_path_is_refused(
    outbox,
) -> None:
    """Only a claimed (DISPATCHING) row can be settled normally."""
    row = _intent(outbox)
    with pytest.raises(ValueError, match="only a claimed"):
        outbox.settle(row.outbox_id, OutboxState.SUCCEEDED, detail="skipped claim")


def test_settling_into_a_non_terminal_state_is_refused(outbox) -> None:
    row = _intent(outbox)
    outbox.claim(row.outbox_id, worker_id="w1")
    with pytest.raises(ValueError, match="not a terminal"):
        outbox.settle(
            row.outbox_id, OutboxState.DISPATCH_PENDING, detail="backwards"
        )


def test_unknown_row_raises_key_error(outbox) -> None:
    with pytest.raises(KeyError, match="unknown outbox row"):
        outbox.claim("no-such-row", worker_id="w1")


def test_reconcile_stale_only_touches_claimed_rows(outbox) -> None:
    """An unclaimed intent is not the stale reconciler's business.

    Claim strictly precedes invocation, so a never-claimed row has no
    undeterminable side effect and must not be settled as UNKNOWN.
    """
    from datetime import timedelta

    row = _intent(outbox)
    settled = outbox.reconcile_stale("acme", older_than=timedelta(seconds=-1))
    assert [r.outbox_id for r in settled] == []
    assert outbox.get(row.outbox_id).state is OutboxState.DISPATCH_PENDING


def test_reconcile_stale_settles_a_claimed_row_as_unknown(outbox) -> None:
    """UNKNOWN, never a retry: the worker may have invoked the tool before dying."""
    from datetime import timedelta

    row = _intent(outbox)
    outbox.claim(row.outbox_id, worker_id="w1")
    settled = outbox.reconcile_stale("acme", older_than=timedelta(seconds=-1))
    assert [r.outbox_id for r in settled] == [row.outbox_id]
    assert outbox.get(row.outbox_id).state is OutboxState.UNKNOWN


def test_reconcile_unclaimed_settles_a_pending_row_as_failed(outbox) -> None:
    """Authorized but never claimed: nothing was dispatched, so FAILED is honest."""
    from datetime import timedelta

    row = _intent(outbox)
    settled = outbox.reconcile_unclaimed("acme", older_than=timedelta(seconds=-1))
    assert [r.outbox_id for r in settled] == [row.outbox_id]
    assert outbox.get(row.outbox_id).state is OutboxState.FAILED


def test_reconcile_unclaimed_leaves_claimed_rows_alone(outbox) -> None:
    from datetime import timedelta

    row = _intent(outbox)
    outbox.claim(row.outbox_id, worker_id="w1")
    settled = outbox.reconcile_unclaimed("acme", older_than=timedelta(seconds=-1))
    assert [r.outbox_id for r in settled] == []
    assert outbox.get(row.outbox_id).state is OutboxState.DISPATCHING


def test_reconcilers_scope_to_one_tenant(outbox) -> None:
    from datetime import timedelta

    mine = _intent(outbox, tenant="acme", item_id="a", grant_jti="j-a")
    theirs = _intent(outbox, tenant="other", item_id="b", grant_jti="j-b")
    outbox.reconcile_unclaimed("acme", older_than=timedelta(seconds=-1))
    assert outbox.get(mine.outbox_id).state is OutboxState.FAILED
    assert outbox.get(theirs.outbox_id).state is OutboxState.DISPATCH_PENDING
