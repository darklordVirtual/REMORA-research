# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""At most one settled effect verdict per dispatch, enforced atomically.

The first implementation read the proposal's existing receipts and then
appended. Two receipts arriving concurrently both read "no settled verdict yet"
and both appended, so the uniqueness the rule depends on held only when nothing
raced. That is the same read-then-write shape the lease nonce ledger exists to
avoid, and it fails the same way.

Uniqueness comes from the database here, not from application logic: a
composite primary key on ``(tenant_id, dispatch_id)``, so exactly one caller
wins an INSERT and the loser is told so. Deliberately the same shape as
``remora.enforcement.nonce_store`` -- one narrow method, three backends, fail
closed -- because a second bespoke ledger would be a second thing to get right.

What is settled and what is not
-------------------------------
Only TERMINAL verdicts take the slot. UNOBSERVABLE and VERIFIER_FAILED mean
"we do not know yet", and a later observation resolving one of them is how an
unknown gets closed honestly; claiming the slot for them would freeze every
timed-out read as permanently unresolvable.
"""
from __future__ import annotations

import threading
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "EffectReceiptLedger",
    "EffectReceiptLedgerUnavailable",
    "DurableEffectReceiptLedger",
    "InMemoryEffectReceiptLedger",
]

_CREATE = (
    "CREATE TABLE IF NOT EXISTS effect_receipt_settled ("
    "tenant_id TEXT NOT NULL, dispatch_id TEXT NOT NULL, "
    "status TEXT NOT NULL, settled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
    "PRIMARY KEY (tenant_id, dispatch_id))"
)


class EffectReceiptLedgerUnavailable(RuntimeError):
    """The ledger could not answer.

    Distinct from "already settled". Unreachable never means unsettled:
    assuming so is how two terminal verdicts get recorded for one dispatch.
    """


@runtime_checkable
class EffectReceiptLedger(Protocol):
    def try_settle(self, dispatch_id: str, *, tenant_id: str,
                   status: str) -> bool:
        """True exactly once per (tenant, dispatch); False if already settled.

        Raises ``EffectReceiptLedgerUnavailable`` when the outcome is unknown.
        Never returns False to mean "I could not tell".
        """
        ...


class InMemoryEffectReceiptLedger:
    """Process-local, with the durable ledger's semantics.

    For library and research use. Not a fallback for a durable backend that
    failed -- falling back here on an outage would reintroduce the double-settle
    it exists to prevent.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._settled: set[tuple[str, str]] = set()

    def try_settle(self, dispatch_id: str, *, tenant_id: str,
                   status: str) -> bool:
        key = (tenant_id, dispatch_id)
        with self._lock:
            if key in self._settled:
                return False
            self._settled.add(key)
            return True


class DurableEffectReceiptLedger:
    """Settled-verdict uniqueness over REMORA's existing durable backends."""

    def __init__(self, *, dsn: str = "", db_path: str = "",
                 state_endpoint: str = "") -> None:
        if not (dsn or db_path or state_endpoint):
            raise ValueError(
                "DurableEffectReceiptLedger needs one of dsn, db_path or "
                "state_endpoint; an unconfigured durable ledger is an "
                "in-memory ledger wearing the durable name")
        self._dsn = dsn
        self._db_path = db_path
        self._state_endpoint = state_endpoint
        self._ready = False

    def _connect(self) -> Any:
        if self._dsn:
            import psycopg
            return psycopg.connect(self._dsn)
        if self._db_path:
            import sqlite3
            return sqlite3.connect(self._db_path)
        from remora.persistence import d1_connection
        return d1_connection.connect()

    def _placeholder(self) -> str:
        return "%s" if self._dsn else "?"

    @staticmethod
    def _is_duplicate(exc: BaseException) -> bool:
        text = str(exc).lower()
        return ("unique" in text or "duplicate key" in text
                or "primary key" in text or "constraint failed" in text)

    def _ensure_table(self, conn: Any) -> None:
        if self._ready:
            return
        conn.execute(_CREATE)
        commit = getattr(conn, "commit", None)
        if commit is not None:
            commit()
        self._ready = True

    def try_settle(self, dispatch_id: str, *, tenant_id: str,
                   status: str) -> bool:
        if not dispatch_id:
            raise ValueError("refusing to settle an empty dispatch id")
        if not tenant_id:
            raise ValueError("refusing to settle without a tenant scope")
        ph = self._placeholder()
        sql = (f"INSERT INTO effect_receipt_settled "
               f"(tenant_id, dispatch_id, status) VALUES ({ph}, {ph}, {ph})")
        try:
            with self._connect() as conn:
                self._ensure_table(conn)
                try:
                    conn.execute(sql, (tenant_id, dispatch_id, status))
                    commit = getattr(conn, "commit", None)
                    if commit is not None:
                        commit()
                except Exception as exc:  # noqa: BLE001 - re-raised below
                    if self._is_duplicate(exc):
                        return False
                    raise
        except EffectReceiptLedgerUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            if self._is_duplicate(exc):
                return False
            raise EffectReceiptLedgerUnavailable(
                f"effect receipt ledger unreachable: {exc}") from exc
        return True
