# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REM-047 / RMR-006: a state transition and its audit event survive together.

The review-queue transition commits inside its own transaction and the audit
entry is appended afterwards. Both writes are atomic; the pair is not. A crash
between them leaves a transition with no audit event, and a verifier holding the
chain cannot distinguish that from a chain nothing was ever written to.

These tests inject the crash at each point in the window and require that
recovery converges on exactly one truth: either the transition and its audit
event both exist, or neither does. Never one without the other, and never the
same event twice.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid

import pytest

from remora.governance.audit_outbox import drain, encode_key, enqueue, pending
from remora.governance.tenant_chain import TenantAuditChain

TENANT = "acme"


@pytest.fixture
def conn(tmp_path):
    connection = sqlite3.connect(tmp_path / "state.db")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS review_state (item_id TEXT PRIMARY KEY, state TEXT)"
    )
    connection.commit()
    yield connection
    connection.close()


def event(item_id: str, state: str) -> dict:
    return {"event": "review_transition", "item_id": item_id, "state": state}


def transition(connection, item_id: str, state: str, *, crash_before_commit=False):
    """One business transition with its audit event on the same transaction."""

    connection.execute(
        "INSERT OR REPLACE INTO review_state (item_id, state) VALUES (?, ?)",
        (item_id, state),
    )
    enqueue(
        connection,
        tenant=TENANT,
        key=encode_key(TENANT, item_id, state),
        payload=event(item_id, state),
    )
    if crash_before_commit:
        raise RuntimeError("process died before commit")
    connection.commit()


def states(connection) -> dict[str, str]:
    return dict(connection.execute("SELECT item_id, state FROM review_state").fetchall())


def chain_events(chain: TenantAuditChain) -> list[dict]:
    return [
        entry.payload if isinstance(entry.payload, dict) else json.loads(entry.payload)
        for entry in chain.entries(TENANT)
    ]


def test_a_crash_before_commit_leaves_neither(conn):
    chain = TenantAuditChain()
    with pytest.raises(RuntimeError):
        transition(conn, "item-1", "APPROVED", crash_before_commit=True)
    conn.rollback()

    assert states(conn) == {}
    assert pending(conn) == []
    assert drain(conn, chain) == 0
    assert chain_events(chain) == []


def test_a_crash_after_commit_and_before_projection_recovers(conn):
    """The window REM-047 is about: the transition is durable, the audit is not yet."""

    chain = TenantAuditChain()
    transition(conn, "item-1", "APPROVED")

    # The process dies here. The transition is committed; nothing has reached
    # the chain.
    assert states(conn) == {"item-1": "APPROVED"}
    assert chain_events(chain) == []
    assert len(pending(conn)) == 1

    # Recovery.
    assert drain(conn, chain) == 1
    assert [e["item_id"] for e in chain_events(chain)] == ["item-1"]
    assert pending(conn) == []


def test_replaying_the_drain_does_not_duplicate_the_event(conn):
    chain = TenantAuditChain()
    transition(conn, "item-1", "APPROVED")
    drain(conn, chain)
    assert drain(conn, chain) == 0
    assert len(chain_events(chain)) == 1


def test_a_crash_during_the_drain_replays_rather_than_losing(conn):
    """Marking after the append is what makes a mid-drain crash survivable."""

    chain = TenantAuditChain()
    transition(conn, "item-1", "APPROVED")

    class DyingChain:
        def append_once(self, tenant_id, idempotency_key, payload):
            chain.append_once(tenant_id, idempotency_key, payload)
            raise RuntimeError("process died after the append, before the mark")

    with pytest.raises(RuntimeError):
        drain(conn, DyingChain())
    conn.rollback()

    # The row is still pending, and replaying it appends nothing new.
    assert len(pending(conn)) == 1
    assert drain(conn, chain) == 1
    assert len(chain_events(chain)) == 1


def test_a_second_process_draining_concurrently_appends_once(conn, tmp_path):
    chain = TenantAuditChain()
    transition(conn, "item-1", "APPROVED")

    other = sqlite3.connect(tmp_path / "state.db")
    try:
        assert drain(other, chain) == 1
        # The first process drains the same row it already saw as pending.
        drain(conn, chain)
        assert len(chain_events(chain)) == 1
    finally:
        other.close()


def test_many_transitions_recover_in_order(conn):
    chain = TenantAuditChain()
    for index in range(5):
        transition(conn, f"item-{index}", "APPROVED")

    assert chain_events(chain) == []
    assert drain(conn, chain) == 5
    assert [e["item_id"] for e in chain_events(chain)] == [f"item-{i}" for i in range(5)]


def test_the_key_must_identify_the_event():
    connection = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match="idempotency key"):
            enqueue(connection, tenant=TENANT, key="", payload={"event": "x"})
    finally:
        connection.close()


