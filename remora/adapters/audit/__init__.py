# Author: Stian Skogbrott
# License: Apache-2.0
"""Audit adapters — platform-agnostic decision audit trail."""
from __future__ import annotations

from abc import ABC, abstractmethod
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
