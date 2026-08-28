# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Persistence package.

Historically this was the flat module holding the disk-based oracle
response cache (Store/CachedOracle); that content lives on below so every
existing `from remora.persistence import CachedOracle` keeps working.
Execution-layer adapters (issue #241) live in submodules with no HTTP
knowledge, e.g. remora.persistence.execution_state.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Optional
from remora.core import Oracle, OracleResponse

class Store:
    """Simple JSON file cache."""
    def __init__(self, path: str = ".remora_cache.json"):
        self.path = Path(path)
        self._data: dict = {}
        if self.path.exists():
            try: self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError): pass  # an unreadable cache starts empty; a failed write loses only the cache
    def get(self, key: str) -> Optional[dict]: return self._data.get(key)
    def set(self, key: str, value: dict) -> None:
        self._data[key] = value
        try: self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError: pass  # an unreadable cache starts empty; a failed write loses only the cache
    def __len__(self) -> int: return len(self._data)

class CachedOracle(Oracle):
    """Wraps an Oracle and caches responses to disk by SHA-256(provider+prompt)."""
    def __init__(self, inner: Oracle, store: Store):
        self._inner = inner; self._store = store
    @property
    def name(self) -> str: return self._inner.name
    def _call(self, prompt: str) -> tuple[str, float, float]:
        return self._inner._call(prompt)
    def ask(self, prompt: str) -> OracleResponse:
        key = hashlib.sha256(f"{self.name}::{prompt}".encode()).hexdigest()[:32]
        cached = self._store.get(key)
        if cached: return OracleResponse(**cached)
        response = self._inner.ask(prompt)
        self._store.set(key, {"provider": response.provider, "raw_text": response.raw_text,
            "extracted": response.extracted, "cost_usd": response.cost_usd,
            "latency_ms": response.latency_ms, "error": response.error})
        return response
