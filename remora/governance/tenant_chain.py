# Author: Stian Skogbrott
# License: Apache-2.0
"""Atomic per-tenant audit chain (REM-034).

External review finding: the REST path produced individually signed records
whose envelope hash did not cover ``previous_hash``, with predecessor lookup
and insert as separate unserialised operations — concurrent writes could
fork the chain, and no verifier existed.

This module is the fix, as a storage-agnostic core:

- ``entry_hash = SHA256(previous_hash || canonical(payload) || tenant_id
  || sequence_no || timestamp)`` — the predecessor, tenant, position and
  time are all inside the hash, so none can be rewritten without breaking
  every later entry.
- ``append()`` is atomic: predecessor read, sequence assignment and insert
  happen under one lock (in-process) — two concurrent appends can never
  read the same predecessor. The equivalent Postgres discipline is shipped
  as :data:`POSTGRES_DDL` (per-tenant head row + ``SELECT ... FOR UPDATE``
  + unique ``(tenant_id, sequence_no)``); an adapter implementing
  ``append`` inside one transaction satisfies the same contract.
- ``verify()`` recomputes the whole chain per tenant and reports every
  break (used at export and startup).
- Optional HMAC signature per entry (``REMORA_AUDIT_SIGNING_KEY``) over the
  entry hash.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

_GENESIS = "0" * 64
_ENV_KEY = "REMORA_AUDIT_SIGNING_KEY"

POSTGRES_DDL = """
-- REM-034: atomic per-tenant audit chain (deployment adapter).
CREATE TABLE IF NOT EXISTS tenant_chain_head (
    tenant_id     TEXT PRIMARY KEY,
    head_hash     TEXT NOT NULL,
    head_sequence BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS tenant_chain_entry (
    tenant_id     TEXT   NOT NULL,
    sequence_no   BIGINT NOT NULL,
    timestamp     TEXT   NOT NULL,
    payload       JSONB  NOT NULL,
    previous_hash TEXT   NOT NULL,
    entry_hash    TEXT   NOT NULL,
    signature     TEXT   NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_id, sequence_no)
);
-- append() MUST run in one transaction:
--   SELECT head_hash, head_sequence FROM tenant_chain_head
--     WHERE tenant_id = $1 FOR UPDATE;
--   INSERT INTO tenant_chain_entry ...;
--   UPDATE tenant_chain_head SET head_hash = $h, head_sequence = $s ...;
"""


def _canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_entry_hash(
    previous_hash: str,
    payload: dict[str, Any],
    tenant_id: str,
    sequence_no: int,
    timestamp: str,
) -> str:
    # ASCII unit separator (0x1f) between every field so field boundaries are
    # unambiguous: without it (tenant="a", seq=12) and (tenant="a1", seq=2)
    # would hash identically. 0x1f cannot occur in any field value (hex hash,
    # JSON, identifier, ISO timestamp), so it is an injective delimiter.
    sep = "\x1f"
    preimage = sep.join((
        previous_hash,
        _canonical(payload),
        tenant_id,
        str(sequence_no),
        timestamp,
    ))
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChainEntry:
    tenant_id: str
    sequence_no: int
    timestamp: str
    payload: dict[str, Any]
    previous_hash: str
    entry_hash: str
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TenantAuditChain:
    """In-process reference implementation with atomic appends."""

    def __init__(self, now_fn: Callable[[], datetime] | None = None) -> None:
        self._entries: dict[str, list[ChainEntry]] = {}
        self._lock = threading.Lock()
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    def append(self, tenant_id: str, payload: dict[str, Any]) -> ChainEntry:
        """Atomic read-predecessor + insert: fork-free by construction."""
        with self._lock:
            chain = self._entries.setdefault(tenant_id, [])
            previous_hash = chain[-1].entry_hash if chain else _GENESIS
            sequence_no = len(chain)
            timestamp = self._now_fn().isoformat()
            entry_hash = compute_entry_hash(
                previous_hash, payload, tenant_id, sequence_no, timestamp
            )
            key = os.environ.get(_ENV_KEY, "").strip().encode()
            signature = (
                hmac.new(key, entry_hash.encode(), hashlib.sha256).hexdigest()
                if key else ""
            )
            entry = ChainEntry(
                tenant_id=tenant_id,
                sequence_no=sequence_no,
                timestamp=timestamp,
                payload=payload,
                previous_hash=previous_hash,
                entry_hash=entry_hash,
                signature=signature,
            )
            chain.append(entry)
            return entry

    def entries(self, tenant_id: str) -> tuple[ChainEntry, ...]:
        with self._lock:
            return tuple(self._entries.get(tenant_id, ()))

    def verify(self, tenant_id: str) -> tuple[bool, list[str]]:
        """Recompute one tenant's chain; report every break (complete set)."""
        problems: list[str] = []
        previous_hash = _GENESIS
        key = os.environ.get(_ENV_KEY, "").strip().encode()
        for i, entry in enumerate(self.entries(tenant_id)):
            if entry.sequence_no != i:
                problems.append(f"sequence_gap_at:{i}")
            if entry.previous_hash != previous_hash:
                problems.append(f"chain_break_at:{i}")
            expected = compute_entry_hash(
                entry.previous_hash, entry.payload, entry.tenant_id,
                entry.sequence_no, entry.timestamp,
            )
            if expected != entry.entry_hash:
                problems.append(f"hash_mismatch_at:{i}")
            if key and entry.signature:
                want = hmac.new(key, entry.entry_hash.encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(want, entry.signature):
                    problems.append(f"signature_mismatch_at:{i}")
            previous_hash = entry.entry_hash
        return (not problems, problems)

    def verify_all(self) -> tuple[bool, dict[str, list[str]]]:
        report = {t: self.verify(t)[1] for t in list(self._entries)}
        report = {t: p for t, p in report.items() if p}
        return (not report, report)


# ---------------------------------------------------------------------------
# Durable adapters (REM-034 completion)
# ---------------------------------------------------------------------------

_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS tenant_chain_entry (
    tenant_id     TEXT    NOT NULL,
    sequence_no   INTEGER NOT NULL,
    timestamp     TEXT    NOT NULL,
    payload       TEXT    NOT NULL,
    previous_hash TEXT    NOT NULL,
    entry_hash    TEXT    NOT NULL,
    signature     TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_id, sequence_no)
);
"""


def _verify_generic(chain, tenant_id: str) -> tuple[bool, list[str]]:
    problems: list[str] = []
    previous_hash = _GENESIS
    key = os.environ.get(_ENV_KEY, "").strip().encode()
    for i, e in enumerate(chain.entries(tenant_id)):
        if e.sequence_no != i:
            problems.append(f"sequence_gap_at:{i}")
        if e.previous_hash != previous_hash:
            problems.append(f"chain_break_at:{i}")
        if compute_entry_hash(e.previous_hash, e.payload, e.tenant_id,
                              e.sequence_no, e.timestamp) != e.entry_hash:
            problems.append(f"hash_mismatch_at:{i}")
        # Durable-path signature check: a tamper-with-rehash (recomputing
        # entry_hash after editing payload) is only caught by the HMAC, which
        # requires the key the attacker does not hold.
        if key and e.signature:
            want = hmac.new(key, e.entry_hash.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(want, e.signature):
                problems.append(f"signature_mismatch_at:{i}")
        elif key and not e.signature:
            # Key configured but an entry carries no signature -> stripped.
            problems.append(f"signature_missing_at:{i}")
        previous_hash = e.entry_hash
    return (not problems, problems)


class SQLiteTenantChain:
    """Durable single-node adapter: same hash contract, atomic via
    ``BEGIN IMMEDIATE`` (the write lock covers predecessor read + insert),
    so concurrent appends serialise and can never fork. Survives restart."""

    def __init__(self, db_path: str, now_fn: Callable[[], datetime] | None = None) -> None:
        self._db_path = db_path
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._local = threading.local()
        self._conn().executescript(_SQLITE_DDL)

    def _conn(self):
        import sqlite3

        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=30, isolation_level=None)
            self._local.conn = conn
        return conn

    def append(self, tenant_id: str, payload: dict[str, Any]) -> ChainEntry:
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")  # exclusive write txn: read+insert atomic
        try:
            row = conn.execute(
                "SELECT entry_hash, sequence_no FROM tenant_chain_entry "
                "WHERE tenant_id = ? ORDER BY sequence_no DESC LIMIT 1",
                (tenant_id,),
            ).fetchone()
            previous_hash, sequence_no = (row[0], row[1] + 1) if row else (_GENESIS, 0)
            timestamp = self._now_fn().isoformat()
            entry_hash = compute_entry_hash(
                previous_hash, payload, tenant_id, sequence_no, timestamp
            )
            key = os.environ.get(_ENV_KEY, "").strip().encode()
            signature = (
                hmac.new(key, entry_hash.encode(), hashlib.sha256).hexdigest()
                if key else ""
            )
            conn.execute(
                "INSERT INTO tenant_chain_entry VALUES (?,?,?,?,?,?,?)",
                (tenant_id, sequence_no, timestamp, _canonical(payload),
                 previous_hash, entry_hash, signature),
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return ChainEntry(tenant_id, sequence_no, timestamp, payload,
                          previous_hash, entry_hash, signature)

    def entries(self, tenant_id: str) -> tuple[ChainEntry, ...]:
        rows = self._conn().execute(
            "SELECT tenant_id, sequence_no, timestamp, payload, previous_hash, "
            "entry_hash, signature FROM tenant_chain_entry WHERE tenant_id = ? "
            "ORDER BY sequence_no", (tenant_id,),
        ).fetchall()
        return tuple(
            ChainEntry(r[0], r[1], r[2], json.loads(r[3]), r[4], r[5], r[6])
            for r in rows
        )

    def verify(self, tenant_id: str) -> tuple[bool, list[str]]:
        return _verify_generic(self, tenant_id)


class PostgresTenantChain:
    """Multi-node durable adapter: implements the POSTGRES_DDL contract with
    ``SELECT ... FOR UPDATE`` on the per-tenant head row inside one
    transaction. Requires ``psycopg`` and a DSN; contract-tested when
    REMORA_PG_DSN is set (skipped otherwise)."""

    def __init__(self, dsn: str, now_fn: Callable[[], datetime] | None = None) -> None:
        import psycopg  # type: ignore[import-not-found]

        self._psycopg = psycopg
        self._dsn = dsn
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        with psycopg.connect(dsn) as conn:
            conn.execute(POSTGRES_DDL)
            conn.commit()

    def append(self, tenant_id: str, payload: dict[str, Any]) -> ChainEntry:
        with self._psycopg.connect(self._dsn) as conn:
            with conn.transaction():
                conn.execute(
                    "INSERT INTO tenant_chain_head VALUES (%s, %s, -1) "
                    "ON CONFLICT (tenant_id) DO NOTHING", (tenant_id, _GENESIS),
                )
                row = conn.execute(
                    "SELECT head_hash, head_sequence FROM tenant_chain_head "
                    "WHERE tenant_id = %s FOR UPDATE", (tenant_id,),
                ).fetchone()
                previous_hash, sequence_no = row[0], row[1] + 1
                timestamp = self._now_fn().isoformat()
                entry_hash = compute_entry_hash(
                    previous_hash, payload, tenant_id, sequence_no, timestamp
                )
                conn.execute(
                    "INSERT INTO tenant_chain_entry "
                    "(tenant_id, sequence_no, timestamp, payload, previous_hash, "
                    "entry_hash) VALUES (%s,%s,%s,%s,%s,%s)",
                    (tenant_id, sequence_no, timestamp, _canonical(payload),
                     previous_hash, entry_hash),
                )
                conn.execute(
                    "UPDATE tenant_chain_head SET head_hash=%s, head_sequence=%s "
                    "WHERE tenant_id=%s", (entry_hash, sequence_no, tenant_id),
                )
        return ChainEntry(tenant_id, sequence_no, timestamp, payload,
                          previous_hash, entry_hash, "")

    def entries(self, tenant_id: str) -> tuple[ChainEntry, ...]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT tenant_id, sequence_no, timestamp, payload, "
                "previous_hash, entry_hash, signature FROM tenant_chain_entry "
                "WHERE tenant_id = %s ORDER BY sequence_no", (tenant_id,),
            ).fetchall()
        return tuple(
            ChainEntry(r[0], r[1], r[2],
                       r[3] if isinstance(r[3], dict) else json.loads(r[3]),
                       r[4], r[5], r[6] or "")
            for r in rows
        )

    def verify(self, tenant_id: str) -> tuple[bool, list[str]]:
        return _verify_generic(self, tenant_id)
