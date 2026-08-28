# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Fault injection for the multi-worker outbox against a real Postgres.

Until 2026-08-27 the Postgres adapter had six contract tests, all
single-threaded and sequential. Concurrency, worker death and the projection
columns were exercised only against the in-process and SQLite stores
(``tests/test_execution_outbox.py``, ``tests/test_dispatch_worker.py``,
``tests/test_execution_fault_injection.py``). An external review of
2026-08-27 named that gap; this file closes the part that a real server can
show. Every test here needs ``REMORA_PG_DSN`` and carries "postgres" in its
name so the ``postgres-contract`` CI job selects it and fails on a skip.

What a real server adds over SQLite: genuine row locks between separate
backends (``SELECT ... FOR UPDATE`` blocking, not ``BEGIN IMMEDIATE``
serialisation), backend termination as a stand-in for a worker process that
dies mid-transaction, and the projection columns the SQLite tests never
touch on this adapter.

Scope, stated plainly: these tests inject faults at transaction and backend
level. They do not kill OS processes, partition networks or exhaust
connection pools. A worker that dies *between* transactions leaves the same
row state as a worker that simply stopped, which is what the reconciler
tests cover.
"""
from __future__ import annotations

import os
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from remora.enforcement.outbox import OutboxState

pg_dsn = pytest.mark.skipif(
    not os.environ.get("REMORA_PG_DSN", "").strip(),
    reason="REMORA_PG_DSN not set (fault injection needs a real Postgres)",
)

PROPOSAL = "11111111-2222-3333-4444-555555555555"
CALL_HASH = "b" * 64


@pytest.fixture()
def pg():
    from remora.enforcement.outbox import PostgresExecutionOutbox

    dsn = os.environ["REMORA_PG_DSN"]
    return PostgresExecutionOutbox(dsn), f"fi-{uuid.uuid4().hex[:8]}", dsn


def _intent(outbox, tenant, *, item_id="item-1", attempt_no=1):
    return outbox.record_intent(
        proposal_id=PROPOSAL, tenant_id=tenant, item_id=item_id,
        tool_name="store_artifact", tool_call_hash=CALL_HASH,
        grant_jti=f"jti-{item_id}-{attempt_no}", attempt_no=attempt_no,
    )


# ── (c) two workers racing for the same row, in-flight simultaneously ───────


@pg_dsn
def test_postgres_concurrent_claims_have_exactly_one_winner(pg) -> None:
    """Eight backends take ``FOR UPDATE`` on the same row at once. The lock
    serialises them; the first to commit wins and every later transaction
    re-reads ``DISPATCHING`` and returns None. No exception, no double
    claim."""
    outbox, tenant, _ = pg
    row = _intent(outbox, tenant)
    n = 8
    barrier = threading.Barrier(n)
    results: list[object] = [None] * n
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            barrier.wait(timeout=10)
            results[i] = outbox.claim(row.outbox_id, worker_id=f"w{i}")
        except Exception as exc:  # noqa: BLE001 - collected for the assert
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    final = outbox.get(row.outbox_id)
    assert final.state is OutboxState.DISPATCHING
    assert final.worker_id == winners[0].worker_id
    assert outbox.pending(tenant) == []


@pg_dsn
def test_postgres_claim_blocks_on_a_held_lock_then_loses(pg) -> None:
    """A foreign transaction holds the row lock. The adapter's claim must
    block rather than fail, and once the holder commits its own claim the
    blocked claimer sees DISPATCHING and returns None."""
    import psycopg

    outbox, tenant, dsn = pg
    row = _intent(outbox, tenant)
    holder = psycopg.connect(dsn)
    holder.execute(
        "SELECT outbox_id FROM execution_outbox WHERE outbox_id = %s FOR UPDATE",
        (row.outbox_id,),
    )
    result: list[object] = []
    started = threading.Event()

    def blocked_claim() -> None:
        started.set()
        result.append(outbox.claim(row.outbox_id, worker_id="late"))

    t = threading.Thread(target=blocked_claim)
    t.start()
    started.wait(timeout=5)
    t.join(timeout=1.0)
    assert t.is_alive(), "claim returned while the row lock was still held"

    holder.execute(
        "UPDATE execution_outbox SET state = %s, worker_id = %s, claimed_at = %s "
        "WHERE outbox_id = %s",
        (OutboxState.DISPATCHING.value, "holder",
         datetime.now(UTC).isoformat(), row.outbox_id),
    )
    holder.commit()
    holder.close()
    t.join(timeout=30)
    assert not t.is_alive()
    assert result == [None]
    assert outbox.get(row.outbox_id).worker_id == "holder"


# ── (d) the worker's backend dies mid-claim ─────────────────────────────────


@pg_dsn
def test_postgres_terminated_backend_releases_the_claim(pg) -> None:
    """A worker takes the row lock and is killed before commit
    (``pg_terminate_backend``). Its transaction rolls back: the row is still
    DISPATCH_PENDING, and a surviving worker claims it normally."""
    import psycopg

    outbox, tenant, dsn = pg
    row = _intent(outbox, tenant)

    victim = psycopg.connect(dsn)
    victim_pid = victim.execute("SELECT pg_backend_pid()").fetchone()[0]
    victim.execute(
        "SELECT outbox_id FROM execution_outbox WHERE outbox_id = %s FOR UPDATE",
        (row.outbox_id,),
    )
    victim.execute(
        "UPDATE execution_outbox SET state = %s, worker_id = %s WHERE outbox_id = %s",
        (OutboxState.DISPATCHING.value, "victim", row.outbox_id),
    )
    # Not committed. Kill the backend from another connection.
    with psycopg.connect(dsn, autocommit=True) as killer:
        assert killer.execute(
            "SELECT pg_terminate_backend(%s)", (victim_pid,)
        ).fetchone()[0] is True

    with pytest.raises(psycopg.OperationalError):
        victim.execute("SELECT 1")
    victim.close()

    survivor = outbox.get(row.outbox_id)
    assert survivor.state is OutboxState.DISPATCH_PENDING
    assert survivor.worker_id is None
    claimed = outbox.claim(row.outbox_id, worker_id="survivor")
    assert claimed is not None and claimed.worker_id == "survivor"


# ── (a) worker dies after claim, before dispatch ────────────────────────────


@pg_dsn
def test_postgres_claim_then_death_is_reconciled_not_redispatched(pg) -> None:
    """A committed claim followed by worker death leaves DISPATCHING with no
    settle. The design does not re-claim: the reconciler settles UNKNOWN,
    the row leaves the pending set, and any later claim raises."""
    outbox, tenant, _ = pg
    row = _intent(outbox, tenant)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    assert outbox.claim(row.outbox_id, worker_id="dead", now=t0) is not None
    # Worker death: nothing else happens on this row.
    assert outbox.get(row.outbox_id).state is OutboxState.DISPATCHING
    assert outbox.pending(tenant) == []

    stale = outbox.reconcile_stale(
        tenant, older_than=timedelta(minutes=5), now=t0 + timedelta(hours=1),
    )
    assert [r.outbox_id for r in stale] == [row.outbox_id]
    after = outbox.get(row.outbox_id)
    assert after.state is OutboxState.UNKNOWN
    assert after.projected_at is None
    with pytest.raises(ValueError):
        outbox.claim(row.outbox_id, worker_id="resurrected")
    # The reconciler is idempotent: a second sweep finds nothing.
    assert outbox.reconcile_stale(
        tenant, older_than=timedelta(minutes=5), now=t0 + timedelta(hours=2),
    ) == []


# ── (b) worker dies after dispatch, before projection ───────────────────────


@pg_dsn
def test_postgres_settled_but_unprojected_row_survives_worker_death(pg) -> None:
    """settle() writes the terminal state and the projection payload in one
    transaction. A worker that dies right after leaves a row the projector
    can find (``unprojected_terminal``) and replay; a projector that dies
    after marking and is retried marks again without re-queueing the row."""
    outbox, tenant, _ = pg
    row = _intent(outbox, tenant)
    outbox.claim(row.outbox_id, worker_id="w")
    payload = '{"outcome":"SUCCEEDED","receipt":"r-1"}'
    settled = outbox.settle(
        row.outbox_id, OutboxState.SUCCEEDED, detail="ok", projection_json=payload,
    )
    assert settled.projection_json == payload
    assert settled.projected_at is None
    # Worker death here. A fresh adapter instance stands in for a new process.
    from remora.enforcement.outbox import PostgresExecutionOutbox

    projector = PostgresExecutionOutbox(os.environ["REMORA_PG_DSN"])
    queue = projector.unprojected_terminal(tenant)
    assert [r.outbox_id for r in queue] == [row.outbox_id]
    assert queue[0].projection_json == payload

    first = projector.mark_projected(row.outbox_id, now=datetime(2026, 1, 1, tzinfo=UTC))
    assert first.projected_at is not None
    # A retried projector marks again; the row stays projected and out of
    # the queue. All three adapters record the latest mark (last write), so
    # the timestamp is when projection was last confirmed, not first.
    second = projector.mark_projected(row.outbox_id, now=datetime(2026, 1, 2, tzinfo=UTC))
    assert second.projected_at is not None
    assert second.state is OutboxState.SUCCEEDED
    assert projector.unprojected_terminal(tenant) == []


@pg_dsn
def test_postgres_projection_is_atomic_with_settlement(pg) -> None:
    """If the settle transaction is torn down before commit, neither the
    terminal state nor the payload lands: the row is still DISPATCHING and
    the stale reconciler owns it. This is the property that lets the
    projector trust projection_json whenever it sees a terminal state."""
    import psycopg

    outbox, tenant, dsn = pg
    row = _intent(outbox, tenant)
    outbox.claim(row.outbox_id, worker_id="w")

    victim = psycopg.connect(dsn)
    pid = victim.execute("SELECT pg_backend_pid()").fetchone()[0]
    victim.execute(
        "UPDATE execution_outbox SET state = %s, projection_json = %s "
        "WHERE outbox_id = %s",
        (OutboxState.SUCCEEDED.value, '{"torn":true}', row.outbox_id),
    )
    with psycopg.connect(dsn, autocommit=True) as killer:
        killer.execute("SELECT pg_terminate_backend(%s)", (pid,))
    victim.close()

    after = outbox.get(row.outbox_id)
    assert after.state is OutboxState.DISPATCHING
    assert after.projection_json is None
    assert outbox.unprojected_terminal(tenant) == []


# ── (f) retry idempotency across processes ──────────────────────────────────


@pg_dsn
def test_postgres_retried_intent_from_a_second_process_is_one_row(pg) -> None:
    """An API replica retrying the same authorization (same attempt) after a
    crash must land on the existing row, from a different adapter instance
    and connection; a genuine re-approval (attempt 2) gets its own row."""
    from remora.enforcement.outbox import PostgresExecutionOutbox

    outbox, tenant, dsn = pg
    first = _intent(outbox, tenant)
    replica = PostgresExecutionOutbox(dsn)
    again = _intent(replica, tenant)
    assert again.outbox_id == first.outbox_id
    assert len(replica.pending(tenant)) == 1
    reapproved = _intent(replica, tenant, attempt_no=2)
    assert reapproved.outbox_id != first.outbox_id
    assert len(outbox.pending(tenant)) == 2
