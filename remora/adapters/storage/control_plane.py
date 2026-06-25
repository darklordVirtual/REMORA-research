# Author: Stian Skogbrott
# License: Apache-2.0
"""Control-plane persistence adapters for REMORA API.

Provides tenant-scoped storage for decision envelopes, audit records,
review decisions, and follow-up workflow events.
"""
from __future__ import annotations

import json
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


class InMemoryControlPlaneStore:
    """Tenant-scoped in-memory store for development and tests."""

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


class PostgresControlPlaneStore:
    """Tenant-scoped PostgreSQL control-plane store.

    Requires `psycopg2` (or `psycopg2-binary`) installed in runtime.
    """

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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
