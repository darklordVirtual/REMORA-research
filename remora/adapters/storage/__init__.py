# Author: Stian Skogbrott
# License: Apache-2.0
"""Storage adapters — platform-agnostic artifact and evidence storage."""
from __future__ import annotations

from abc import ABC, abstractmethod

from remora.adapters.storage.control_plane import (
    ControlPlaneStore,
    EvidenceRecord,
    FollowUpRecord,
    InMemoryControlPlaneStore,
    PostgresControlPlaneStore,
    ReviewRecord,
)


class StorageAdapter(ABC):
    """Abstract base class for storage adapters.

    Provides a key-value interface for storing and retrieving
    artifacts, evidence, and results.
    """

    @abstractmethod
    def put(self, key: str, data: bytes) -> None:
        """Store data under the given key."""
        ...

    @abstractmethod
    def get(self, key: str) -> bytes | None:
        """Retrieve data by key. Returns None if not found."""
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a key exists."""
        ...

    @abstractmethod
    def list_keys(self, prefix: str = "") -> list[str]:
        """List keys matching the given prefix."""
        ...


__all__ = [
    "StorageAdapter",
    "ControlPlaneStore",
    "InMemoryControlPlaneStore",
    "PostgresControlPlaneStore",
    "EvidenceRecord",
    "ReviewRecord",
    "FollowUpRecord",
]
