# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
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
  entry hash: v1 untagged and frozen, v2 domain-separated from an
  ``AUDIT_VERSION_TRANSITION`` record on (:mod:`remora.governance.audit_signing`,
  RMR-CR-011). History is never re-signed.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from remora.governance.audit_signing import (
    chain_signature_format,
    entry_signature,
    signature_problems,
    transition_payload,
)

_GENESIS = "0" * 64
_ENV_KEY = "REMORA_AUDIT_SIGNING_KEY"

#: (previous_hash, sequence_no) -> the payload to append at that position.
_PayloadAt = Callable[[str, int], dict[str, Any]]


def _signing_key() -> bytes:
    return os.environ.get(_ENV_KEY, "").strip().encode()


def _needs_transition(key: bytes, in_v2: bool) -> bool:
    """Whether this append must first write the AUDIT_VERSION_TRANSITION record.

    Only a signed chain has a format to change, and only once: a chain already
    in v2 stays there whatever this process would issue.
    """
    if not key or in_v2:
        return False
    from remora.crypto.formats import FORMAT_V2, signature_format

    return signature_format() == FORMAT_V2


def _transition_at(previous_hash: str, sequence_no: int) -> dict[str, Any]:
    return transition_payload(previous_hash, first=sequence_no == 0)

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
CREATE TABLE IF NOT EXISTS tenant_chain_idempotency (
    tenant_id       TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    PRIMARY KEY (tenant_id, idempotency_key)
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


def _head_problems(
    entries: Sequence[ChainEntry],
    expected_head: tuple[int, str] | None,
    stored_head: tuple[int, str] | None = None,
) -> list[str]:
    """Compare the last entry to an external anchor and/or a stored head row.

    Tail truncation (deleting the newest entries) leaves a self-consistent
    prefix, so it is invisible to per-entry checks. ``expected_head`` is a
    ``(sequence_no, entry_hash)`` pair held outside the chain store; a stored
    head row (Postgres) is compared the same way.
    """
    problems: list[str] = []
    last: tuple[int, str] = (
        (entries[-1].sequence_no, entries[-1].entry_hash) if entries else (-1, _GENESIS)
    )
    if expected_head is not None and (int(expected_head[0]), str(expected_head[1])) != last:
        problems.append(f"head_mismatch:expected_seq={expected_head[0]}:actual_seq={last[0]}")
    if stored_head is not None and (int(stored_head[0]), str(stored_head[1])) != last:
        problems.append(f"stored_head_mismatch:stored_seq={stored_head[0]}:actual_seq={last[0]}")
    return problems


class TenantAuditChain:
    """In-process reference implementation with atomic appends."""

    def __init__(self, now_fn: Callable[[], datetime] | None = None) -> None:
        self._entries: dict[str, list[ChainEntry]] = {}
        self._idempotency: set[tuple[str, str]] = set()
        #: Tenants whose chain has entered signature format v2.
        self._v2: set[str] = set()
        self._lock = threading.Lock()
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    def append(self, tenant_id: str, payload: dict[str, Any]) -> ChainEntry:
        """Atomic read-predecessor + insert: fork-free by construction."""
        with self._lock:
            return self._append_locked(tenant_id, payload)

    def append_once(
        self, tenant_id: str, idempotency_key: str, payload: dict[str, Any]
    ) -> ChainEntry | None:
        """Append and claim ``idempotency_key`` as one atomic operation.

        ``None`` means the key was already committed. The key and entry are
        mutated while holding the same lock, so an exception while building
        the entry cannot leave a claimed key without the audit evidence it is
        meant to protect.
        """
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        key = (tenant_id, idempotency_key)
        with self._lock:
            if key in self._idempotency:
                return None
            entry = self._append_locked(tenant_id, payload)
            self._idempotency.add(key)
            return entry

    def _append_locked(self, tenant_id: str, payload: dict[str, Any]) -> ChainEntry:
        key = _signing_key()
        in_v2 = tenant_id in self._v2
        if _needs_transition(key, in_v2):
            self._insert(tenant_id, _transition_at, key, v2=True)
            self._v2.add(tenant_id)
            in_v2 = True
        return self._insert(tenant_id, lambda _prev, _seq: payload, key, v2=in_v2)

    def _insert(self, tenant_id: str, payload_at: _PayloadAt, key: bytes, *,
                v2: bool) -> ChainEntry:
        chain = self._entries.setdefault(tenant_id, [])
        previous_hash = chain[-1].entry_hash if chain else _GENESIS
        sequence_no = len(chain)
        payload = payload_at(previous_hash, sequence_no)
        timestamp = self._now_fn().isoformat()
        entry_hash = compute_entry_hash(
            previous_hash, payload, tenant_id, sequence_no, timestamp
        )
        signature = entry_signature(entry_hash, key, v2=v2) if key else ""
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

    def verify(
        self, tenant_id: str, expected_head: tuple[int, str] | None = None
    ) -> tuple[bool, list[str]]:
        """Recompute one tenant's chain; report every break (complete set).

        ``expected_head`` is an optional ``(sequence_no, entry_hash)`` anchor
        held outside the store; a mismatch (e.g. tail truncation) is reported.
        """
        return _verify_generic(self, tenant_id, expected_head)

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
CREATE TABLE IF NOT EXISTS tenant_chain_idempotency (
    tenant_id       TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    PRIMARY KEY (tenant_id, idempotency_key)
);
"""

#: AACP-X-01: per-tenant head, written in the entry's transaction. Kept as
#: separate statements so ``SQLiteTenantChain`` can create them and run the
#: one-time migration inside a single ``BEGIN IMMEDIATE``.
_SQLITE_HEAD_DDL = (
    """CREATE TABLE IF NOT EXISTS tenant_chain_head (
    tenant_id         TEXT    PRIMARY KEY,
    head_hash         TEXT    NOT NULL,
    head_sequence     INTEGER NOT NULL,
    head_origin       TEXT    NOT NULL,
    baseline_sequence INTEGER NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS tenant_chain_schema (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)""",
)

#: The head has been written with every entry since the tenant's first one.
HEAD_ORIGIN_APPEND = "append"
#: The head was set at migration from history found in the file. Entries up to
#: ``baseline_sequence`` were never head-tracked: truncation before the
#: upgrade is not detectable from the database, and nothing about that
#: history is verified by this baseline.
HEAD_ORIGIN_LEGACY = "legacy_unanchored_baseline"
_HEAD_ORIGINS = frozenset({HEAD_ORIGIN_APPEND, HEAD_ORIGIN_LEGACY})

#: What a verification compared the chain against. A head stored in the same
#: database is defeated by anyone who can rewrite the database; only an
#: ``expected_head`` kept elsewhere makes truncation detectable against them.
INTEGRITY_SCOPE_LOCAL = "LOCAL_DATABASE_CONSISTENCY"
INTEGRITY_SCOPE_ANCHORED = "EXTERNALLY_ANCHORED"

_HEAD_TRACKING_KEY = "head_tracking"
_HEX64 = frozenset("0123456789abcdef")


class ChainHeadInconsistent(RuntimeError):
    """The stored head cannot be extended without hiding or forking history."""


def compute_entry_hash_from_canonical(
    previous_hash: str,
    canonical_payload: str,
    tenant_id: str,
    sequence_no: int,
    timestamp: str,
) -> str:
    """Same hash as :func:`compute_entry_hash`, over an already-canonical payload.

    Producers outside Python (the Cloudflare agent-control Worker) store the
    exact canonical string they hashed. Re-serialising their parsed payload
    here would risk a spurious mismatch on values Python and JavaScript
    render differently (``1.0`` vs ``1``), so an independent verifier must
    hash the stored bytes instead.
    """
    sep = "\x1f"
    preimage = sep.join((
        previous_hash,
        canonical_payload,
        tenant_id,
        str(sequence_no),
        timestamp,
    ))
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


#: What a verification established about signatures (RMR-CR-007). Kept apart
#: from the hash-chain result, because a chain re-linked by someone with write
#: access verifies as intact while its signatures say nothing.
SIGNATURE_CHECKED = "CHECKED"
SIGNATURE_NOT_CHECKED_NO_KEY = "NOT_CHECKED_NO_KEY"
SIGNATURE_UNSIGNED = "UNSIGNED"

_SIGNATURE_PROBLEMS = ("signature_mismatch_at:", "signature_missing_at:",
                       "audit_v1_after_transition_at:", "audit_v2_before_transition_at:",
                       "audit_transition_repeated_at:", "audit_transition_malformed_at:")


def verification_statuses(
    entries: tuple[ChainEntry, ...] | list[ChainEntry], problems: list[str]
) -> dict[str, str]:
    """``hash_chain_status`` and ``signature_status`` for one verification.

    - ``CHECKED``: this process holds ``REMORA_AUDIT_SIGNING_KEY``, so every
      signature was compared (failures are in ``problems``).
    - ``NOT_CHECKED_NO_KEY``: entries carry signatures, but this process has
      no key, so none was compared. An intact hash chain then shows only
      that the records link, not who wrote them.
    - ``UNSIGNED``: no entry carries a signature; the chain is hash-linked
      only, which anyone with write access can reproduce.

    ``signature_format`` (RMR-CR-011) is ``none``, ``v1``, ``v2`` or
    ``v1+v2``: a chain that crossed its AUDIT_VERSION_TRANSITION shows both.
    """
    if os.environ.get(_ENV_KEY, "").strip():
        signature = SIGNATURE_CHECKED
    elif any(getattr(e, "signature", "") for e in entries):
        signature = SIGNATURE_NOT_CHECKED_NO_KEY
    else:
        signature = SIGNATURE_UNSIGNED
    hash_problems = [p for p in problems if not p.startswith(_SIGNATURE_PROBLEMS)]
    return {
        "hash_chain_status": "INTACT" if not hash_problems else "BROKEN",
        "signature_status": signature,
        "signature_format": chain_signature_format(entries),
    }


def verify_exported_chain(
    rows: list[dict[str, Any]],
    *,
    signing_key: str | None = None,
) -> tuple[bool, list[str]]:
    """Verify a chain exported from an external producer, off-platform.

    This is what makes the Worker's trail independently checkable: an auditor
    pulls ``GET /envelopes`` and re-derives every hash here, on their own
    machine, without trusting the Worker's own verify endpoint.

    Each row needs ``sequence_no``, ``created_at``, ``envelope_canonical``,
    ``previous_hash``, ``entry_hash`` and (optionally) ``signature``. Rows
    must be in ascending sequence order. Returns ``(ok, problems)`` listing
    every failure, not just the first.
    """
    problems: list[str] = []
    previous_hash = _GENESIS
    key = (signing_key or os.environ.get(_ENV_KEY, "")).strip().encode()

    for i, row in enumerate(rows):
        sequence_no = int(row.get("sequence_no", -1))
        canonical = str(row.get("envelope_canonical", ""))
        entry_hash = str(row.get("entry_hash", ""))
        row_previous = str(row.get("previous_hash", ""))
        timestamp = str(row.get("created_at", ""))
        signature = str(row.get("signature", "") or "")

        if sequence_no != i:
            problems.append(f"sequence_gap_at:{i}")
        if row_previous != previous_hash:
            problems.append(f"chain_break_at:{i}")

        try:
            tenant_id = str(json.loads(canonical)["audit"]["tenant_id"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            problems.append(f"unreadable_payload_at:{i}:{exc}")
            previous_hash = entry_hash
            continue

        if compute_entry_hash_from_canonical(
            row_previous, canonical, tenant_id, sequence_no, timestamp
        ) != entry_hash:
            problems.append(f"hash_mismatch_at:{i}")

        # The Worker's envelope chain signs format v1 only (CR-011 scope).
        if key and signature:
            if not _hmac_equal(entry_signature(entry_hash, key, v2=False), signature):
                problems.append(f"signature_mismatch_at:{i}")
        elif key and not signature:
            problems.append(f"signature_missing_at:{i}")

        previous_hash = entry_hash

    return (not problems), problems


def _hmac_equal(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a, b)


def _verify_generic(
    chain: Any, tenant_id: str, expected_head: tuple[int, str] | None = None
) -> tuple[bool, list[str]]:
    problems: list[str] = []
    previous_hash = _GENESIS
    key = _signing_key()
    all_entries = chain.entries(tenant_id)
    stored_head_fn = getattr(chain, "stored_head", None)
    stored = stored_head_fn(tenant_id) if callable(stored_head_fn) else None
    problems.extend(_head_problems(all_entries, expected_head, stored))
    for i, e in enumerate(all_entries):
        if e.sequence_no != i:
            problems.append(f"sequence_gap_at:{i}")
        if e.previous_hash != previous_hash:
            problems.append(f"chain_break_at:{i}")
        if compute_entry_hash(e.previous_hash, e.payload, e.tenant_id,
                              e.sequence_no, e.timestamp) != e.entry_hash:
            problems.append(f"hash_mismatch_at:{i}")
        previous_hash = e.entry_hash
    # Signatures in their era (v1 before the AUDIT_VERSION_TRANSITION, v2 from
    # it on). A tamper-with-rehash (recomputing entry_hash after editing the
    # payload) is only caught here, by the key the attacker does not hold; a
    # missing signature under a configured key means it was stripped.
    problems.extend(signature_problems(all_entries, key))
    return (not problems, problems)


class SQLiteTenantChain:
    """Durable single-node adapter: same hash contract, atomic via
    ``BEGIN IMMEDIATE`` (the write lock covers predecessor read + insert),
    so concurrent appends serialise and can never fork. Survives restart.

    Head (AACP-X-01). ``tenant_chain_head`` holds each tenant's newest
    ``(sequence_no, entry_hash)``, written in the same transaction as the
    entry, and :meth:`verify` compares it with the last entry, so deleting the
    newest entries is reported as ``stored_head_mismatch``. A missing or
    malformed head row is reported, and refuses further appends, rather than
    being rebuilt from the entries.

    Migration. The first open of a database written before head tracking
    sets each existing tenant's head to its last entry, marked
    ``HEAD_ORIGIN_LEGACY`` with that entry as ``baseline_sequence``. This
    records the history as found; it is not a trusted head and does not
    verify that history. It runs once (``tenant_chain_schema`` records it).

    Limit. A head in the same file is local consistency only: whoever can
    rewrite both tables can truncate undetected. Pass an ``expected_head``
    held outside the database to :meth:`verify` for that;
    :meth:`verify_report` states which was checked.
    """

    def __init__(self, db_path: str, now_fn: Callable[[], datetime] | None = None) -> None:
        self._db_path = db_path
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._local = threading.local()
        conn = self._conn()
        conn.executescript(_SQLITE_DDL)
        self._migrate_head_tracking(conn)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=30, isolation_level=None)
            self._local.conn = conn
        return conn

    def _migrate_head_tracking(self, conn: sqlite3.Connection) -> None:
        """Create the head tables and baseline pre-existing tenants, once.

        A database that has migrated is recognised by a plain read, so an
        ordinary open takes no write lock (RMR-SEC-0023: another connection
        to the same file may hold one while this adapter is constructed).
        """
        try:
            if conn.execute(
                "SELECT 1 FROM tenant_chain_schema WHERE key = ?", (_HEAD_TRACKING_KEY,)
            ).fetchone() is not None:
                return
        except sqlite3.OperationalError:
            pass  # no schema table yet: migrate below
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _SQLITE_HEAD_DDL:
                conn.execute(statement)
            done = conn.execute(
                "SELECT value FROM tenant_chain_schema WHERE key = ?", (_HEAD_TRACKING_KEY,)
            ).fetchone()
            if done is None:
                conn.execute(
                    "INSERT OR IGNORE INTO tenant_chain_head "
                    "(tenant_id, head_hash, head_sequence, head_origin, baseline_sequence) "
                    "SELECT e.tenant_id, e.entry_hash, e.sequence_no, ?, e.sequence_no "
                    "FROM tenant_chain_entry e WHERE e.sequence_no = "
                    "(SELECT MAX(sequence_no) FROM tenant_chain_entry m "
                    " WHERE m.tenant_id = e.tenant_id)",
                    (HEAD_ORIGIN_LEGACY,),
                )
                conn.execute(
                    "INSERT INTO tenant_chain_schema (key, value) VALUES (?, ?)",
                    (_HEAD_TRACKING_KEY, self._now_fn().isoformat()),
                )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    @staticmethod
    def _head_row(conn: sqlite3.Connection, tenant_id: str) -> tuple[str, Any]:
        """``("none", None)``, ``("malformed", None)`` or ``("ok", row)``.

        ``row`` is ``(head_sequence, head_hash, head_origin, baseline_sequence)``
        and has been type-checked; nothing read here is trusted unchecked.
        """
        try:
            row = conn.execute(
                "SELECT head_sequence, head_hash, head_origin, baseline_sequence "
                "FROM tenant_chain_head WHERE tenant_id = ?", (tenant_id,),
            ).fetchone()
        except sqlite3.DatabaseError:
            return ("malformed", None)
        if row is None:
            return ("none", None)
        seq, head_hash, origin, baseline = row
        well_formed = (
            type(seq) is int and seq >= 0
            and isinstance(head_hash, str) and len(head_hash) == 64
            and set(head_hash) <= _HEX64
            and origin in _HEAD_ORIGINS
            and type(baseline) is int and baseline >= -1
        )
        return ("ok", row) if well_formed else ("malformed", None)

    def append(self, tenant_id: str, payload: dict[str, Any]) -> ChainEntry:
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")  # exclusive write txn: read+insert atomic
        try:
            entry = self._append_in_transaction(conn, tenant_id, payload)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return entry

    def append_once(
        self, tenant_id: str, idempotency_key: str, payload: dict[str, Any]
    ) -> ChainEntry | None:
        """Atomically claim a key and append its audit entry.

        The primary-key insert and chain append share one SQLite transaction.
        A crash or insert failure therefore rolls both back; a retry can never
        encounter a phantom claim whose evidence was not recorded.
        """
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            claimed = conn.execute(
                "INSERT OR IGNORE INTO tenant_chain_idempotency "
                "(tenant_id, idempotency_key) VALUES (?, ?)",
                (tenant_id, idempotency_key),
            )
            if claimed.rowcount == 0:
                conn.execute("COMMIT")
                return None
            entry = self._append_in_transaction(conn, tenant_id, payload)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return entry

    def _append_in_transaction(
        self, conn: sqlite3.Connection, tenant_id: str, payload: dict[str, Any]
    ) -> ChainEntry:
        key = _signing_key()
        # The transition record is the first v2 entry and v2-signed, so a
        # chain is in v2 exactly when some entry carries a v2 signature.
        in_v2 = bool(key) and conn.execute(
            "SELECT 1 FROM tenant_chain_entry WHERE tenant_id = ? "
            "AND signature LIKE 'v2:%' LIMIT 1", (tenant_id,),
        ).fetchone() is not None
        if _needs_transition(key, in_v2):
            self._insert(conn, tenant_id, _transition_at, key, v2=True)
            in_v2 = True
        return self._insert(conn, tenant_id, lambda _prev, _seq: payload, key, v2=in_v2)

    def _predecessor(self, conn: sqlite3.Connection, tenant_id: str) -> tuple[str, int]:
        """``(previous_hash, sequence_no)`` for the next entry, from the head.

        Like Postgres, the head row is the predecessor. After a truncation the
        next entry links to the head, not to the surviving last entry, so the
        gap stays visible in verify() instead of being covered by a new head.
        """
        status, head = self._head_row(conn, tenant_id)
        last = conn.execute(
            "SELECT sequence_no FROM tenant_chain_entry WHERE tenant_id = ? "
            "ORDER BY sequence_no DESC LIMIT 1", (tenant_id,),
        ).fetchone()
        if status == "malformed":
            raise ChainHeadInconsistent(
                f"tenant_chain_head row for tenant {tenant_id!r} is malformed; "
                "refusing to append")
        if status == "none":
            if last is not None:
                raise ChainHeadInconsistent(
                    f"tenant {tenant_id!r} has entries but no tenant_chain_head row; "
                    "refusing to append rather than rebuild the head from entries")
            return (_GENESIS, 0)
        head_seq, head_hash = int(head[0]), str(head[1])
        if last is not None and int(last[0]) > head_seq:
            raise ChainHeadInconsistent(
                f"tenant {tenant_id!r} has entries past its stored head "
                f"({last[0]} > {head_seq}); refusing to append")
        return (head_hash, head_seq + 1)

    def _insert(self, conn: sqlite3.Connection, tenant_id: str, payload_at: _PayloadAt,
                key: bytes, *, v2: bool) -> ChainEntry:
        previous_hash, sequence_no = self._predecessor(conn, tenant_id)
        payload = payload_at(previous_hash, sequence_no)
        timestamp = self._now_fn().isoformat()
        entry_hash = compute_entry_hash(
            previous_hash, payload, tenant_id, sequence_no, timestamp
        )
        signature = entry_signature(entry_hash, key, v2=v2) if key else ""
        conn.execute(
            "INSERT INTO tenant_chain_entry VALUES (?,?,?,?,?,?,?)",
            (tenant_id, sequence_no, timestamp, _canonical(payload),
             previous_hash, entry_hash, signature),
        )
        # Same transaction as the entry: both commit or neither does.
        conn.execute(
            "INSERT INTO tenant_chain_head "
            "(tenant_id, head_hash, head_sequence, head_origin, baseline_sequence) "
            "VALUES (?, ?, ?, ?, -1) ON CONFLICT (tenant_id) DO UPDATE SET "
            "head_hash = excluded.head_hash, head_sequence = excluded.head_sequence",
            (tenant_id, entry_hash, sequence_no, HEAD_ORIGIN_APPEND),
        )
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

    def stored_head(self, tenant_id: str) -> tuple[int, str] | None:
        """The per-tenant head row, or None when it is absent or malformed.

        ``verify`` reports which of the two it was; this accessor only
        returns a head that passed its type checks.
        """
        status, head = self._head_row(self._conn(), tenant_id)
        return (int(head[0]), str(head[1])) if status == "ok" else None

    def verify(
        self, tenant_id: str, expected_head: tuple[int, str] | None = None
    ) -> tuple[bool, list[str]]:
        report = self.verify_report(tenant_id, expected_head)
        return (report["ok"], report["problems"])

    def verify_report(
        self, tenant_id: str, expected_head: tuple[int, str] | None = None
    ) -> dict[str, Any]:
        """``verify`` plus what it was checked against.

        ``integrity_scope`` is ``INTEGRITY_SCOPE_ANCHORED`` only when an
        ``expected_head`` from outside the database was compared, else
        ``INTEGRITY_SCOPE_LOCAL``. ``head_origin`` and ``baseline_sequence``
        say whether the head has tracked every entry or was baselined at
        migration. Reads run in one transaction so a concurrent append cannot
        appear as a head mismatch.
        """
        conn = self._conn()
        conn.execute("BEGIN")
        try:
            status, head = self._head_row(conn, tenant_id)
            _ok, problems = _verify_generic(self, tenant_id, expected_head)
            head_problems: list[str] = []
            if status == "malformed":
                head_problems.append("stored_head_malformed")
            elif status == "none" and conn.execute(
                "SELECT 1 FROM tenant_chain_entry WHERE tenant_id = ? LIMIT 1", (tenant_id,),
            ).fetchone() is not None:
                head_problems.append("stored_head_missing")
        finally:
            conn.execute("COMMIT")
        problems = head_problems + problems
        return {
            "ok": not problems,
            "problems": problems,
            "integrity_scope": (INTEGRITY_SCOPE_ANCHORED if expected_head is not None
                                else INTEGRITY_SCOPE_LOCAL),
            "head_origin": head[2] if status == "ok" else None,
            "baseline_sequence": int(head[3]) if status == "ok" else None,
        }


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
                entry = self._append_in_transaction(conn, tenant_id, payload)
        return entry

    def append_once(
        self, tenant_id: str, idempotency_key: str, payload: dict[str, Any]
    ) -> ChainEntry | None:
        """Claim a key and append inside one Postgres transaction."""
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        with self._psycopg.connect(self._dsn) as conn:
            with conn.transaction():
                claimed = conn.execute(
                    "INSERT INTO tenant_chain_idempotency "
                    "(tenant_id, idempotency_key) VALUES (%s, %s) "
                    "ON CONFLICT (tenant_id, idempotency_key) DO NOTHING "
                    "RETURNING idempotency_key",
                    (tenant_id, idempotency_key),
                ).fetchone()
                if claimed is None:
                    return None
                entry = self._append_in_transaction(conn, tenant_id, payload)
        return entry

    def _append_in_transaction(
        self, conn: Any, tenant_id: str, payload: dict[str, Any]
    ) -> ChainEntry:
        key = _signing_key()
        in_v2 = bool(key) and conn.execute(
            "SELECT 1 FROM tenant_chain_entry WHERE tenant_id = %s "
            "AND signature LIKE 'v2:%%' LIMIT 1", (tenant_id,),
        ).fetchone() is not None
        if _needs_transition(key, in_v2):
            self._insert(conn, tenant_id, _transition_at, key, v2=True)
            in_v2 = True
        return self._insert(conn, tenant_id, lambda _prev, _seq: payload, key, v2=in_v2)

    def _insert(self, conn: Any, tenant_id: str, payload_at: _PayloadAt, key: bytes, *,
                v2: bool) -> ChainEntry:
        conn.execute(
            "INSERT INTO tenant_chain_head VALUES (%s, %s, -1) "
            "ON CONFLICT (tenant_id) DO NOTHING", (tenant_id, _GENESIS),
        )
        row = conn.execute(
            "SELECT head_hash, head_sequence FROM tenant_chain_head "
            "WHERE tenant_id = %s FOR UPDATE", (tenant_id,),
        ).fetchone()
        if row is None:
            # The upsert above should guarantee this row. If it is gone anyway
            # the chain has no predecessor to link to; appending would silently
            # start a second chain for this tenant.
            raise RuntimeError(
                f"no chain head for tenant {tenant_id!r} in "
                "tenant_chain_head immediately after upsert; refusing "
                "to append an entry with no predecessor"
            )
        previous_hash, sequence_no = row[0], row[1] + 1
        payload = payload_at(previous_hash, sequence_no)
        timestamp = self._now_fn().isoformat()
        entry_hash = compute_entry_hash(
            previous_hash, payload, tenant_id, sequence_no, timestamp
        )
        signature = entry_signature(entry_hash, key, v2=v2) if key else ""
        conn.execute(
            "INSERT INTO tenant_chain_entry "
            "(tenant_id, sequence_no, timestamp, payload, previous_hash, "
            "entry_hash, signature) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (tenant_id, sequence_no, timestamp, _canonical(payload),
             previous_hash, entry_hash, signature),
        )
        conn.execute(
            "UPDATE tenant_chain_head SET head_hash=%s, head_sequence=%s "
            "WHERE tenant_id=%s", (entry_hash, sequence_no, tenant_id),
        )
        return ChainEntry(tenant_id, sequence_no, timestamp, payload,
                          previous_hash, entry_hash, signature)

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

    def stored_head(self, tenant_id: str) -> tuple[int, str] | None:
        """The per-tenant head row, or None when no row exists."""
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT head_sequence, head_hash FROM tenant_chain_head "
                "WHERE tenant_id = %s", (tenant_id,),
            ).fetchone()
        return None if row is None else (int(row[0]), str(row[1]))

    def verify(
        self, tenant_id: str, expected_head: tuple[int, str] | None = None
    ) -> tuple[bool, list[str]]:
        return _verify_generic(self, tenant_id, expected_head)
