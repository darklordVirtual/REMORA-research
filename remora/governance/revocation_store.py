# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Durable principal revocation for the execution re-gate.

``ReviewQueue`` kept revoked principals in a ``dict`` on the instance, and
``servers/execution_api.py`` builds one ``ReviewQueue`` per tenant per
*process*. A revocation therefore reached the worker that served the HTTP
call and no other, and did not survive a restart. The queue appended a
``principal_revoked`` event to the tenant chain either way, so the audit
record showed a revocation that enforcement had already forgotten. An
after-the-fact review of that deployment reads correct.

This is the third occurrence of one defect class. The consumed-jti ledger
(#350) and the lease nonce ledger (``remora/enforcement/nonce_store.py``)
were the first two: a durable backend the deployment already runs, that one
component learned to use and another did not. The strict runtime profile
already requires ``REMORA_PG_DSN`` or ``REMORA_CHAIN_DB``
(``remora/toolcall/runtime_profile.py``), so nothing new has to be
configured here. The store was present. Revocation simply never read it.

Three required semantics, each with a test:

durable
    a restart, a replacement container, or a second worker does not restore
    the authority of a revoked principal.
fail closed
    an unreachable store raises ``RevocationStoreUnavailable``. Unknown is
    never reported as "not revoked": that would turn a transient outage into
    a way around revocation, which is the hole this module closes. Nor is it
    reported as "revoked" — see the exception's docstring.
tenant scoped
    the primary key is (tenant_id, principal). Revoking a principal in
    tenant A says nothing about the same name in tenant B.
"""
from __future__ import annotations

import threading
from typing import Any, Protocol, runtime_checkable

from remora.errors import RemoraError

__all__ = [
    "DurableRevocationStore",
    "InMemoryRevocationStore",
    "RevocationStore",
    "RevocationStoreUnavailable",
]

#: Composite primary key, so tenant isolation is enforced by the store rather
#: than by every caller remembering to prefix.
_CREATE = (
    "CREATE TABLE IF NOT EXISTS principal_revocations ("
    "tenant_id TEXT NOT NULL, principal TEXT NOT NULL, "
    "reason TEXT NOT NULL DEFAULT '', "
    "revoked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
    "PRIMARY KEY (tenant_id, principal))"
)


class RevocationStoreUnavailable(RemoraError, RuntimeError):
    """The store could not be reached or could not answer.

    Deliberately distinct from both answers it sits between.

    Reporting unavailable as "not revoked" lets a withdrawn approver keep
    executing for as long as the outage lasts, which is the failure this
    module exists to prevent.

    Reporting it as "revoked" is wrong in the other direction, but not
    symmetrically so: it is refused work rather than unauthorised work. This
    is why the re-gate raises instead of voiding the approval. Voiding would
    destroy a valid authorization over a transient fault, exactly as burning
    an unspent nonce would; raising leaves the approval intact for a retry
    once the store answers again.
    """

    code = "revocation_store_unavailable"
    category = "governance"


@runtime_checkable
class RevocationStore(Protocol):
    """Durable, tenant-scoped principal revocation."""

    def revoke(self, principal: str, *, tenant_id: str, reason: str = "") -> None:
        """Record that ``principal`` no longer holds authority in this tenant.

        Idempotent: revoking twice is not an error. Raises
        ``RevocationStoreUnavailable`` if the outcome is unknown, so a caller
        is never told a revocation took effect when it may not have.
        """
        ...

    def is_revoked(self, principal: str, *, tenant_id: str) -> bool:
        """Whether ``principal`` is revoked in this tenant.

        Raises ``RevocationStoreUnavailable`` if the answer is unknown. Never
        returns False to mean "I could not tell".
        """
        ...


class InMemoryRevocationStore:
    """Process-local store with the durable store's exact semantics.

    For library and research use, and as the control in the durability
    tests: it is the thing whose restart behaviour must differ. It is NOT a
    fallback for a durable backend that failed. Falling back to this on an
    outage would silently reintroduce the window this module closes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._revoked: dict[tuple[str, str], str] = {}

    def revoke(self, principal: str, *, tenant_id: str, reason: str = "") -> None:
        _require_scope(principal, tenant_id)
        with self._lock:
            self._revoked[(tenant_id, principal)] = reason

    def is_revoked(self, principal: str, *, tenant_id: str) -> bool:
        _require_scope(principal, tenant_id)
        with self._lock:
            return (tenant_id, principal) in self._revoked


class DurableRevocationStore:
    """Revocation over REMORA's existing durable state backends.

    Exactly the three the durability guard in ``servers/api.py`` admits, for
    the reason recorded against the nonce ledger: a store the guard accepts
    but the consumer never learned to use is how this defect class keeps
    recurring. Adding a fourth backend to the guard means adding it here.
    """

    def __init__(self, *, dsn: str = "", db_path: str = "",
                 state_endpoint: str = "",
                 connection_provider: Any = None) -> None:
        if not (dsn or db_path or state_endpoint):
            raise ValueError(
                "DurableRevocationStore needs one of dsn, db_path or "
                "state_endpoint; an unconfigured durable store would be an "
                "in-memory store wearing the durable name"
            )
        self._dsn = dsn
        self._db_path = db_path
        from remora.persistence.sqlite_path import refuse_memory_db
        refuse_memory_db(db_path, what="principal revocation store")
        self._state_endpoint = state_endpoint
        #: Returns the caller's in-flight transaction connection, or None.
        #: The re-gate reads this store from *inside* the review-state
        #: transaction, so opening a second connection to the same SQLite
        #: file deadlocks against the writer that is already holding it.
        #: Joining the ambient transaction also makes a revocation written
        #: during one commit atomic with the rest of that commit.
        self._connection_provider = connection_provider
        self._ready = False

    # ── backend plumbing ────────────────────────────────────────────────────

    def _ambient(self) -> Any:
        if self._connection_provider is None:
            return None
        return self._connection_provider()

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

    def _ensure_table(self, conn: Any, *, own_commit: bool = True) -> None:
        if self._ready:
            return
        conn.execute(_CREATE)
        if own_commit:
            commit = getattr(conn, "commit", None)
            if commit is not None:
                commit()
        # Only remember the table on a connection we control. Inside someone
        # else's transaction the DDL is not durable until they commit, and a
        # rollback would leave this instance believing in a table that no
        # longer exists.
        self._ready = own_commit

    # ── the interface ───────────────────────────────────────────────────────

    def revoke(self, principal: str, *, tenant_id: str, reason: str = "") -> None:
        _require_scope(principal, tenant_id)
        # Idempotent by construction: a second revocation of the same
        # principal must not raise, and must not overwrite the first reason,
        # which is the one the audit chain already recorded.
        sql = (
            "INSERT INTO principal_revocations (tenant_id, principal, reason) "
            f"VALUES ({self._placeholder()}, {self._placeholder()}, "
            f"{self._placeholder()})"
        )
        def _write(conn: Any, *, own_commit: bool) -> None:
            self._ensure_table(conn, own_commit=own_commit)
            try:
                conn.execute(sql, (tenant_id, principal, reason))
            except Exception as exc:  # noqa: BLE001 — re-raised below
                if not _is_duplicate(exc):
                    raise
            if own_commit:
                commit = getattr(conn, "commit", None)
                if commit is not None:
                    commit()

        try:
            ambient = self._ambient()
            if ambient is not None:
                # The caller's transaction owns the commit. Committing here
                # would publish half of their work.
                _write(ambient, own_commit=False)
            else:
                with self._connect() as conn:
                    _write(conn, own_commit=True)
        except RevocationStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RevocationStoreUnavailable(
                f"principal revocation store unreachable: {exc}"
            ) from exc

    def is_revoked(self, principal: str, *, tenant_id: str) -> bool:
        _require_scope(principal, tenant_id)
        sql = (
            "SELECT 1 AS hit FROM principal_revocations WHERE tenant_id = "
            f"{self._placeholder()} AND principal = {self._placeholder()}"
        )
        try:
            ambient = self._ambient()
            if ambient is not None:
                self._ensure_table(ambient, own_commit=False)
                row = ambient.execute(sql, (tenant_id, principal)).fetchone()
            else:
                with self._connect() as conn:
                    self._ensure_table(conn, own_commit=True)
                    row = conn.execute(sql, (tenant_id, principal)).fetchone()
        except Exception as exc:  # noqa: BLE001
            raise RevocationStoreUnavailable(
                f"principal revocation store unreachable: {exc}"
            ) from exc
        return row is not None


def _require_scope(principal: str, tenant_id: str) -> None:
    if not principal or not principal.strip():
        raise ValueError("revocation requires a principal")
    if not tenant_id or not tenant_id.strip():
        # An empty tenant would put every unattributed principal in one
        # shared namespace, so revoking "alice" anywhere would revoke her
        # everywhere.
        raise ValueError("revocation requires a tenant scope")


def _is_duplicate(exc: BaseException) -> bool:
    """Did this failure mean 'already revoked' rather than 'unknown'?

    Read from the message rather than the exception type because the three
    backends raise three different types, and D1 surfaces the constraint
    violation through its transport error. Anything not recognised as a
    uniqueness violation is treated as unknown, which fails closed.
    """
    text = str(exc).lower()
    return (
        "unique" in text
        or "duplicate key" in text
        or "primary key" in text
        or "constraint failed" in text
    )
