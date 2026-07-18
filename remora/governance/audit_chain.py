# Author: Stian Skogbrott
# License: Apache-2.0
"""Tamper-evident SHA-256 hash chain for REMORA governance decisions.

Every governance decision produces a DecisionEnvelope. This module chains
those envelopes into a cryptographically-linked sequence where each entry
commits to all prior decisions — making retrospective tampering detectable.

Design
------
Chain entry:   HASH_N = SHA-256(HASH_{N-1} ‖ request_id ‖ gate_outcome ‖ policy_version)
Seal (HMAC):   HMAC-SHA256(secret_key, HASH_N) — binds chain to a signing key

Verification:  replay all entries and check each hash matches the stored value.
               Any tampered entry breaks the chain and is immediately detected.

Usage
-----
    from remora.governance.audit_chain import RemoraAuditChain

    chain = RemoraAuditChain()

    for envelope in envelopes:
        sealed = chain.append(envelope)      # returns sealed envelope
        assert sealed.audit.previous_hash == chain.prev_hash  # type: ignore

    ok, violations = chain.verify()
    assert ok, violations

Signing (optional)::

    import secrets
    chain = RemoraAuditChain(secret_key=secrets.token_bytes(32))
    sealed = chain.append(envelope)
    assert sealed.audit.signature is not None

Persistence::

    chain.export_jsonl("audit_chain.jsonl")
    loaded = RemoraAuditChain.import_jsonl("audit_chain.jsonl")
    ok, _ = loaded.verify()
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from remora.governance.envelope import AuditBlock, DecisionEnvelope

# ---------------------------------------------------------------------------
# Chain entry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChainEntry:
    """One link in the audit chain."""

    index: int
    """Sequential index (1-based)."""
    timestamp: str
    """ISO-8601 UTC timestamp of when the entry was appended."""
    request_id: str
    gate_outcome: str
    policy_version: str
    hash: str
    """SHA-256 of (previous_hash ‖ request_id ‖ gate_outcome ‖ policy_version)."""
    previous_hash: str
    """Hash of the preceding entry (``'0' * 64`` for the genesis entry)."""
    signature: str | None
    """HMAC-SHA256(secret_key, hash) if the chain was created with a secret key."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "request_id": self.request_id,
            "gate_outcome": self.gate_outcome,
            "policy_version": self.policy_version,
            "hash": self.hash,
            "previous_hash": self.previous_hash,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChainEntry:
        return cls(**d)


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------

GENESIS_HASH = "0" * 64


