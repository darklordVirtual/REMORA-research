# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Audit adapters — platform-agnostic decision audit trail."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AuditEntry:
    """A single audit record for a REMORA decision."""
    timestamp: datetime
    question_hash: str
    action: str
    trust_score: float
    phase: str
    oracle_count: int
    verdict: str
    policy_version: str
    metadata: dict[str, str]


@runtime_checkable
class AuditSink(Protocol):
    """Structural contract for an audit trail.

    :class:`AuditAdapter` is the nominal base class this repository's own
    adapters inherit. ``AuditSink`` is the same contract expressed
    structurally, so a deployment can hand REMORA an existing audit object —
    a wrapper around its own ledger, a queue client, a compliance SDK —
    without inheriting from a REMORA class. Anything satisfying this
    interface is acceptable; ``AuditAdapter`` satisfies it by construction.

    The append-only rule is part of the contract and cannot be expressed in
    the type: implementations must not allow deletion or modification of
    existing entries.
    """

    def append(self, entry: AuditEntry) -> None:
        """Append an audit entry to the trail."""
        ...

    def query(
        self,
        *,
        since: datetime | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query audit entries with optional filters."""
        ...


class AuditAdapter(ABC):
    """Abstract base class for audit trail adapters.

    All audit entries are append-only. Implementations must not
    allow deletion or modification of existing entries.
    """

    @abstractmethod
    def append(self, entry: AuditEntry) -> None:
        """Append an audit entry to the trail."""
        ...

    @abstractmethod
    def query(self, *, since: datetime | None = None, action: str | None = None, limit: int = 100) -> list[AuditEntry]:
        """Query audit entries with optional filters."""
        ...
