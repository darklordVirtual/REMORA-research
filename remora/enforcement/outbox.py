# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Crash-consistent execution outbox (FT-02 / issue #82, slice 1).

The outbox is the durable record of **dispatch intent**. Today's execution
path commits authorization, burns the PDP grant, dispatches the tool and
records the outcome across separate transactions, leaving three crash
windows in which a side effect may have happened with nothing durable
saying so. The outbox closes that by making one row the source of truth
for "a dispatch was authorized and what became of it".

State machine (mirrors ``schemas/execution_lifecycle_v1.yaml``; the state
NAMES are the lifecycle model's, asserted by test)::

    DISPATCH_PENDING --claim--> DISPATCHING --+--> SUCCEEDED
                                              +--> FAILED
                                              +--> REFUSED
                                              +--> UNKNOWN

All four right-hand states are terminal and **none auto-retries**.
``UNKNOWN`` is first-class: it is what reconciliation produces when it
cannot prove ``SUCCEEDED`` vs ``FAILED``, and re-running a call that may
already have taken effect is the one thing this component must never do.
Resolving an ``UNKNOWN`` is a manual operator decision that produces a
NEW record (maintainer contract decision 2026-08-05) — it never rewrites
the terminal state, because the uncertainty genuinely happened.

Three adapters, one contract: :class:`ExecutionOutbox` (in-process
reference, for tests and development), :class:`SQLiteExecutionOutbox`
(durable single-node) and :class:`PostgresExecutionOutbox` (durable
multi-worker, contract-tested against a real service in CI).

**Realization status:** this module is the store, its state machine, and
its transactional enlistment path (``record_intent_enlisted`` on both
durable adapters, which makes "the row is written in the same transaction
that authorizes the call" a verified property rather than an aspiration —
a rollback of the authorization removes the row). Nothing in
``servers/execution_api.py`` writes to it yet: that wiring and the
dispatch worker/reconciler are the remaining FT-02 slices. The fasttrack
register remains the status authority; no crash-consistency property may
be claimed for the live path until the wiring lands.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum

__all__ = [
    "ExecutionOutbox",
    "OutboxRow",
    "OutboxState",
    "PostgresExecutionOutbox",
    "SQLiteExecutionOutbox",
    "idempotency_key",
]

POSTGRES_DDL = """
-- FT-02: crash-consistent dispatch intent (multi-worker adapter).
CREATE TABLE IF NOT EXISTS execution_outbox (
    outbox_id       TEXT PRIMARY KEY,
    proposal_id     TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    item_id         TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    tool_call_hash  TEXT NOT NULL,
    grant_jti       TEXT NOT NULL,
    state           TEXT NOT NULL,
    attempt_no      INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    worker_id       TEXT,
    claimed_at      TEXT,
    settled_at      TEXT,
    detail          TEXT,
    UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS execution_outbox_pending_idx
    ON execution_outbox (tenant_id, state, created_at);
"""

_COLUMNS = (
    "outbox_id", "proposal_id", "tenant_id", "item_id", "idempotency_key",
    "tool_name", "tool_call_hash", "grant_jti", "state", "attempt_no",
    "created_at", "worker_id", "claimed_at", "settled_at", "detail",
)


class OutboxState(str, Enum):
    """Dispatch-intent states. Values are lifecycle-model state names."""

    DISPATCH_PENDING = "DISPATCH_PENDING"
    DISPATCHING = "DISPATCHING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUSED = "REFUSED"
    UNKNOWN = "UNKNOWN"


TERMINAL_STATES = frozenset({
    OutboxState.SUCCEEDED,
    OutboxState.FAILED,
    OutboxState.REFUSED,
    OutboxState.UNKNOWN,
})


def idempotency_key(proposal_id: str, tool_call_hash: str, attempt_no: int) -> str:
    """SHA-256 over (proposal_id, tool_call_hash, attempt_no).

    ``attempt_no`` is folded in deliberately: a legitimately re-approved
    identical call after ``APPROVAL_INVALIDATED`` is a NEW dispatch
    intent and must not collide with the stale row from the previous
    approval cycle. Fields are length-prefixed so no concatenation of
    different components can produce the same preimage.
    """
    hasher = hashlib.sha256()
    for part in (proposal_id, tool_call_hash, str(attempt_no)):
        hasher.update(f"{len(part)}:{part}".encode("utf-8"))
    return hasher.hexdigest()


@dataclass(frozen=True)
class OutboxRow:
    """One dispatch intent and everything known about its fate."""

    outbox_id: str
    proposal_id: str
    tenant_id: str
    item_id: str
    idempotency_key: str
    tool_name: str
    tool_call_hash: str
    grant_jti: str
    state: OutboxState
    attempt_no: int
    created_at: datetime
    worker_id: str | None = None
    claimed_at: datetime | None = None
    settled_at: datetime | None = None
    detail: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _check_claimable(row: OutboxRow) -> None:
    if row.is_terminal:
        raise ValueError(
            f"outbox row {row.outbox_id} is terminal ({row.state.value}); "
            "a settled dispatch is never re-claimed"
        )


def _check_settleable(row: OutboxRow, state: OutboxState) -> None:
    if row.is_terminal:
        raise ValueError(
            f"outbox row {row.outbox_id} is already terminal "
            f"({row.state.value}); terminal states are absorbing"
        )
    if row.state is not OutboxState.DISPATCHING:
        raise ValueError(
            f"outbox row {row.outbox_id} is {row.state.value}; only a claimed "
            "(DISPATCHING) row can be settled"
        )
    if state not in TERMINAL_STATES:
        raise ValueError(f"{state.value} is not a terminal outbox state")


class ExecutionOutbox:
    """In-process reference implementation of the outbox contract.

    Not durable: a restart loses every row, and with it the record that a
    dispatch was authorized. Development and tests only — the same
    honesty the rest of the execution layer applies to its in-process
    stores.
    """

    def __init__(self) -> None:
        self._rows: dict[str, OutboxRow] = {}
        self._by_key: dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()

    # -- writes ------------------------------------------------------------

    def record_intent(
        self,
        *,
        proposal_id: str,
        tenant_id: str,
        item_id: str,
        tool_name: str,
        tool_call_hash: str,
        grant_jti: str,
        attempt_no: int = 1,
        now: datetime | None = None,
    ) -> OutboxRow:
        """Insert a dispatch intent, or return the existing one.

        Idempotent by ``(tenant_id, idempotency_key)``: a retried
        authorization can never create a second dispatch intent for the
        same attempt.
        """
        key = idempotency_key(proposal_id, tool_call_hash, attempt_no)
        with self._lock:
            existing = self._by_key.get((tenant_id, key))
            if existing is not None:
                return self._rows[existing]
            row = OutboxRow(
                outbox_id=str(uuid.uuid4()),
                proposal_id=proposal_id,
                tenant_id=tenant_id,
                item_id=item_id,
                idempotency_key=key,
                tool_name=tool_name,
                tool_call_hash=tool_call_hash,
                grant_jti=grant_jti,
                state=OutboxState.DISPATCH_PENDING,
                attempt_no=attempt_no,
                created_at=_now(now),
            )
            self._rows[row.outbox_id] = row
            self._by_key[(tenant_id, key)] = row.outbox_id
            return row

    def record_intent_enlisted(
        self,
        connection: "sqlite3.Connection",
        *,
        proposal_id: str,
        tenant_id: str,
        item_id: str,
        tool_name: str,
        tool_call_hash: str,
        grant_jti: str,
        attempt_no: int = 1,
        now: datetime | None = None,
    ) -> OutboxRow:
        """Not available in-process: there is no transaction to join.

        Refusing is the honest answer. Silently ignoring *connection* would
        let a caller believe the row is atomic with their authorization
        write when it is not — precisely the false guarantee FT-02 exists
        to remove.
        """
        raise NotImplementedError(
            "the in-process outbox cannot enlist in a database transaction; "
            "use SQLiteExecutionOutbox (or configure REMORA_CHAIN_DB)"
        )

    def claim(
        self, outbox_id: str, *, worker_id: str, now: datetime | None = None
    ) -> OutboxRow | None:
        """Claim a pending row for dispatch; ``None`` if another worker won.

        A lost race is normal concurrency and returns ``None``. Claiming a
        SETTLED row is a caller bug and raises — the two must never be
        confused, or a retried dispatch could look like a lost race.
        """
        with self._lock:
            row = self._require(outbox_id)
            _check_claimable(row)
            if row.state is not OutboxState.DISPATCH_PENDING:
                return None
            claimed = replace(
                row,
                state=OutboxState.DISPATCHING,
                worker_id=worker_id,
                claimed_at=_now(now),
            )
            self._rows[outbox_id] = claimed
            return claimed

    def settle(
        self,
        outbox_id: str,
        state: OutboxState,
        *,
        detail: str | None = None,
        now: datetime | None = None,
    ) -> OutboxRow:
        """Drive a claimed row to a terminal state. Terminals are absorbing."""
        with self._lock:
            row = self._require(outbox_id)
            _check_settleable(row, state)
            settled = replace(
                row, state=state, detail=detail, settled_at=_now(now)
            )
            self._rows[outbox_id] = settled
            return settled

    def reconcile_stale(
        self,
        tenant_id: str,
        *,
        older_than: timedelta,
        now: datetime | None = None,
    ) -> list[OutboxRow]:
        """Settle stale ``DISPATCHING`` rows as ``UNKNOWN``.

        A row claimed longer ago than *older_than* has an undeterminable
        side effect: the worker may have invoked the tool before dying.
        The honest outcome is ``UNKNOWN`` — never a retry, and never a
        return to the pending set.
        """
        moment = _now(now)
        cutoff = moment - older_than
        out: list[OutboxRow] = []
        with self._lock:
            for row in list(self._rows.values()):
                if row.tenant_id != tenant_id:
                    continue
                if row.state is not OutboxState.DISPATCHING:
                    continue
                if row.claimed_at is not None and row.claimed_at > cutoff:
                    continue
                out.append(self.settle(
                    row.outbox_id, OutboxState.UNKNOWN,
                    detail="reconciler: dispatch outcome undeterminable",
                    now=moment,
                ))
        return out

    # -- reads -------------------------------------------------------------

    def get(self, outbox_id: str) -> OutboxRow:
        with self._lock:
            return self._require(outbox_id)

    def pending(self, tenant_id: str) -> list[OutboxRow]:
        with self._lock:
            return sorted(
                (r for r in self._rows.values()
                 if r.tenant_id == tenant_id
                 and r.state is OutboxState.DISPATCH_PENDING),
                key=lambda r: r.created_at,
            )

    def _require(self, outbox_id: str) -> OutboxRow:
        row = self._rows.get(outbox_id)
        if row is None:
            raise KeyError(f"unknown outbox row: {outbox_id}")
        return row


_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS execution_outbox (
    outbox_id       TEXT PRIMARY KEY,
    proposal_id     TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    item_id         TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    tool_call_hash  TEXT NOT NULL,
    grant_jti       TEXT NOT NULL,
    state           TEXT NOT NULL,
    attempt_no      INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    worker_id       TEXT,
    claimed_at      TEXT,
    settled_at      TEXT,
    detail          TEXT,
    UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS execution_outbox_pending_idx
    ON execution_outbox (tenant_id, state, created_at);
"""


class SQLiteExecutionOutbox(ExecutionOutbox):
    """Durable single-node outbox. Same contract, survives restart.

    Atomicity comes from ``BEGIN IMMEDIATE``: the write lock covers the
    read-then-write of every state transition, so two workers cannot both
    claim the same row and a retried authorization cannot insert a second
    intent (the ``UNIQUE (tenant_id, idempotency_key)`` constraint is the
    second line of defense).

    Multi-worker deployments need the Postgres adapter (next slice); this
    one is single-node by construction.
    """

    def __init__(self, db_path: str) -> None:  # noqa: D107 - see class doc
        self._db_path = db_path
        self._local = threading.local()
        self._conn().executescript(_SQLITE_DDL)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=30, isolation_level=None)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    @staticmethod
    def _row(record: sqlite3.Row) -> OutboxRow:
        def _dt(value: str | None) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        return OutboxRow(
            outbox_id=record["outbox_id"],
            proposal_id=record["proposal_id"],
            tenant_id=record["tenant_id"],
            item_id=record["item_id"],
            idempotency_key=record["idempotency_key"],
            tool_name=record["tool_name"],
            tool_call_hash=record["tool_call_hash"],
            grant_jti=record["grant_jti"],
            state=OutboxState(record["state"]),
            attempt_no=int(record["attempt_no"]),
            created_at=_dt(record["created_at"]),  # type: ignore[arg-type]
            worker_id=record["worker_id"],
            claimed_at=_dt(record["claimed_at"]),
            settled_at=_dt(record["settled_at"]),
            detail=record["detail"],
        )

    def record_intent(
        self,
        *,
        proposal_id: str,
        tenant_id: str,
        item_id: str,
        tool_name: str,
        tool_call_hash: str,
        grant_jti: str,
        attempt_no: int = 1,
        now: datetime | None = None,
    ) -> OutboxRow:
        key = idempotency_key(proposal_id, tool_call_hash, attempt_no)
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            found = conn.execute(
                "SELECT * FROM execution_outbox "
                "WHERE tenant_id = ? AND idempotency_key = ?",
                (tenant_id, key),
            ).fetchone()
            if found is not None:
                conn.execute("COMMIT")
                return self._row(found)
            outbox_id = str(uuid.uuid4())
            created = _now(now)
            conn.execute(
                "INSERT INTO execution_outbox (outbox_id, proposal_id, "
                "tenant_id, item_id, idempotency_key, tool_name, "
                "tool_call_hash, grant_jti, state, attempt_no, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (outbox_id, proposal_id, tenant_id, item_id, key, tool_name,
                 tool_call_hash, grant_jti,
                 OutboxState.DISPATCH_PENDING.value, attempt_no,
                 created.isoformat()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return self.get(outbox_id)

    def claim(
        self, outbox_id: str, *, worker_id: str, now: datetime | None = None
    ) -> OutboxRow | None:
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._require_conn(conn, outbox_id)
            _check_claimable(row)
            if row.state is not OutboxState.DISPATCH_PENDING:
                conn.execute("COMMIT")
                return None
            conn.execute(
                "UPDATE execution_outbox SET state = ?, worker_id = ?, "
                "claimed_at = ? WHERE outbox_id = ?",
                (OutboxState.DISPATCHING.value, worker_id,
                 _now(now).isoformat(), outbox_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return self.get(outbox_id)

    def settle(
        self,
        outbox_id: str,
        state: OutboxState,
        *,
        detail: str | None = None,
        now: datetime | None = None,
    ) -> OutboxRow:
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._require_conn(conn, outbox_id)
            _check_settleable(row, state)
            conn.execute(
                "UPDATE execution_outbox SET state = ?, detail = ?, "
                "settled_at = ? WHERE outbox_id = ?",
                (state.value, detail, _now(now).isoformat(), outbox_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return self.get(outbox_id)

    def reconcile_stale(
        self,
        tenant_id: str,
        *,
        older_than: timedelta,
        now: datetime | None = None,
    ) -> list[OutboxRow]:
        moment = _now(now)
        cutoff = moment - older_than
        rows = self._conn().execute(
            "SELECT * FROM execution_outbox WHERE tenant_id = ? AND state = ?",
            (tenant_id, OutboxState.DISPATCHING.value),
        ).fetchall()
        out: list[OutboxRow] = []
        for record in rows:
            row = self._row(record)
            if row.claimed_at is not None and row.claimed_at > cutoff:
                continue
            out.append(self.settle(
                row.outbox_id, OutboxState.UNKNOWN,
                detail="reconciler: dispatch outcome undeterminable",
                now=moment,
            ))
        return out

    def get(self, outbox_id: str) -> OutboxRow:
        return self._require_conn(self._conn(), outbox_id)

    def pending(self, tenant_id: str) -> list[OutboxRow]:
        rows = self._conn().execute(
            "SELECT * FROM execution_outbox WHERE tenant_id = ? AND state = ? "
            "ORDER BY created_at",
            (tenant_id, OutboxState.DISPATCH_PENDING.value),
        ).fetchall()
        return [self._row(r) for r in rows]

    def _require_conn(
        self, conn: sqlite3.Connection, outbox_id: str
    ) -> OutboxRow:
        record = conn.execute(
            "SELECT * FROM execution_outbox WHERE outbox_id = ?", (outbox_id,)
        ).fetchone()
        if record is None:
            raise KeyError(f"unknown outbox row: {outbox_id}")
        return self._row(record)

    def record_intent_enlisted(
        self,
        connection: sqlite3.Connection,
        *,
        proposal_id: str,
        tenant_id: str,
        item_id: str,
        tool_name: str,
        tool_call_hash: str,
        grant_jti: str,
        attempt_no: int = 1,
        now: datetime | None = None,
    ) -> OutboxRow:
        """Record the intent INSIDE the caller's open transaction.

        This is what makes "the outbox row is written in the same
        transaction that authorizes the call" true rather than aspirational:
        the row commits with the caller's authorization write and is rolled
        back with it. The caller owns the transaction — this method never
        commits, never rolls back, and never opens one of its own.

        Requires the connection to address the same database file as this
        adapter, whose constructor already created the table. Idempotent by
        ``(tenant_id, idempotency_key)`` exactly like :meth:`record_intent`,
        including against rows committed earlier by another connection.

        Deliberately issues NO transaction-control statement, not even DDL:
        ``executescript`` implicitly commits, which would silently end the
        caller's transaction and turn the atomicity guarantee into a lie
        while every test still passed. Pinned by the rollback test.
        """
        key = idempotency_key(proposal_id, tool_call_hash, attempt_no)
        found = connection.execute(
            "SELECT * FROM execution_outbox "
            "WHERE tenant_id = ? AND idempotency_key = ?",
            (tenant_id, key),
        ).fetchone()
        if found is not None:
            return self._row_any(found)
        outbox_id = str(uuid.uuid4())
        created = _now(now)
        connection.execute(
            "INSERT INTO execution_outbox (outbox_id, proposal_id, tenant_id, "
            "item_id, idempotency_key, tool_name, tool_call_hash, grant_jti, "
            "state, attempt_no, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (outbox_id, proposal_id, tenant_id, item_id, key, tool_name,
             tool_call_hash, grant_jti, OutboxState.DISPATCH_PENDING.value,
             attempt_no, created.isoformat()),
        )
        return OutboxRow(
            outbox_id=outbox_id,
            proposal_id=proposal_id,
            tenant_id=tenant_id,
            item_id=item_id,
            idempotency_key=key,
            tool_name=tool_name,
            tool_call_hash=tool_call_hash,
            grant_jti=grant_jti,
            state=OutboxState.DISPATCH_PENDING,
            attempt_no=attempt_no,
            created_at=created,
        )

    @classmethod
    def _row_any(cls, record: "sqlite3.Row | tuple") -> OutboxRow:
        """Parse a row from a caller connection, which may lack row_factory."""
        if not isinstance(record, sqlite3.Row):
            columns = (
                "outbox_id", "proposal_id", "tenant_id", "item_id",
                "idempotency_key", "tool_name", "tool_call_hash", "grant_jti",
                "state", "attempt_no", "created_at", "worker_id", "claimed_at",
                "settled_at", "detail",
            )
            record = dict(zip(columns, record))  # type: ignore[assignment]
        return cls._row(record)  # type: ignore[arg-type]


class PostgresExecutionOutbox(ExecutionOutbox):
    """Multi-worker durable outbox.

    Atomicity comes from ``SELECT ... FOR UPDATE`` on the row inside one
    transaction — the same contract ``PostgresTenantChain`` uses: two
    workers cannot both claim a row, and a retried authorization cannot
    insert a second intent (``UNIQUE (tenant_id, idempotency_key)`` is the
    second line of defense).

    This is the adapter a multi-worker deployment needs; the SQLite one is
    single-node by construction. Contract-tested against a real Postgres
    service in CI with a hard no-skip check, so "the multi-worker adapter
    is unverified" cannot quietly become true.
    """

    _SELECT = "SELECT " + ", ".join(_COLUMNS) + " FROM execution_outbox"

    def __init__(self, dsn: str) -> None:  # noqa: D107 - see class doc
        import psycopg  # type: ignore[import-not-found]

        self._psycopg = psycopg
        self._dsn = dsn
        with psycopg.connect(dsn) as conn:
            conn.execute(POSTGRES_DDL)
            conn.commit()

    @staticmethod
    def _row_tuple(record: tuple) -> OutboxRow:
        data = dict(zip(_COLUMNS, record))

        def _dt(value: str | None) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        return OutboxRow(
            outbox_id=data["outbox_id"],
            proposal_id=data["proposal_id"],
            tenant_id=data["tenant_id"],
            item_id=data["item_id"],
            idempotency_key=data["idempotency_key"],
            tool_name=data["tool_name"],
            tool_call_hash=data["tool_call_hash"],
            grant_jti=data["grant_jti"],
            state=OutboxState(data["state"]),
            attempt_no=int(data["attempt_no"]),
            created_at=_dt(data["created_at"]),  # type: ignore[arg-type]
            worker_id=data["worker_id"],
            claimed_at=_dt(data["claimed_at"]),
            settled_at=_dt(data["settled_at"]),
            detail=data["detail"],
        )

    def record_intent(
        self,
        *,
        proposal_id: str,
        tenant_id: str,
        item_id: str,
        tool_name: str,
        tool_call_hash: str,
        grant_jti: str,
        attempt_no: int = 1,
        now: datetime | None = None,
    ) -> OutboxRow:
        with self._psycopg.connect(self._dsn) as conn:
            with conn.transaction():
                return self.record_intent_enlisted(
                    conn,
                    proposal_id=proposal_id,
                    tenant_id=tenant_id,
                    item_id=item_id,
                    tool_name=tool_name,
                    tool_call_hash=tool_call_hash,
                    grant_jti=grant_jti,
                    attempt_no=attempt_no,
                    now=now,
                )

    def record_intent_enlisted(
        self,
        connection,  # psycopg.Connection; loose to avoid a hard import
        *,
        proposal_id: str,
        tenant_id: str,
        item_id: str,
        tool_name: str,
        tool_call_hash: str,
        grant_jti: str,
        attempt_no: int = 1,
        now: datetime | None = None,
    ) -> OutboxRow:
        """Record the intent inside the caller's open transaction.

        Same guarantee as the SQLite adapter: the row commits with the
        caller's authorization write and rolls back with it. Issues no
        transaction-control statement of its own — the caller owns the
        transaction.
        """
        key = idempotency_key(proposal_id, tool_call_hash, attempt_no)
        found = connection.execute(
            self._SELECT + " WHERE tenant_id = %s AND idempotency_key = %s",
            (tenant_id, key),
        ).fetchone()
        if found is not None:
            return self._row_tuple(found)
        outbox_id = str(uuid.uuid4())
        created = _now(now)
        connection.execute(
            "INSERT INTO execution_outbox (outbox_id, proposal_id, tenant_id, "
            "item_id, idempotency_key, tool_name, tool_call_hash, grant_jti, "
            "state, attempt_no, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (outbox_id, proposal_id, tenant_id, item_id, key, tool_name,
             tool_call_hash, grant_jti, OutboxState.DISPATCH_PENDING.value,
             attempt_no, created.isoformat()),
        )
        return OutboxRow(
            outbox_id=outbox_id,
            proposal_id=proposal_id,
            tenant_id=tenant_id,
            item_id=item_id,
            idempotency_key=key,
            tool_name=tool_name,
            tool_call_hash=tool_call_hash,
            grant_jti=grant_jti,
            state=OutboxState.DISPATCH_PENDING,
            attempt_no=attempt_no,
            created_at=created,
        )

    def claim(
        self, outbox_id: str, *, worker_id: str, now: datetime | None = None
    ) -> OutboxRow | None:
        with self._psycopg.connect(self._dsn) as conn:
            with conn.transaction():
                record = conn.execute(
                    self._SELECT + " WHERE outbox_id = %s FOR UPDATE",
                    (outbox_id,),
                ).fetchone()
                if record is None:
                    raise KeyError("unknown outbox row: " + outbox_id)
                row = self._row_tuple(record)
                _check_claimable(row)
                if row.state is not OutboxState.DISPATCH_PENDING:
                    return None
                conn.execute(
                    "UPDATE execution_outbox SET state = %s, worker_id = %s, "
                    "claimed_at = %s WHERE outbox_id = %s",
                    (OutboxState.DISPATCHING.value, worker_id,
                     _now(now).isoformat(), outbox_id),
                )
        return self.get(outbox_id)

    def settle(
        self,
        outbox_id: str,
        state: OutboxState,
        *,
        detail: str | None = None,
        now: datetime | None = None,
    ) -> OutboxRow:
        with self._psycopg.connect(self._dsn) as conn:
            with conn.transaction():
                record = conn.execute(
                    self._SELECT + " WHERE outbox_id = %s FOR UPDATE",
                    (outbox_id,),
                ).fetchone()
                if record is None:
                    raise KeyError("unknown outbox row: " + outbox_id)
                _check_settleable(self._row_tuple(record), state)
                conn.execute(
                    "UPDATE execution_outbox SET state = %s, detail = %s, "
                    "settled_at = %s WHERE outbox_id = %s",
                    (state.value, detail, _now(now).isoformat(), outbox_id),
                )
        return self.get(outbox_id)

    def reconcile_stale(
        self,
        tenant_id: str,
        *,
        older_than: timedelta,
        now: datetime | None = None,
    ) -> list[OutboxRow]:
        moment = _now(now)
        cutoff = moment - older_than
        with self._psycopg.connect(self._dsn) as conn:
            records = conn.execute(
                self._SELECT + " WHERE tenant_id = %s AND state = %s",
                (tenant_id, OutboxState.DISPATCHING.value),
            ).fetchall()
        out: list[OutboxRow] = []
        for record in records:
            row = self._row_tuple(record)
            if row.claimed_at is not None and row.claimed_at > cutoff:
                continue
            out.append(self.settle(
                row.outbox_id, OutboxState.UNKNOWN,
                detail="reconciler: dispatch outcome undeterminable",
                now=moment,
            ))
        return out

    def get(self, outbox_id: str) -> OutboxRow:
        with self._psycopg.connect(self._dsn) as conn:
            record = conn.execute(
                self._SELECT + " WHERE outbox_id = %s", (outbox_id,)
            ).fetchone()
        if record is None:
            raise KeyError("unknown outbox row: " + outbox_id)
        return self._row_tuple(record)

    def pending(self, tenant_id: str) -> list[OutboxRow]:
        with self._psycopg.connect(self._dsn) as conn:
            records = conn.execute(
                self._SELECT + " WHERE tenant_id = %s AND state = %s "
                "ORDER BY created_at",
                (tenant_id, OutboxState.DISPATCH_PENDING.value),
            ).fetchall()
        return [self._row_tuple(r) for r in records]