def test_the_chain_verifies_after_recovery(conn):
    chain = TenantAuditChain()
    for index in range(3):
        transition(conn, f"item-{index}", "APPROVED")
    drain(conn, chain)
    intact, problems = chain.verify(TENANT)
    assert intact is True, problems


# ── Drain order is a property, not an accident ────────────────────────────
#
# ``pending`` ordered by ``rowid`` on SQLite and by nothing at all on
# Postgres, so the order events reached the chain was undefined on the only
# backend production uses. A monotonic sequence column makes the order the
# same on both.

def test_pending_is_ordered_by_arrival_not_by_key(conn):
    """Keys deliberately sort against arrival order, so a key sort would show."""

    chain = TenantAuditChain()
    for item_id in ("zulu", "mike", "alpha"):
        transition(conn, item_id, "APPROVED")

    assert [row[2]["item_id"] for row in pending(conn)] == ["zulu", "mike", "alpha"]
    drain(conn, chain)
    assert [e["item_id"] for e in chain_events(chain)] == ["zulu", "mike", "alpha"]


def test_the_sequence_is_monotonic_and_survives_projection(conn):
    for index in range(3):
        transition(conn, f"item-{index}", "APPROVED")
    seqs = [row[0] for row in conn.execute(
        "SELECT seq FROM audit_outbox ORDER BY seq").fetchall()]
    assert seqs == sorted(seqs) and len(set(seqs)) == 3


def test_a_table_written_before_the_sequence_existed_is_migrated(tmp_path):
    """The module creates schema on demand; the added column follows the same rule."""

    legacy = sqlite3.connect(tmp_path / "legacy.db")
    try:
        legacy.execute(
            "CREATE TABLE audit_outbox ("
            "  key TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,"
            "  payload_json TEXT NOT NULL, projected INTEGER NOT NULL DEFAULT 0)"
        )
        legacy.execute(
            "INSERT INTO audit_outbox (key, tenant_id, payload_json) VALUES (?, ?, ?)",
            ("old-key", TENANT, json.dumps(event("item-old", "APPROVED"))),
        )
        legacy.commit()

        enqueue(legacy, tenant=TENANT, key="new-key", payload=event("item-new", "APPROVED"))
        legacy.commit()
        assert [row[0] for row in pending(legacy)] == ["old-key", "new-key"]

        chain = TenantAuditChain()
        assert drain(legacy, chain) == 2
        assert [e["item_id"] for e in chain_events(chain)] == ["item-old", "item-new"]
    finally:
        legacy.close()


def test_drain_refuses_a_connection_inside_an_open_transaction(conn):
    """``drain`` commits unconditionally, so it must never be handed someone
    else's open transaction: it would commit writes the caller had not
    finished making."""

    chain = TenantAuditChain()
    transition(conn, "item-1", "APPROVED")
    conn.execute(
        "INSERT OR REPLACE INTO review_state (item_id, state) VALUES (?, ?)",
        ("item-2", "PENDING"),
    )
    assert conn.in_transaction
    with pytest.raises(RuntimeError, match="ambient transaction"):
        drain(conn, chain)
    conn.rollback()
    assert chain_events(chain) == []


# ── The same order on the backend production actually runs ────────────────
#
# Postgres has no rowid, so the old query had no ORDER BY at all there and
# drain order was whatever the planner returned. Skipped without a server;
# CI runs a Postgres job.

pg_dsn = pytest.mark.skipif(
    not os.environ.get("REMORA_PG_DSN", "").strip(),
    reason="REMORA_PG_DSN not set (ordering on Postgres needs a real Postgres)",
)


@pg_dsn
def test_postgres_drains_in_arrival_order() -> None:
    import psycopg

    tenant = f"order-{uuid.uuid4().hex[:8]}"
    chain = TenantAuditChain()
    with psycopg.connect(os.environ["REMORA_PG_DSN"]) as writer:
        for item_id in ("zulu", "mike", "alpha"):
            enqueue(writer, tenant=tenant, key=encode_key(tenant, item_id),
                    payload=event(item_id, "APPROVED"))
        writer.commit()

    with psycopg.connect(os.environ["REMORA_PG_DSN"]) as reader:
        assert [row[2]["item_id"] for row in pending(reader, tenant=tenant)] == [
            "zulu", "mike", "alpha"]

    # A connection of its own: drain commits, so it may not be handed one
    # with a transaction already open.
    with psycopg.connect(os.environ["REMORA_PG_DSN"]) as drainer:
        assert drain(drainer, chain, tenant=tenant) == 3

    projected = [
        entry.payload if isinstance(entry.payload, dict) else json.loads(entry.payload)
        for entry in chain.entries(tenant)
    ]
    assert [e["item_id"] for e in projected] == ["zulu", "mike", "alpha"]
