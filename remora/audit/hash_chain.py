"""Cryptographic hash-chain for REMORA audit entries.

Provides tamper-DETECTABLE ledger integrity by linking each audit entry
to the previous entry via SHA-256.  Any modification to a historical
entry invalidates the chain from that point forward — provided the
genesis hash or a recent snapshot is held externally.

This is a **structural** integrity layer — it detects tampering but does
NOT prevent it.  An adversary with write access to the audit store can
rewrite the entire chain and recompute valid hashes, so the chain alone
does not provide tamper resistance.  For append-only (WORM) storage that
resists rewriting, combine with:

  * WORM media or object storage with immutability policy
  * A Transparency Log (Trillian / Sigstore / Certificate Transparency)
  * A Trusted Timestamp Authority (RFC 3161)
  * Regular external publication of Merkle roots (see ``remora.audit.merkle``)
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class HashChainEntry:
    """One link in the audit hash chain.

    Attributes
    ----------
    timestamp:
        ISO-8601 timestamp of the decision.
    question_hash:
        SHA-256 hash of the question text.
    action:
        Decision action (accept, verify, abstain, escalate).
    trust_score:
        Final trust score.
    phase:
        Thermodynamic phase.
    previous_hash:
        Hash of the previous entry in the chain.  ``None`` for genesis.
    entry_hash:
        SHA-256 of ``previous_hash || canonical_json(data)``.
    metadata:
        Additional fields (policy_version, etc.).
    """

    timestamp: str
    question_hash: str
    action: str
    trust_score: float
    phase: str
    previous_hash: str | None
    entry_hash: str
    metadata: dict[str, Any]

    def verify(self, previous: "HashChainEntry | None" = None) -> bool:
        """Check that this entry's hash is correctly computed.

        If *previous* is supplied, also verify the previous_hash link.
        """
        recomputed = _compute_hash(
            timestamp=self.timestamp,
            question_hash=self.question_hash,
            action=self.action,
            trust_score=self.trust_score,
            phase=self.phase,
            previous_hash=self.previous_hash,
            metadata=self.metadata,
        )
        if recomputed != self.entry_hash:
            return False
        if previous is not None and self.previous_hash != previous.entry_hash:
            return False
        return True


def _canonical_json(data: dict[str, Any]) -> str:
    """Deterministic JSON for hashing (sorted keys, no whitespace)."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _compute_hash(
    *,
    timestamp: str,
    question_hash: str,
    action: str,
    trust_score: float,
    phase: str,
    previous_hash: str | None,
    metadata: dict[str, Any],
) -> str:
    """Compute the SHA-256 hash for one chain entry."""
    payload = {
        "timestamp": timestamp,
        "question_hash": question_hash,
        "action": action,
        "trust_score": trust_score,
        "phase": phase,
        "metadata": metadata,
    }
    body = _canonical_json(payload)
    preimage = (previous_hash or "") + body
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


class AuditHashChain:
    """Build and verify a hash-linked audit trail.

    Usage::

        chain = AuditHashChain()
        entry1 = chain.append(...)
        entry2 = chain.append(...)
        assert chain.verify()
    """

    def __init__(self) -> None:
        self._entries: list[HashChainEntry] = []
        # Serialise append() so concurrent writers cannot both read the same
        # chain head and fork the chain (external security audit finding: the
        # in-memory chain had no concurrency control). This makes the in-process
        # chain linear under threads; a multi-process / durable deployment must
        # additionally use a transactional per-tenant sequence — see
        # docs/assurance/ai_assisted_adversarial_security_review_v1.md.
        self._lock = threading.Lock()

    def append(
        self,
        *,
        timestamp: str | datetime,
        question_hash: str,
        action: str,
        trust_score: float,
        phase: str,
        metadata: dict[str, Any] | None = None,
    ) -> HashChainEntry:
        """Append a new entry and return it. Thread-safe (serialised)."""
        if isinstance(timestamp, datetime):
            timestamp = timestamp.isoformat()
        with self._lock:
            previous_hash = self._entries[-1].entry_hash if self._entries else None
            entry_hash = _compute_hash(
                timestamp=timestamp,
                question_hash=question_hash,
                action=action,
                trust_score=trust_score,
                phase=phase,
                previous_hash=previous_hash,
                metadata=metadata or {},
            )
            entry = HashChainEntry(
                timestamp=timestamp,
                question_hash=question_hash,
                action=action,
                trust_score=trust_score,
                phase=phase,
                previous_hash=previous_hash,
                entry_hash=entry_hash,
                metadata=metadata or {},
            )
            self._entries.append(entry)
            return entry

    def verify(self) -> bool:
        """Verify the entire chain.  Returns ``False`` on any break."""
        for i, entry in enumerate(self._entries):
            prev = self._entries[i - 1] if i > 0 else None
            if not entry.verify(previous=prev):
                return False
        return True

    def entries(self) -> list[HashChainEntry]:
        """Return an immutable view of the chain."""
        return list(self._entries)

    def to_dicts(self) -> list[dict[str, Any]]:
        """Serialise the chain to a list of plain dicts."""
        return [asdict(e) for e in self._entries]
