# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Control-plane persistence adapters for REMORA API.

Provides tenant-scoped storage for decision envelopes, audit records,
review decisions, and follow-up workflow events.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass(frozen=True)
class ReviewRecord:
    request_id: str
    tenant_id: str
    reviewer_id: str
    decision: str
    reason: str
    evidence_refs: list[str]
    created_at: str


@dataclass(frozen=True)
class FollowUpRecord:
    request_id: str
    tenant_id: str
    follow_up_type: str
    requested_by: str | None
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class EvidenceRecord:
    request_id: str
    tenant_id: str
    evidence_type: str
    payload: dict[str, Any]
    submitted_by: str | None
    created_at: str


class ControlPlaneStore(Protocol):
    #: Whether decisions survive a process restart. Consumers that assert an
    #: auditable trail (shadow mode, external review, replay) must refuse to
    #: treat a non-durable store as evidence; the API surfaces this flag so a
    #: volatile fallback is never silent.
    durable: bool

    def save_decision(
        self,
        *,
        request_id: str,
        tenant_id: str,
        envelope: dict[str, Any],
        audit_record: dict[str, Any],
    ) -> None:
        ...

    def get_envelope(self, *, request_id: str, tenant_id: str) -> dict[str, Any] | None:
        ...

    def get_audit_record(self, *, request_id: str, tenant_id: str) -> dict[str, Any] | None:
        ...

    def create_review(self, record: ReviewRecord) -> None:
        ...

    def create_follow_up(self, record: FollowUpRecord) -> None:
        ...

    def create_evidence(self, record: EvidenceRecord) -> None:
        ...

    def get_evidence(self, *, request_id: str, tenant_id: str) -> list[dict[str, Any]]:
        ...

    def get_latest_audit_record_for_tenant(self, *, tenant_id: str) -> dict[str, Any] | None:
        ...

    def list_audit_records_for_tenant(
        self, *, tenant_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Return the tenant's audit records in write order (oldest first).

        This is what makes the persisted trail *checkable*: the records carry
        ``envelope_audit_hash``/``envelope_previous_hash``, so a verifier can
        walk them and prove no decision was removed or rewritten. See
        :func:`verify_audit_record_chain`.
        """
        ...


class InMemoryControlPlaneStore:
    """Tenant-scoped in-memory store for development and tests.

    NOT an audit store: every envelope is lost when the process exits. Use
    :class:`SQLiteControlPlaneStore` or :class:`PostgresControlPlaneStore`
    for anything whose decisions must be reviewable after the fact.
    """

    durable = False

    def __init__(self) -> None:
        self._decisions: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._audit: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._audit_timeline: list[dict[str, Any]] = []
        self._reviews: list[ReviewRecord] = []
        self._follow_ups: list[FollowUpRecord] = []
        self._evidence: list[EvidenceRecord] = []

    def save_decision(
        self,
        *,
        request_id: str,
        tenant_id: str,
        envelope: dict[str, Any],
        audit_record: dict[str, Any],
    ) -> None:
        key = (tenant_id, request_id)
        self._decisions.setdefault(key, []).append(envelope)
        self._audit.setdefault(key, []).append(audit_record)
        self._audit_timeline.append(dict(audit_record))

    def get_envelope(self, *, request_id: str, tenant_id: str) -> dict[str, Any] | None:
        versions = self._decisions.get((tenant_id, request_id), [])
        return versions[-1] if versions else None

    def get_audit_record(self, *, request_id: str, tenant_id: str) -> dict[str, Any] | None:
        versions = self._audit.get((tenant_id, request_id), [])
        return versions[-1] if versions else None

    def create_review(self, record: ReviewRecord) -> None:
        self._reviews.append(record)

    def create_follow_up(self, record: FollowUpRecord) -> None:
        self._follow_ups.append(record)

    def create_evidence(self, record: EvidenceRecord) -> None:
        self._evidence.append(record)

    def get_evidence(self, *, request_id: str, tenant_id: str) -> list[dict[str, Any]]:
        return [
            {
                "request_id": e.request_id,
                "tenant_id": e.tenant_id,
                "evidence_type": e.evidence_type,
                "payload": e.payload,
                "submitted_by": e.submitted_by,
                "created_at": e.created_at,
            }
            for e in self._evidence
            if e.request_id == request_id and e.tenant_id == tenant_id
        ]

    def get_latest_audit_record_for_tenant(self, *, tenant_id: str) -> dict[str, Any] | None:
        for row in reversed(self._audit_timeline):
            if str(row.get("tenant_id", "")) == tenant_id:
                return dict(row)
        return None

    def list_audit_records_for_tenant(
        self, *, tenant_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        rows = [
            dict(row)
            for row in self._audit_timeline
            if str(row.get("tenant_id", "")) == tenant_id
        ]
        return rows[:limit] if limit is not None else rows


_SQLITE_DDL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS remora_control_plane_decision_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id    TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    audit_json    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_remora_cp_decision_versions_lookup
    ON remora_control_plane_decision_versions (request_id, tenant_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_remora_cp_decision_versions_tenant
    ON remora_control_plane_decision_versions (tenant_id, id);
CREATE TABLE IF NOT EXISTS remora_control_plane_reviews (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id         TEXT NOT NULL,
    tenant_id          TEXT NOT NULL,
    reviewer_id        TEXT NOT NULL,
    decision           TEXT NOT NULL,
    reason             TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    created_at         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS remora_control_plane_followups (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id     TEXT NOT NULL,
    tenant_id      TEXT NOT NULL,
    follow_up_type TEXT NOT NULL,
    requested_by   TEXT,
    payload_json   TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS remora_control_plane_evidence (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id    TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    submitted_by  TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_remora_cp_evidence_lookup
    ON remora_control_plane_evidence (request_id, tenant_id, id);
"""


class SQLiteControlPlaneStore:
    """Tenant-scoped durable single-node control-plane store.

    Same append-only versioning contract as
    :class:`PostgresControlPlaneStore` — every ``save_decision`` inserts a
    new row, reads resolve to the newest version — but backed by a local
    SQLite file, so a single-node deployment (self-hosted pilot, shadow-mode
    run, CI replay) keeps a reviewable envelope trail across restarts
    without operating a database server.

    Writes run inside ``BEGIN IMMEDIATE`` so the insert holds the write lock
    for its duration and concurrent writers serialise rather than interleave.
    Connections are thread-local because SQLite connection objects are not
    safe to share across threads.

    Scope: single node. Multi-process or multi-node deployments must use
    :class:`PostgresControlPlaneStore`; SQLite's file lock does not extend
    across hosts.
    """

    durable = True

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._local = threading.local()
        self._conn().executescript(_SQLITE_DDL)

    def _conn(self):
        import sqlite3

        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=30, isolation_level=None)
            self._local.conn = conn
        return conn

    def _write(self, sql: str, params: tuple[Any, ...]) -> None:
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(sql, params)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    def save_decision(
        self,
        *,
        request_id: str,
        tenant_id: str,
        envelope: dict[str, Any],
        audit_record: dict[str, Any],
    ) -> None:
        self._write(
            """
            INSERT INTO remora_control_plane_decision_versions
                (request_id, tenant_id, created_at, envelope_json, audit_json)
            VALUES (?,?,?,?,?)
            """,
            (
                request_id,
                tenant_id,
                utc_now_iso(),
                json.dumps(envelope, sort_keys=True),
                json.dumps(audit_record, sort_keys=True),
            ),
        )

    def _latest_column(self, column: str, request_id: str, tenant_id: str) -> dict[str, Any] | None:
        row = self._conn().execute(
            f"SELECT {column} FROM remora_control_plane_decision_versions "
            "WHERE request_id = ? AND tenant_id = ? ORDER BY id DESC LIMIT 1",
            (request_id, tenant_id),
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row[0])
        return payload if isinstance(payload, dict) else None

    def get_envelope(self, *, request_id: str, tenant_id: str) -> dict[str, Any] | None:
        return self._latest_column("envelope_json", request_id, tenant_id)

    def get_audit_record(self, *, request_id: str, tenant_id: str) -> dict[str, Any] | None:
        return self._latest_column("audit_json", request_id, tenant_id)

    def create_review(self, record: ReviewRecord) -> None:
        self._write(
            """
            INSERT INTO remora_control_plane_reviews
                (request_id, tenant_id, reviewer_id, decision, reason,
                 evidence_refs_json, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                record.request_id,
                record.tenant_id,
                record.reviewer_id,
                record.decision,
                record.reason,
                json.dumps(record.evidence_refs),
                record.created_at,
            ),
        )

    def create_follow_up(self, record: FollowUpRecord) -> None:
        self._write(
            """
            INSERT INTO remora_control_plane_followups
                (request_id, tenant_id, follow_up_type, requested_by,
                 payload_json, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                record.request_id,
                record.tenant_id,
                record.follow_up_type,
                record.requested_by,
                json.dumps(record.payload, sort_keys=True),
                record.created_at,
            ),
        )

    def create_evidence(self, record: EvidenceRecord) -> None:
        self._write(
            """
            INSERT INTO remora_control_plane_evidence
                (request_id, tenant_id, evidence_type, payload_json,
                 submitted_by, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                record.request_id,
                record.tenant_id,
                record.evidence_type,
                json.dumps(record.payload, sort_keys=True),
                record.submitted_by,
                record.created_at,
            ),
        )

    def get_evidence(self, *, request_id: str, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT evidence_type, payload_json, submitted_by, created_at "
            "FROM remora_control_plane_evidence "
            "WHERE request_id = ? AND tenant_id = ? ORDER BY id ASC",
            (request_id, tenant_id),
        ).fetchall()
        return [
            {
                "request_id": request_id,
                "tenant_id": tenant_id,
                "evidence_type": evidence_type,
                "payload": json.loads(payload_json),
                "submitted_by": submitted_by,
                "created_at": created_at,
            }
            for evidence_type, payload_json, submitted_by, created_at in rows
        ]

    def get_latest_audit_record_for_tenant(self, *, tenant_id: str) -> dict[str, Any] | None:
        row = self._conn().execute(
            "SELECT audit_json FROM remora_control_plane_decision_versions "
            "WHERE tenant_id = ? ORDER BY id DESC LIMIT 1",
            (tenant_id,),
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row[0])
        return payload if isinstance(payload, dict) else None

    def list_audit_records_for_tenant(
        self, *, tenant_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT audit_json FROM remora_control_plane_decision_versions "
            "WHERE tenant_id = ? ORDER BY id ASC"
        )
        params: tuple[Any, ...] = (tenant_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (tenant_id, int(limit))
        rows = self._conn().execute(sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for (audit_json,) in rows:
            payload = json.loads(audit_json)
            if isinstance(payload, dict):
                out.append(payload)
        return out


class PostgresControlPlaneStore:
    """Tenant-scoped PostgreSQL control-plane store.

    Requires `psycopg2` (or `psycopg2-binary`) installed in runtime.
    """

    durable = True

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._ensure_schema()

    def _connect(self):
        import psycopg2  # type: ignore[import-not-found]

        return psycopg2.connect(self._dsn)

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS remora_control_plane_decision_versions (
                        id BIGSERIAL PRIMARY KEY,
                        request_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        envelope_json JSONB NOT NULL,
                        audit_json JSONB NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_remora_cp_decision_versions_lookup
                    ON remora_control_plane_decision_versions (request_id, tenant_id, id DESC)
                    """
                )
                # One-time compatibility migration from legacy upsert table, if present.
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1
                            FROM information_schema.tables
                            WHERE table_name = 'remora_control_plane_decisions'
                        ) THEN
                            INSERT INTO remora_control_plane_decision_versions
                                (request_id, tenant_id, created_at, envelope_json, audit_json)
                            SELECT
                                d.request_id,
                                d.tenant_id,
                                d.created_at,
                                d.envelope_json,
                                d.audit_json
                            FROM remora_control_plane_decisions d
                            WHERE NOT EXISTS (
                                SELECT 1
                                FROM remora_control_plane_decision_versions v
                                WHERE v.request_id = d.request_id
                                  AND v.tenant_id = d.tenant_id
                            );
                        END IF;
                    END
                    $$;
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS remora_control_plane_reviews (
                        id BIGSERIAL PRIMARY KEY,
                        request_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        reviewer_id TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        evidence_refs_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS remora_control_plane_followups (
                        id BIGSERIAL PRIMARY KEY,
                        request_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        follow_up_type TEXT NOT NULL,
                        requested_by TEXT,
                        payload_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS remora_control_plane_evidence (
                        id BIGSERIAL PRIMARY KEY,
                        request_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        evidence_type TEXT NOT NULL,
                        payload_json JSONB NOT NULL,
                        submitted_by TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            conn.commit()
        finally:
            conn.close()

    def save_decision(
        self,
        *,
        request_id: str,
        tenant_id: str,
        envelope: dict[str, Any],
        audit_record: dict[str, Any],
    ) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO remora_control_plane_decision_versions
                        (request_id, tenant_id, envelope_json, audit_json)
                    VALUES (%s, %s, %s::jsonb, %s::jsonb)
                    """,
                    (request_id, tenant_id, json.dumps(envelope), json.dumps(audit_record)),
                )
            conn.commit()
        finally:
            conn.close()

    def get_envelope(self, *, request_id: str, tenant_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT envelope_json
                    FROM remora_control_plane_decision_versions
                    WHERE request_id = %s AND tenant_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (request_id, tenant_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return row[0]
        finally:
            conn.close()

    def get_audit_record(self, *, request_id: str, tenant_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT audit_json
                    FROM remora_control_plane_decision_versions
                    WHERE request_id = %s AND tenant_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (request_id, tenant_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return row[0]
        finally:
            conn.close()

    def create_review(self, record: ReviewRecord) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO remora_control_plane_reviews
                        (request_id, tenant_id, reviewer_id, decision, reason, evidence_refs_json, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        record.request_id,
                        record.tenant_id,
                        record.reviewer_id,
                        record.decision,
                        record.reason,
                        json.dumps(record.evidence_refs),
                        record.created_at,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def create_follow_up(self, record: FollowUpRecord) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO remora_control_plane_followups
                        (request_id, tenant_id, follow_up_type, requested_by, payload_json, created_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        record.request_id,
                        record.tenant_id,
                        record.follow_up_type,
                        record.requested_by,
                        json.dumps(record.payload),
                        record.created_at,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def create_evidence(self, record: EvidenceRecord) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO remora_control_plane_evidence
                        (request_id, tenant_id, evidence_type, payload_json, submitted_by, created_at)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        record.request_id,
                        record.tenant_id,
                        record.evidence_type,
                        json.dumps(record.payload),
                        record.submitted_by,
                        record.created_at,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def get_evidence(self, *, request_id: str, tenant_id: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT evidence_type, payload_json, submitted_by, created_at
                    FROM remora_control_plane_evidence
                    WHERE request_id = %s AND tenant_id = %s
                    ORDER BY id ASC
                    """,
                    (request_id, tenant_id),
                )
                rows = cur.fetchall() or []
                out: list[dict[str, Any]] = []
                for evidence_type, payload_json, submitted_by, created_at in rows:
                    out.append(
                        {
                            "request_id": request_id,
                            "tenant_id": tenant_id,
                            "evidence_type": evidence_type,
                            "payload": payload_json,
                            "submitted_by": submitted_by,
                            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
                        }
                    )
                return out
        finally:
            conn.close()

    def get_latest_audit_record_for_tenant(self, *, tenant_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT audit_json
                    FROM remora_control_plane_decision_versions
                    WHERE tenant_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (tenant_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                payload = row[0]
                return payload if isinstance(payload, dict) else None
        finally:
            conn.close()

    def list_audit_records_for_tenant(
        self, *, tenant_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                sql = """
                    SELECT audit_json
                    FROM remora_control_plane_decision_versions
                    WHERE tenant_id = %s
                    ORDER BY id ASC
                """
                params: tuple[Any, ...] = (tenant_id,)
                if limit is not None:
                    sql += " LIMIT %s"
                    params = (tenant_id, int(limit))
                cur.execute(sql, params)
                rows = cur.fetchall() or []
                return [row[0] for row in rows if isinstance(row[0], dict)]
        finally:
            conn.close()


def verify_audit_record_chain(records: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Verify hash-chain linkage across a tenant's persisted audit records.

    Each record written by the REST path carries ``envelope_audit_hash``
    (this decision) and ``envelope_previous_hash`` (the tenant's previous
    decision). Walking them in write order proves that no decision was
    deleted from, or spliced into, the middle of the trail.

    Scope of the guarantee: this checks *linkage*, not the envelope payload
    itself. Recomputing an envelope's own hash from its payload is
    ``remora.shadow.replay.verify_envelope_hash_chain`` for shadow-mode
    envelopes; the REST envelope hash is produced by the API and covered by
    ``envelope_signature`` when ``REMORA_ENVELOPE_SIGNING_KEY`` is set.

    Returns ``(ok, breaks)`` where ``breaks`` names every failure found, so
    a broken trail reports all damage instead of only the first break.
    """
    breaks: list[str] = []
    expected_previous: str | None = None

    for index, record in enumerate(records):
        current = record.get("envelope_audit_hash")
        previous = record.get("envelope_previous_hash")
        request_id = record.get("request_id", f"index-{index}")

        if not isinstance(current, str) or not current.strip():
            breaks.append(f"{request_id}: missing envelope_audit_hash")
            # The cursor cannot advance across a record with no hash; a later
            # link would be checked against the wrong predecessor.
            expected_previous = None
            continue

        if index == 0:
            # First record for the tenant: any predecessor is accepted, since
            # the store may have been opened mid-stream (e.g. retention trim).
            expected_previous = current
            continue

        if previous != expected_previous:
            breaks.append(
                f"{request_id}: previous_hash {previous!r} does not link to "
                f"predecessor {expected_previous!r}"
            )
        expected_previous = current

    return (not breaks), breaks


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
