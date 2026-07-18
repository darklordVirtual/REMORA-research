# Author: Stian Skogbrott
# License: Apache-2.0
"""Atomic per-tenant audit chain (REM-034).

External review finding: the REST path produced individually signed records
whose envelope hash did not cover ``previous_hash``, with predecessor lookup
and insert as separate unserialised operations — concurrent writes could
fork the chain, and no verifier existed.

This module is the fix, as a storage-agnostic core:

- ``entry_hash = SHA256(previous_hash || canonical(payload) || tenant_id
  || sequence_no || timestamp)`` — the predecessor, tenant, position and
  time are all inside the hash, so none can be rewritten without breaking
  every later entry.
- ``append()`` is atomic: predecessor read, sequence assignment and insert
  happen under one lock (in-process) — two concurrent appends can never
  read the same predecessor. The equivalent Postgres discipline is shipped
  as :data:`POSTGRES_DDL` (per-tenant head row + ``SELECT ... FOR UPDATE``
  + unique ``(tenant_id, sequence_no)``); an adapter implementing
  ``append`` inside one transaction satisfies the same contract.
- ``verify()`` recomputes the whole chain per tenant and reports every
  break (used at export and startup).
- Optional HMAC signature per entry (``REMORA_AUDIT_SIGNING_KEY``) over the
  entry hash.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

_GENESIS = "0" * 64
_ENV_KEY = "REMORA_AUDIT_SIGNING_KEY"

POSTGRES_DDL = """
-- REM-034: atomic per-tenant audit chain (deployment adapter).
CREATE TABLE IF NOT EXISTS tenant_chain_head (
    tenant_id     TEXT PRIMARY KEY,
    head_hash     TEXT NOT NULL,
    head_sequence BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS tenant_chain_entry (
    tenant_id     TEXT   NOT NULL,
    sequence_no   BIGINT NOT NULL,
    timestamp     TEXT   NOT NULL,
    payload       JSONB  NOT NULL,
    previous_hash TEXT   NOT NULL,
    entry_hash    TEXT   NOT NULL,
    signature     TEXT   NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_id, sequence_no)
);
-- append() MUST run in one transaction:
--   SELECT head_hash, head_sequence FROM tenant_chain_head
--     WHERE tenant_id = $1 FOR UPDATE;
--   INSERT INTO tenant_chain_entry ...;
--   UPDATE tenant_chain_head SET head_hash = $h, head_sequence = $s ...;
"""


def _canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_entry_hash(
    previous_hash: str,
    payload: dict[str, Any],
    tenant_id: str,
    sequence_no: int,
    timestamp: str,
) -> str:
    preimage = (
        previous_hash
        + _canonical(payload)
        + tenant_id
        + str(sequence_no)
        + timestamp
    )
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChainEntry:
    tenant_id: str
    sequence_no: int
    timestamp: str
    payload: dict[str, Any]
    previous_hash: str
    entry_hash: str
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TenantAuditChain:
    """In-process reference implementation with atomic appends."""

    def __init__(self, now_fn: Callable[[], datetime] | None = None) -> None:
        self._entries: dict[str, list[ChainEntry]] = {}
        self._lock = threading.Lock()
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def append(self, tenant_id: str, payload: dict[str, Any]) -> ChainEntry:
        """Atomic read-predecessor + insert: fork-free by construction."""
        with self._lock:
            chain = self._entries.setdefault(tenant_id, [])
            previous_hash = chain[-1].entry_hash if chain else _GENESIS
            sequence_no = len(chain)
            timestamp = self._now_fn().isoformat()
            entry_hash = compute_entry_hash(
                previous_hash, payload, tenant_id, sequence_no, timestamp
            )
            key = os.environ.get(_ENV_KEY, "").strip().encode()
            signature = (
                hmac.new(key, entry_hash.encode(), hashlib.sha256).hexdigest()
                if key else ""
            )
            entry = ChainEntry(
                tenant_id=tenant_id,
                sequence_no=sequence_no,
                timestamp=timestamp,
                payload=payload,
                previous_hash=previous_hash,
                entry_hash=entry_hash,
                signature=signature,
            )
            chain.append(entry)
            return entry

    def entries(self, tenant_id: str) -> tuple[ChainEntry, ...]:
        with self._lock:
            return tuple(self._entries.get(tenant_id, ()))

    def verify(self, tenant_id: str) -> tuple[bool, list[str]]:
        """Recompute one tenant's chain; report every break (complete set)."""
        problems: list[str] = []
        previous_hash = _GENESIS
        key = os.environ.get(_ENV_KEY, "").strip().encode()
        for i, entry in enumerate(self.entries(tenant_id)):
            if entry.sequence_no != i:
                problems.append(f"sequence_gap_at:{i}")
            if entry.previous_hash != previous_hash:
                problems.append(f"chain_break_at:{i}")
            expected = compute_entry_hash(
                entry.previous_hash, entry.payload, entry.tenant_id,
                entry.sequence_no, entry.timestamp,
            )
            if expected != entry.entry_hash:
                problems.append(f"hash_mismatch_at:{i}")
            if key and entry.signature:
                want = hmac.new(key, entry.entry_hash.encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(want, entry.signature):
                    problems.append(f"signature_mismatch_at:{i}")
            previous_hash = entry.entry_hash
        return (not problems, problems)

    def verify_all(self) -> tuple[bool, dict[str, list[str]]]:
        report = {t: self.verify(t)[1] for t in list(self._entries)}
        report = {t: p for t, p in report.items() if p}
        return (not report, report)
