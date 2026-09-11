# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A transactional outbox for tenant audit events (REM-047, RMR-006).

The review-queue transition commits inside ``transaction_state``. The audit
entry is appended afterwards, through the tenant chain, which is atomic in
itself. Two atomic writes are not one atomic write: a crash between them leaves
a state transition with no audit event, or an approval with no audit post, and
a verifier holding the chain cannot tell that from a chain that was never
written to.

The fix is the mechanism the dispatch half already uses. The audit event is
enqueued on the SAME connection as the state transition, so it commits or rolls
back with it. A separate drain then projects enqueued events into the chain and
marks them projected. A crash between commit and projection leaves an enqueued
row, and the next drain finds it.

Two properties make the drain safe to run at any time, from any process:

idempotent
    projection goes through ``append_once`` under a deterministic key, so
    replaying a drain cannot append the same event twice.

resumable
    a row is marked projected only after ``append_once`` returns, so a crash
    mid-drain replays the row rather than losing it. The cost of a crash is a
    duplicate attempt, which the key absorbs; the cost of the reverse order
    would be a lost audit event, which nothing absorbs.

The table is created on demand, like the other execution-state tables, so a
deployment that has not run a migration still fails closed rather than silently
skipping audit.

Order is part of the contract. ``pending`` ordered by SQLite's ``rowid`` and by
nothing at all on Postgres, so the order events reached the chain was undefined
on the backend production actually runs. Each row now carries a monotonic
``seq``, assigned inside the enqueuing transaction, and both backends order by
``(seq, key)``. Two transactions that commit concurrently can read the same
maximum and take the same ``seq``; the key breaks that tie, so the order is
total and identical on every reader, which is what a verifier needs. It is not
a global commit order, and does not claim to be one.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

#: Deliberately narrow. This is a queue with two operations, not a store.
_CREATE_SQLITE = (
    "CREATE TABLE IF NOT EXISTS audit_outbox ("
    "  key TEXT PRIMARY KEY,"
    "  tenant_id TEXT NOT NULL,"
    "  payload_json TEXT NOT NULL,"
    "  projected INTEGER NOT NULL DEFAULT 0,"
    "  seq INTEGER NOT NULL DEFAULT 0"
    ")"
)

_CREATE_POSTGRES = (
    "CREATE TABLE IF NOT EXISTS audit_outbox ("
    "  key TEXT PRIMARY KEY,"
    "  tenant_id TEXT NOT NULL,"
    "  payload_json TEXT NOT NULL,"
    "  projected BOOLEAN NOT NULL DEFAULT FALSE,"
    "  seq BIGINT NOT NULL DEFAULT 0"
    ")"
)

#: Same schema-on-demand rule as the CREATE above: a table written before the
#: column existed is migrated where it is found, not by a separate step an
#: operator has to remember. Postgres has ``IF NOT EXISTS``; SQLite does not,
#: so its presence is read from the catalogue first.
_ADD_SEQ_POSTGRES = "ALTER TABLE audit_outbox ADD COLUMN IF NOT EXISTS seq BIGINT NOT NULL DEFAULT 0"
_ADD_SEQ_SQLITE = "ALTER TABLE audit_outbox ADD COLUMN seq INTEGER NOT NULL DEFAULT 0"


class ChainPort(Protocol):
    """The half of the tenant chain a projector needs."""

    def append_once(
        self, tenant_id: str, idempotency_key: str, payload: dict[str, Any]
    ) -> Any: ...


def _placeholder(conn: Any) -> str:
    """Postgres uses %s, SQLite and D1 use ?."""

    return "%s" if type(conn).__module__.startswith("psycopg") else "?"


def _in_ambient_transaction(conn: Any) -> bool:
    """Whether someone else already has a transaction open on this connection.

    Best effort by design: an adapter this does not recognise reports False and
    the caller keeps the documented precondition. Both drivers the deployment
    actually uses are recognised.
    """

    in_transaction = getattr(conn, "in_transaction", None)
    if isinstance(in_transaction, bool):  # sqlite3
        return in_transaction
    info = getattr(conn, "info", None)
    status = getattr(info, "transaction_status", None)
    if status is None:
        return False
    # psycopg's TransactionStatus.IDLE is 0; anything else is an open one.
    return getattr(status, "value", status) != 0


