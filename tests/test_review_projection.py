# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Phase 8 slice 1: normalized review-items projection, dual-written.

The projection is written in the SAME transaction as global_state (so it can
never disagree with what committed), indexed for tenant/status/proposal
queries, and rolls back with the transaction. Reads still come from
global_state — authorization semantics untouched.
"""
from __future__ import annotations

import contextvars
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.governance.review_queue import ReviewQueue
from remora.persistence.execution_state import transaction_state
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction

_ENGINE = RemoraDecisionEngine()


def _enqueue(q: ReviewQueue, proposal_id: str) -> None:
    obs = PolicyObservation(
        question=f"projection {proposal_id}",
        proposed_tool_name="update_work_order",
        proposal_id=proposal_id,
    )
    q.enqueue(obs, DecisionAction.VERIFY)


def _tx(tenant: str, db: str, queue: ReviewQueue, item_tenant: dict):
    var: contextvars.ContextVar = contextvars.ContextVar("tx", default=None)
    return transaction_state(
        tenant, queue=queue, item_tenant=item_tenant,
        active_tx_connection=var, dsn="", db_path=db,
    )


def test_projection_written_in_same_transaction(tmp_path: Path) -> None:
    db = str(tmp_path / "state.db")
    q = ReviewQueue(engine=_ENGINE)
    with _tx("t1", db, q, {}) as queue:
        _enqueue(queue, "p-1")
        _enqueue(queue, "p-2")

    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT tenant_id, status, proposal_id FROM review_items_projection "
            "ORDER BY proposal_id"
        ).fetchall()
    assert [r[0] for r in rows] == ["t1", "t1"]
    assert {r[2] for r in rows} == {"p-1", "p-2"}
    assert all(r[1] for r in rows)  # every row carries a status


def test_projection_rolls_back_with_the_transaction(tmp_path: Path) -> None:
    db = str(tmp_path / "state.db")
    q = ReviewQueue(engine=_ENGINE)
    with _tx("t1", db, q, {}) as queue:
        _enqueue(queue, "p-keep")

    try:
        with _tx("t1", db, ReviewQueue(engine=_ENGINE), {}) as queue:
            _enqueue(queue, "p-aborted")
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    with sqlite3.connect(db) as conn:
        proposals = {r[0] for r in conn.execute(
            "SELECT proposal_id FROM review_items_projection"
        ).fetchall()}
    assert proposals == {"p-keep"}, "aborted transaction must not leak rows"


def test_projection_is_tenant_scoped_and_indexed(tmp_path: Path) -> None:
    db = str(tmp_path / "state.db")
    for tenant, pid in (("t-a", "p-a"), ("t-b", "p-b")):
        q = ReviewQueue(engine=_ENGINE)
        with _tx(tenant, db, q, {}) as queue:
            _enqueue(queue, pid)

    with sqlite3.connect(db) as conn:
        a_rows = conn.execute(
            "SELECT proposal_id FROM review_items_projection WHERE tenant_id = ?",
            ("t-a",),
        ).fetchall()
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()}
    assert [r[0] for r in a_rows] == ["p-a"]
    assert {"idx_review_proj_tenant", "idx_review_proj_status",
            "idx_review_proj_proposal", "idx_review_proj_updated"} <= indexes


def test_reads_still_come_from_global_state(tmp_path: Path) -> None:
    """Deleting the projection must not change what the queue loads — the
    projection is derived, never load-bearing."""
    db = str(tmp_path / "state.db")
    q = ReviewQueue(engine=_ENGINE)
    with _tx("t1", db, q, {}) as queue:
        _enqueue(queue, "p-1")

    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM review_items_projection")
        conn.commit()

    reloaded = ReviewQueue(engine=_ENGINE)
    with _tx("t1", db, reloaded, {}) as queue:
        assert len(queue._items) == 1