class RemoraAuditChain:
    """Append-only tamper-evident chain of governance decisions.

    Parameters
    ----------
    secret_key:
        Optional 32-byte secret for HMAC-SHA256 signing. When provided,
        every entry receives a ``signature`` that binds the chain to this
        key. Pass ``bytes`` or a hex string.
    """

    def __init__(self, *, secret_key: bytes | str | None = None) -> None:
        self._entries: list[ChainEntry] = []
        self._prev_hash: str = GENESIS_HASH

        if isinstance(secret_key, str):
            secret_key = secret_key.encode("utf-8")
        self._secret: bytes | None = secret_key

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def prev_hash(self) -> str:
        """SHA-256 hash of the most recently appended entry."""
        return self._prev_hash

    @property
    def length(self) -> int:
        """Number of entries in the chain."""
        return len(self._entries)

    def __len__(self) -> int:
        """Number of entries in the chain."""
        return len(self._entries)

    def __iter__(self):
        """Iterate over ChainEntry records in order."""
        return iter(self._entries)

    def append(self, envelope: DecisionEnvelope) -> DecisionEnvelope:
        """Append a governance decision and return the sealed envelope.

        The returned envelope has its ``audit.hash``, ``audit.previous_hash``,
        and (if signed) ``audit.signature`` populated with the chain values.
        The original ``envelope`` is not mutated.

        Parameters
        ----------
        envelope:
            A ``DecisionEnvelope`` to append to the chain.

        Returns
        -------
        DecisionEnvelope
            The same envelope with a sealed ``AuditBlock``.
        """
        request_id = envelope.request.request_id
        gate_outcome = envelope.gate.outcome
        policy_version = envelope.audit.policy_version or "unknown"

        entry_hash = self._compute_hash(
            self._prev_hash, request_id, gate_outcome, policy_version
        )
        signature = self._sign(entry_hash) if self._secret else None
        ts = datetime.now(UTC).isoformat()

        entry = ChainEntry(
            index=len(self._entries) + 1,
            timestamp=ts,
            request_id=request_id,
            gate_outcome=gate_outcome,
            policy_version=policy_version,
            hash=entry_hash,
            previous_hash=self._prev_hash,
            signature=signature,
        )
        self._entries.append(entry)
        self._prev_hash = entry_hash

        # Return a sealed copy of the envelope
        sealed_audit = AuditBlock(
            policy_version=policy_version,
            hash=entry_hash,
            previous_hash=entry.previous_hash,
            signature=signature,
        )
        return DecisionEnvelope(
            request=envelope.request,
            assessment=envelope.assessment,
            gate=envelope.gate,
            reviewer_context=envelope.reviewer_context,
            follow_up=envelope.follow_up,
            history=envelope.history,
            policy_learning=envelope.policy_learning,
            audit=sealed_audit,
        )

    def verify(self) -> tuple[bool, list[str]]:
        """Verify integrity of the entire chain.

        Returns
        -------
        (ok, violations):
            ``ok`` is ``True`` when the chain is intact.
            ``violations`` is a list of human-readable error strings
            (empty when ``ok`` is ``True``).

        Example::

            ok, violations = chain.verify()
            if not ok:
                raise RuntimeError(f"Chain tampered: {violations}")
        """
        violations: list[str] = []
        running_hash = GENESIS_HASH

        for entry in self._entries:
            # Check previous_hash linkage
            if entry.previous_hash != running_hash:
                violations.append(
                    f"[{entry.index}] previous_hash mismatch: "
                    f"expected {running_hash[:16]}… got {entry.previous_hash[:16]}…"
                )

            # Recompute hash
            expected = self._compute_hash(
                entry.previous_hash,
                entry.request_id,
                entry.gate_outcome,
                entry.policy_version,
            )
            if entry.hash != expected:
                violations.append(
                    f"[{entry.index}] hash mismatch: "
                    f"expected {expected[:16]}… got {entry.hash[:16]}…"
                )

            # Verify signature if present
            if entry.signature is not None and self._secret is not None:
                expected_sig = self._sign(entry.hash)
                if not hmac.compare_digest(entry.signature, expected_sig):
                    violations.append(
                        f"[{entry.index}] HMAC signature invalid"
                    )

            running_hash = entry.hash

        return len(violations) == 0, violations

    def export_jsonl(self, path: str | Path) -> None:
        """Write the chain to a JSONL file — one entry per line."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            for entry in self._entries:
                f.write(json.dumps(entry.to_dict(), sort_keys=True) + "\n")

    @classmethod
    def import_jsonl(
        cls,
        path: str | Path,
        *,
        secret_key: bytes | str | None = None,
    ) -> RemoraAuditChain:
        """Load a chain from a JSONL file without re-appending envelopes.

        The loaded chain can be verified but no new entries should be
        appended without first confirming the chain tip.
        """
        chain = cls(secret_key=secret_key)
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = ChainEntry.from_dict(json.loads(line))
                chain._entries.append(entry)

        if chain._entries:
            chain._prev_hash = chain._entries[-1].hash
        return chain

    def summary(self) -> dict[str, Any]:
        """Return a compact summary of chain state."""
        return {
            "length": self.length,
            "tip_hash": self._prev_hash[:32] + "…" if self.length else None,
            "signed": self._secret is not None,
            "genesis_hash": GENESIS_HASH[:16] + "…",
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_hash(
        previous_hash: str,
        request_id: str,
        gate_outcome: str,
        policy_version: str,
    ) -> str:
        payload = f"{previous_hash}:{request_id}:{gate_outcome}:{policy_version}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _sign(self, hash_value: str) -> str:
        assert self._secret is not None
        return hmac.new(self._secret, hash_value.encode("utf-8"), hashlib.sha256).hexdigest()
