# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""WS1-M4 admission: the checks that run inside the admission transaction (M4.1c).

The re-gate proves a call's preconditions at its own instant. Admission
re-checks what that proof depends on at the instant the grant is spent, inside
the transaction that spends it and records the dispatch intent
(docs/architecture/ADR-ws1-m4-admission-topology.md, decisions 1 to 4):

1. ``before_regate`` reads the authority epochs of every subject the tool's
   evidence can come from, before the re-gate's lookups run, without a lock.
2. ``check`` runs inside the open transaction: it builds the receipts from the
   re-gate's composition record and those epochs, reads the database instant
   once, reads the current epochs under lock, and returns
   :func:`~remora.verification.receipts.admission_refusal`'s answer.

The caller consumes the grant and records the intent on the same connection
only when ``check`` returns no reason, and the transaction commits all of it
or none of it. Nothing here calls the network or a monitor.

Postgres and SQLite only. A D1 deployment is refused when this is built
(decision 5); the server does not build it without a declared clock skew.

The epoch store is passed in (``remora.governance.authority_epochs`` on the
server), because the WS1 library imports no authority module. Any failure to
read it refuses: an epoch that could not be read is never taken as current.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from remora.verification.receipts import (
    MAX_CLOCK_SKEW_MS,
    admission_refusal,
    receipt_set_digest,
    receipts_from_record,
)

__all__ = ["EpochReader", "Ws1Admission", "database_now_ms"]

_PG_NOW = "SELECT CAST(EXTRACT(EPOCH FROM clock_timestamp()) * 1000 AS BIGINT)"
_SQLITE_NOW = "SELECT CAST(ROUND((julianday('now') - 2440587.5) * 86400000) AS INTEGER)"


def database_now_ms(connection: Any, *, postgres: bool) -> int:
    """The database's own instant in epoch ms, read once per admission."""
    row = connection.execute(_PG_NOW if postgres else _SQLITE_NOW).fetchone()
    return int(row[0])


class EpochReader(Protocol):
    """``AuthorityEpochs.read``: ``{subject: (epoch, revoked)}``."""

    def read(self, subject_keys: Iterable[str], *, tenant_id: str,
             lock: bool = False) -> dict[str, tuple[int, bool]]: ...


@dataclass(frozen=True)
class Ws1Admission:
    """The admission checks for one deployment. Built by the server, not the request."""

    epochs: EpochReader
    max_clock_skew_ms: int
    postgres: bool
    #: Test seam: the database instant. Defaults to :func:`database_now_ms`.
    clock: Callable[[Any], int] | None = None

    def __post_init__(self) -> None:
        if (isinstance(self.max_clock_skew_ms, bool)
                or not isinstance(self.max_clock_skew_ms, int)
                or not 0 <= self.max_clock_skew_ms <= MAX_CLOCK_SKEW_MS):
            raise ValueError(
                f"max_clock_skew_ms must be an int from 0 to {MAX_CLOCK_SKEW_MS}")

    def before_regate(self, gate: Any, *, tenant: str, tool_name: str
                      ) -> tuple[dict[str, int] | None, str]:
        """``(epochs, "")`` read before the lookups, or ``(None, reason)``."""
        try:
            read = self.epochs.read(gate.subjects_for_tool(tool_name), tenant_id=tenant)
        except Exception:  # unreachable or unreadable: refuse, never assume epoch 0
            return None, "authority_epochs_unavailable"
        return {subject: epoch for subject, (epoch, _) in read.items()}, ""

    def check(self, connection: Any, *, tenant: str, outcome: Any,
              epochs_before: Mapping[str, int]) -> tuple[str | None, dict[str, Any]]:
        """``(reason, facts)`` inside the admission transaction; reason None admits.

        ``facts`` is what the admission audit event records: the database
        instant, the receipt set's digest and the epochs read under lock.
        """
        if connection is None:
            return "admission_backend_unavailable", {}
        record = getattr(outcome, "record", None)
        if record is None or not outcome.binding_hash:
            return "evidence_receipt_missing", {}
        try:
            receipts = receipts_from_record(
                record, tenant_id=tenant, binding_hash=outcome.binding_hash,
                subject_of=outcome.subjects, epochs=epochs_before)
        except ValueError:
            return "evidence_receipt_unbuildable", {}
        now_ms = (self.clock(connection) if self.clock is not None
                  else database_now_ms(connection, postgres=self.postgres))
        try:
            current = self.epochs.read({r.subject_key for r in receipts},
                                       tenant_id=tenant, lock=True)
        except Exception:  # as above, under lock inside the transaction
            return "authority_epochs_unavailable", {}
        digest = receipt_set_digest(receipts)
        facts = {"db_now_ms": now_ms, "receipt_set_digest": digest,
                 "receipt_count": len(receipts),
                 "max_clock_skew_ms": self.max_clock_skew_ms,
                 "authority_epochs": {k: e for k, (e, _) in sorted(current.items())}}
        reason = admission_refusal(
            receipts, tenant_id=tenant, binding_hash=outcome.binding_hash,
            expected_set_digest=digest,
            required_preconditions=outcome.required_preconditions,
            now_ms=now_ms, max_clock_skew_ms=self.max_clock_skew_ms, epochs=current)
        return reason, facts
