# SPDX-License-Identifier: BUSL-1.1
"""RMR-SEC-0023: the audit-outbox drain projects every pending row on SQLite.

drain() marked each row with an UPDATE on its own connection and committed
only after the loop. On SQLite that UPDATE holds the database's write lock,
and SQLiteTenantChain.append_once opens BEGIN IMMEDIATE on a second connection
to the same file, so from the second pending row on the append waited out its
30 s busy timeout and failed. The API's sweep swallowed the error and returned
0, approval and revocation events never reached the chain, and /audit/verify
still said valid. The wiring tests replaced the chain with the in-memory one,
which takes no file lock, so they could not see it.

These use a real SQLite file for both the outbox and the chain.
"""
from __future__ import annotations

import sqlite3
import time

from remora.governance import audit_outbox
from remora.governance.tenant_chain import SQLiteTenantChain


def _setup(tmp_path, n: int):
    path = str(tmp_path / "chain.db")
    chain = SQLiteTenantChain(path)
    writer = sqlite3.connect(path, timeout=30)
    audit_outbox.ensure_table(writer)
    for i in range(n):
        audit_outbox.enqueue(writer, tenant="acme", key=f"evt|{i}", payload={"event": "approved", "i": i})
    writer.commit()
    writer.close()
    drain_conn = sqlite3.connect(path, timeout=30)
    return chain, drain_conn


def test_three_pending_events_drain_promptly_into_a_sqlite_chain(tmp_path) -> None:
    chain, conn = _setup(tmp_path, 3)
    started = time.monotonic()
    projected = audit_outbox.drain(conn, chain)
    elapsed = time.monotonic() - started
    assert projected == 3
    assert elapsed < 5.0, f"drain took {elapsed:.1f}s; the write lock was held across appends"
    assert [entry.payload["i"] for entry in chain.entries("acme")] == [0, 1, 2]
    assert audit_outbox.pending(conn) == []
    assert chain.verify("acme")[0] is True


def test_a_second_drain_projects_nothing_twice(tmp_path) -> None:
    chain, conn = _setup(tmp_path, 2)
    assert audit_outbox.drain(conn, chain) == 2
    assert audit_outbox.drain(conn, chain) == 0
    assert len(chain.entries("acme")) == 2


def test_other_writers_are_not_locked_out_while_draining(tmp_path) -> None:
    """The review saw NonceStoreUnavailable from other ledgers on the file."""
    chain, conn = _setup(tmp_path, 3)
    audit_outbox.drain(conn, chain)
    other = sqlite3.connect(str(tmp_path / "chain.db"), timeout=1)
    other.execute("CREATE TABLE IF NOT EXISTS probe (x INTEGER)")
    other.execute("INSERT INTO probe VALUES (1)")
    other.commit()
