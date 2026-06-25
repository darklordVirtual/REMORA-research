# Author: Stian Skogbrott
# License: Apache-2.0
"""Filesystem storage adapter — default for development and on-premises deployment."""
from __future__ import annotations

from pathlib import Path

from remora.adapters.storage import StorageAdapter


class FilesystemStorage(StorageAdapter):
    """Store artifacts as files on the local filesystem."""

    def __init__(self, base_dir: str = "artifacts"):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes) -> None:
        path = self._base / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes | None:
        path = self._base / key
        if path.exists():
            return path.read_bytes()
        return None

    def exists(self, key: str) -> bool:
        return (self._base / key).exists()

    def list_keys(self, prefix: str = "") -> list[str]:
        results = []
        search_dir = self._base / prefix if prefix else self._base
        if search_dir.exists():
            for p in search_dir.rglob("*"):
                if p.is_file():
                    results.append(str(p.relative_to(self._base)))
        return sorted(results)
