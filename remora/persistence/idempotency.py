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

Reservation (code review of 898758f, finding 3)
-----------------------------------------------

``get`` then ``put`` let two concurrent requests with the same key both miss,
both assess, and both return their own executable grant: ``INSERT OR IGNORE``
only chose which of the two answers was stored. :meth:`IdempotencyStore.claim`
reserves the key atomically before anything is assessed. The winner assesses
and calls :meth:`~IdempotencyStore.complete`; a concurrent request with the
same key waits for that answer and returns it, so one key yields one decision
and at most one grant. A reservation records a fingerprint of the request, and
the same key with a different request is refused (:class:`IdempotencyConflict`)
instead of answered with another request's decision. A failed assessment
releases its reservation. A reservation whose owner crashed is taken over only
after ``stale_after_s``, which must exceed any request's running time; until
then the key answers "in progress" rather than risk a second grant.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
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


#: Version tag of a reservation record. Rows written by ``put`` lack it.
_RECORD = "idempotency-reservation/v1"


class IdempotencyConflict(Exception):
    """The key cannot be answered for this request; nothing was assessed.

    ``reason`` is ``"request_mismatch"`` when the key already belongs to a
    different request, and ``"in_progress"`` when another request holds it
    and has not finished within the wait.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class IdempotencyClaim:
    """The caller's reservation. ``response`` is set when the key was already
    answered for the same request; otherwise the caller owns the key and must
    :meth:`IdempotencyStore.complete` or :meth:`IdempotencyStore.release` it."""

    __slots__ = ("tenant", "key", "response", "record")

    def __init__(self, tenant: str, key: str, response: dict[str, Any] | None,
                 record: str | None) -> None:
        self.tenant, self.key, self.response, self.record = tenant, key, response, record

    @property
    def owned(self) -> bool:
        return self.record is not None


def idempotency_scope(principal: str, key: str,
                      request: Mapping[str, Any]) -> tuple[str, str]:
    """The stored key and the request fingerprint for a caller's key.

    The stored key names the principal, so one principal's key never answers
    another's request in the same tenant. The fingerprint is the SHA-256 of
    the request's canonical JSON without the key itself.
    """
    who = hashlib.sha256(principal.encode("utf-8")).hexdigest()[:32]
    body = json.dumps(request, sort_keys=True, separators=(",", ":"), default=str)
    return f"p:{who}:{key}", hashlib.sha256(body.encode("utf-8")).hexdigest()


def _decode(raw: str) -> dict[str, Any] | None:
    try:
        record = json.loads(raw)
    except ValueError:
        return None
    return record if isinstance(record, dict) and record.get("record") == _RECORD else None


class IdempotencyStore:
    """In-process reference store (bounded LRU). Not durable: a restart
    forgets every key, which the durable adapters below exist to fix."""

    def __init__(self) -> None:
        self._entries: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self._raw: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._lock = threading.Lock()

    # The three row primitives a reservation needs; each is atomic per row.

    def _insert_raw(self, tenant: str, key: str, raw: str) -> bool:
        with self._lock:
            if (tenant, key) in self._raw:
                return False
            self._raw[(tenant, key)] = raw
            while len(self._raw) > _MAX_ENTRIES:
                self._raw.popitem(last=False)
            return True

    def _read_raw(self, tenant: str, key: str) -> str | None:
        with self._lock:
            return self._raw.get((tenant, key))

    def _swap_raw(self, tenant: str, key: str, expected: str, new: str | None) -> bool:
        with self._lock:
            if self._raw.get((tenant, key)) != expected:
                return False
            if new is None:
                del self._raw[(tenant, key)]
            else:
                self._raw[(tenant, key)] = new
            return True

    def claim(self, tenant: str, key: str, fingerprint: str, *,
              wait_s: float = 10.0, stale_after_s: float = 300.0,
              poll_s: float = 0.05) -> IdempotencyClaim:
        """Reserve ``key`` for the request ``fingerprint``, or return its answer."""
        deadline = time.monotonic() + wait_s
        while True:
            pending = json.dumps({"record": _RECORD, "fingerprint": fingerprint,
                                  "state": "pending", "owner": secrets.token_hex(16),
                                  "claimed_at": time.time()}, sort_keys=True)
            if self._insert_raw(tenant, key, pending):
                return IdempotencyClaim(tenant, key, None, pending)
            raw = self._read_raw(tenant, key)
            if raw is None:
                continue  # released between the insert and the read
            record = _decode(raw)
            if record is None or record.get("fingerprint") != fingerprint:
                raise IdempotencyConflict("request_mismatch")
            if record.get("state") == "done":
                return IdempotencyClaim(tenant, key, record["response"], None)
            if time.time() - float(record.get("claimed_at", 0)) > stale_after_s:
                if self._swap_raw(tenant, key, raw, pending):
                    return IdempotencyClaim(tenant, key, None, pending)
                continue
            if time.monotonic() >= deadline:
                raise IdempotencyConflict("in_progress")
            time.sleep(poll_s)

    def complete(self, claim: IdempotencyClaim, response: dict[str, Any]) -> bool:
        """Record the owner's answer. False if a stale takeover replaced the
        reservation; the answer is then not stored, and the caller still has it."""
        if claim.record is None:
            raise ValueError("only the owner of a reservation can complete it")
        fingerprint = json.loads(claim.record)["fingerprint"]
        done = json.dumps({"record": _RECORD, "fingerprint": fingerprint,
                           "state": "done", "response": response}, sort_keys=True)
        return self._swap_raw(claim.tenant, claim.key, claim.record, done)

    def release(self, claim: IdempotencyClaim) -> None:
        """Give the key back after a failed assessment, so a retry can run."""
        if claim.record is not None:
            self._swap_raw(claim.tenant, claim.key, claim.record, None)

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
        from remora.persistence.sqlite_path import refuse_memory_db
        refuse_memory_db(db_path, what="idempotency ledger")
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

    def _insert_raw(self, tenant: str, key: str, raw: str) -> bool:
        import sqlite3

        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO assess_idempotency "
                "(tenant_id, idem_key, response_json) VALUES (?, ?, ?)",
                (tenant, key, raw),
            )
            conn.commit()
            return cursor.rowcount == 1

    def _read_raw(self, tenant: str, key: str) -> str | None:
        import sqlite3

        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT response_json FROM assess_idempotency "
                "WHERE tenant_id = ? AND idem_key = ?",
                (tenant, key),
            ).fetchone()
        return row[0] if row else None

    def _swap_raw(self, tenant: str, key: str, expected: str, new: str | None) -> bool:
        import sqlite3

        with sqlite3.connect(self._db_path) as conn:
            if new is None:
                cursor = conn.execute(
                    "DELETE FROM assess_idempotency "
                    "WHERE tenant_id = ? AND idem_key = ? AND response_json = ?",
                    (tenant, key, expected),
                )
            else:
                cursor = conn.execute(
                    "UPDATE assess_idempotency SET response_json = ? "
                    "WHERE tenant_id = ? AND idem_key = ? AND response_json = ?",
                    (new, tenant, key, expected),
                )
            conn.commit()
            return cursor.rowcount == 1


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

    def _insert_raw(self, tenant: str, key: str, raw: str) -> bool:
        with self._psycopg.connect(self._dsn) as conn:
            cursor = conn.execute(
                "INSERT INTO assess_idempotency "
                "(tenant_id, idem_key, response_json) VALUES (%s, %s, %s) "
                "ON CONFLICT (tenant_id, idem_key) DO NOTHING",
                (tenant, key, raw),
            )
            conn.commit()
            return bool(cursor.rowcount == 1)

    def _read_raw(self, tenant: str, key: str) -> str | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT response_json FROM assess_idempotency "
                "WHERE tenant_id = %s AND idem_key = %s",
                (tenant, key),
            ).fetchone()
        return str(row[0]) if row else None

    def _swap_raw(self, tenant: str, key: str, expected: str, new: str | None) -> bool:
        with self._psycopg.connect(self._dsn) as conn:
            if new is None:
                cursor = conn.execute(
                    "DELETE FROM assess_idempotency "
                    "WHERE tenant_id = %s AND idem_key = %s AND response_json = %s",
                    (tenant, key, expected),
                )
            else:
                cursor = conn.execute(
                    "UPDATE assess_idempotency SET response_json = %s "
                    "WHERE tenant_id = %s AND idem_key = %s AND response_json = %s",
                    (new, tenant, key, expected),
                )
            conn.commit()
            return bool(cursor.rowcount == 1)


def build_idempotency_store(environ: Any) -> IdempotencyStore:
    """Same durability switches as the chain, queue and jti ledger."""
    dsn = environ.get("REMORA_PG_DSN", "").strip()
    if dsn:
        return PostgresIdempotencyStore(dsn)
    db = environ.get("REMORA_CHAIN_DB", "").strip()
    if db:
        return SQLiteIdempotencyStore(db)
    return IdempotencyStore()