def ensure_table(conn: Any) -> None:
    """Create the table, and add ``seq`` to one written before it existed.

    Runs on the caller's transaction and deliberately does not commit: a
    migration that committed here would commit the state transition the caller
    had not finished making. A rolled-back caller simply redoes it next time.
    """

    marker = _placeholder(conn)
    conn.execute(_CREATE_POSTGRES if marker == "%s" else _CREATE_SQLITE)
    if marker == "%s":
        conn.execute(_ADD_SEQ_POSTGRES)
        return
    columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_outbox)")}
    if "seq" not in columns:
        conn.execute(_ADD_SEQ_SQLITE)
        # rowid is the arrival order those rows were written under, which is
        # exactly what the old ORDER BY used. Preserving it keeps a migrated
        # queue draining in the order it was enqueued.
        conn.execute("UPDATE audit_outbox SET seq = rowid")


def _next_seq(conn: Any) -> int:
    row = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM audit_outbox").fetchone()
    return int(row[0]) if row else 1


def enqueue(conn: Any, *, tenant: str, key: str, payload: dict[str, Any]) -> None:
    """Enqueue one audit event on the caller's open transaction.

    ``key`` must be deterministic for the event it describes: it is both the
    de-duplication key for a replayed drain and the idempotency key the chain
    append is claimed under. A random key would make a retried transaction look
    like a second event.
    """

    if not key:
        raise ValueError("audit outbox key must be non-empty: it is the idempotency key")
    ensure_table(conn)
    marker = _placeholder(conn)
    conflict = (
        "ON CONFLICT (key) DO NOTHING"
        if marker == "%s"
        else "ON CONFLICT(key) DO NOTHING"
    )
    conn.execute(
        f"INSERT INTO audit_outbox (key, tenant_id, payload_json, projected, seq) "
        f"VALUES ({marker}, {marker}, {marker}, "
        f"{'FALSE' if marker == '%s' else '0'}, {marker}) {conflict}",
        (key, tenant, json.dumps(payload, sort_keys=True), _next_seq(conn)),
    )


def pending(conn: Any, *, tenant: str | None = None) -> list[tuple[str, str, dict[str, Any]]]:
    """Enqueued events that have not been projected, oldest first."""

    ensure_table(conn)
    marker = _placeholder(conn)
    false_literal = "FALSE" if marker == "%s" else "0"
    # Identical ordering on both backends: seq is the arrival order, and key
    # breaks the tie two concurrent enqueues can produce.
    if tenant is None:
        rows = conn.execute(
            f"SELECT key, tenant_id, payload_json FROM audit_outbox "
            f"WHERE projected = {false_literal} ORDER BY seq, key"
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT key, tenant_id, payload_json FROM audit_outbox "
            f"WHERE projected = {false_literal} AND tenant_id = {marker} "
            f"ORDER BY seq, key",
            (tenant,),
        ).fetchall()
    return [(row[0], row[1], json.loads(row[2])) for row in rows]


def drain(conn: Any, chain: ChainPort, *, tenant: str | None = None) -> int:
    """Project enqueued events into the chain. Returns how many were projected.

    Safe to call from anywhere, at any time, including concurrently: the append
    is claimed under the row's key, so a second caller that wins the race
    projects nothing and the row is still marked. Marking after the append is
    what makes a crash replay rather than lose.

    Precondition, enforced rather than documented: the connection must not have
    a transaction open. This function commits, and committing someone else's
    half-written transaction would durably record a state change its author had
    not finished making — the inverse of the defect the outbox exists to close.
    Give the drain its own connection.
    """

    if _in_ambient_transaction(conn):
        raise RuntimeError(
            "drain() commits and was given a connection inside an ambient "
            "transaction; it would commit writes its caller had not finished. "
            "Drain on a connection of its own."
        )
    marker = _placeholder(conn)
    projected = 0
    for key, row_tenant, payload in pending(conn, tenant=tenant):
        chain.append_once(row_tenant, key, payload)
        conn.execute(
            f"UPDATE audit_outbox SET projected = "
            f"{'TRUE' if marker == '%s' else '1'} WHERE key = {marker}",
            (key,),
        )
        projected += 1
    if projected:
        conn.commit()
    return projected


__all__ = ["ChainPort", "drain", "encode_key", "enqueue", "ensure_table", "pending"]


def encode_key(*parts: str) -> str:
    """A deterministic key from the parts that identify the event.

    Joined rather than hashed so an operator reading the table can see which
    event a stuck row belongs to without another lookup.
    """

    return "|".join(part.replace("|", "_") for part in parts if part)
