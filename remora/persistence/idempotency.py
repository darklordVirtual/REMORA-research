# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Durable assess-idempotency store (issue #241 layout; review finding).

The previous cache was a process-local LRU: after a restart (or from a
second worker) a replayed idempotency key re-ran assess. Re-running assess
is decision-idempotent but NOT record-idempotent — it mints a new
proposal_id and appends a new chain record, so the caller's retry silently
forked the proposal identity.

With the same durability switches as every other execution store
(REMORA_PG_DSN → Postgres, REMORA_CHAIN_DB → SQLite), the response is
persisted keyed on (tenant, key) and survives restarts and worker fan-out.
Without them the in-process LRU remains — a recorded limitation of that
configuration, consistent with the chain/queue/ledger posture.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

_MAX_ENTRIES = 10_000

_DDL_SQLITE = (
    "CREATE TABLE IF NOT EXISTS assess_idempotency ("
    "tenant_id TEXT NOT NULL, idem_key TEXT NOT NULL, "
    "response_json TEXT NOT NULL, "
    "created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')), "
    "PRIMARY KEY (tenant_id, idem_key))"
)
_DDL_PG = (
    "CREATE TABLE IF NOT EXISTS assess_idempotency ("
    "tenant_id TEXT NOT NULL, idem_key TEXT NOT NULL, "
    "response_json TEXT NOT NULL, "
    "created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, "
    "PRIMARY KEY (tenant_id, idem_key))"
)


class IdempotencyStore:
    """In-process reference store (bounded LRU). Not durable: a restart
    forgets every key, which the durable adapters below exist to fix."""

    def __init__(self) -> None:
        self._entries: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    @property
    def durable(self) -> bool:
        return False

    def get(self, tenant: str, key: str) -> dict[str, Any] | None:
        hit = self._entries.get((tenant, key))
        if hit is not None:
            self._entries.move_to_end((tenant, key))
        return hit

    def put(self, tenant: str, key: str, response: dict[str, Any]) -> None:
        self._entries[(tenant, key)] = response
        self._entries.move_to_end((tenant, key))
        while len(self._entries) > _MAX_ENTRIES:
            self._entries.popitem(last=False)


class SQLiteIdempotencyStore(IdempotencyStore):
    def __init__(self, db_path: str) -> None:
        super().__init__()
        import sqlite3

        self._db_path = db_path
        with sqlite3.connect(db_path) as conn:
            conn.execute(_DDL_SQLITE)
            conn.commit()

    @property
    def durable(self) -> bool:
        return True

    def get(self, tenant: str, key: str) -> dict[str, Any] | None:
        import sqlite3

        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT response_json FROM assess_idempotency "
                "WHERE tenant_id = ? AND idem_key = ?",
                (tenant, key),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, tenant: str, key: str, response: dict[str, Any]) -> None:
        import sqlite3

        with sqlite3.connect(self._db_path) as conn:
            # First write wins: a concurrent retry must observe the original
            # response, never overwrite it with a forked proposal identity.
            conn.execute(
                "INSERT OR IGNORE INTO assess_idempotency "
                "(tenant_id, idem_key, response_json) VALUES (?, ?, ?)",
                (tenant, key, json.dumps(response)),
            )
            conn.commit()


class PostgresIdempotencyStore(IdempotencyStore):
    def __init__(self, dsn: str) -> None:
        super().__init__()
        import psycopg  # type: ignore

        self._psycopg = psycopg
        self._dsn = dsn
        with psycopg.connect(dsn) as conn:
            conn.execute(_DDL_PG)
            conn.commit()

    @property
    def durable(self) -> bool:
        return True

    def get(self, tenant: str, key: str) -> dict[str, Any] | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT response_json FROM assess_idempotency "
                "WHERE tenant_id = %s AND idem_key = %s",
                (tenant, key),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, tenant: str, key: str, response: dict[str, Any]) -> None:
        with self._psycopg.connect(self._dsn) as conn:
            conn.execute(
                "INSERT INTO assess_idempotency "
                "(tenant_id, idem_key, response_json) VALUES (%s, %s, %s) "
                "ON CONFLICT (tenant_id, idem_key) DO NOTHING",
                (tenant, key, json.dumps(response)),
            )
            conn.commit()


def build_idempotency_store(environ: Any) -> IdempotencyStore:
    """Same durability switches as the chain, queue and jti ledger."""
    dsn = environ.get("REMORA_PG_DSN", "").strip()
    if dsn:
        return PostgresIdempotencyStore(dsn)
    db = environ.get("REMORA_CHAIN_DB", "").strip()
    if db:
        return SQLiteIdempotencyStore(db)
    return IdempotencyStore()
