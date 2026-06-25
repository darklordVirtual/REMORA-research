# Author: Stian Skogbrott
# License: Apache-2.0
"""PostgreSQL audit adapter — production-grade append-only audit trail.

Uses the schema defined in enterprise/audit-ledger-schema.sql.

Requirements:
    pip install psycopg2-binary  (or psycopg2 for production)
"""
from __future__ import annotations

import json
from datetime import datetime

from remora.adapters.audit import AuditAdapter, AuditEntry


class PostgresAudit(AuditAdapter):
    """Append-only audit trail backed by PostgreSQL.

    Parameters
    ----------
    dsn:
        PostgreSQL connection string (e.g. 'postgresql://remora:password@localhost/remora_audit').
    """

    def __init__(self, dsn: str):
        self._dsn = dsn

    def _connect(self):
        import psycopg2
        return psycopg2.connect(self._dsn)

    def append(self, entry: AuditEntry) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO audit_log
                       (timestamp, question_hash, action, trust_score, phase,
                        oracle_count, verdict, policy_version, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        entry.timestamp,
                        entry.question_hash,
                        entry.action,
                        entry.trust_score,
                        entry.phase,
                        entry.oracle_count,
                        entry.verdict,
                        entry.policy_version,
                        json.dumps(entry.metadata),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def query(self, *, since: datetime | None = None, action: str | None = None, limit: int = 100) -> list[AuditEntry]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                conditions = []
                params: list = []
                if since:
                    conditions.append("timestamp >= %s")
                    params.append(since)
                if action:
                    conditions.append("action = %s")
                    params.append(action)
                where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                cur.execute(
                    f"SELECT timestamp, question_hash, action, trust_score, phase, "
                    f"oracle_count, verdict, policy_version, metadata "
                    f"FROM audit_log {where} ORDER BY timestamp DESC LIMIT %s",
                    params + [limit],
                )
                return [
                    AuditEntry(
                        timestamp=row[0],
                        question_hash=row[1],
                        action=row[2],
                        trust_score=float(row[3]),
                        phase=row[4],
                        oracle_count=row[5],
                        verdict=row[6],
                        policy_version=row[7],
                        metadata=json.loads(row[8]) if row[8] else {},
                    )
                    for row in cur.fetchall()
                ]
        finally:
            conn.close()
