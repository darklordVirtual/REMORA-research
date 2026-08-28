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
import sqlite3

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
