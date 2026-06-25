# Author: Stian Skogbrott
# License: Apache-2.0
"""Audit root anchoring prototype.

PR-11: Provides cryptographic anchoring of REMORA decision audit trails
to an immutable root hash.  The anchor records the first-seen entry hash
(the "genesis" of a decision chain) and verifies that subsequent entries
form an unbroken chain back to that root.

This module is a prototype — production anchoring should use an
append-only ledger (e.g. Merkle-tree in a database, or a Transparency Log).

Classes
-------
AuditAnchor
    Manages a chain root and verifies integrity of a JSONL audit file.

Functions
---------
anchor_from_jsonl()
    Create or verify an AuditAnchor from a JSONL audit file.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AnchorRecord:
    """Immutable record of an anchored audit root."""

    root_hash: str          # entry_hash of the first (genesis) entry
    entry_count: int        # total entries at time of anchoring
    chain_valid: bool       # True when every entry links back to root_hash
    broken_at_index: Optional[int] = None   # first broken link (None = intact)
    error_message: Optional[str] = None
    signature: Optional[str] = None
    signature_algorithm: str = "unsigned"


class AuditAnchor:
    """Cryptographic anchor for a JSONL audit chain.

    Parameters
    ----------
    jsonl_path:
        Path to the audit JSONL file produced by ``JSONLAudit``.
    """

    def __init__(
        self,
        jsonl_path: str,
        *,
        signing_key: str | None = None,
        signing_key_env: str = "REMORA_AUDIT_ANCHOR_KEY",
    ) -> None:
        self._path = Path(jsonl_path).resolve()
        self._signing_key = signing_key
        self._signing_key_env = signing_key_env

    def _resolve_signing_key(self) -> str | None:
        if self._signing_key is not None:
            return self._signing_key
        return os.getenv(self._signing_key_env)

    @staticmethod
    def _signature_payload(record: AnchorRecord) -> str:
        payload = {
            "root_hash": record.root_hash,
            "entry_count": record.entry_count,
            "chain_valid": record.chain_valid,
            "broken_at_index": record.broken_at_index,
            "error_message": record.error_message,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def _sign_record(self, record: AnchorRecord) -> AnchorRecord:
        key = self._resolve_signing_key()
        if not key:
            return record

        payload = self._signature_payload(record).encode("utf-8")
        digest = hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return AnchorRecord(
            root_hash=record.root_hash,
            entry_count=record.entry_count,
            chain_valid=record.chain_valid,
            broken_at_index=record.broken_at_index,
            error_message=record.error_message,
            signature=digest,
            signature_algorithm="hmac-sha256",
        )

    def anchor(self) -> AnchorRecord:
        """Read the JSONL file and return an ``AnchorRecord``.

        Validates that every ``previous_hash`` field matches the
        ``entry_hash`` of the preceding line (hash-chain integrity).
        """
        if not self._path.exists():
            return self._sign_record(AnchorRecord(
                root_hash="",
                entry_count=0,
                chain_valid=True,
                error_message="file_not_found",
            ))

        entries: list[dict] = []
        try:
            with open(self._path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entries.append(json.loads(line))
        except (json.JSONDecodeError, OSError) as exc:
            return self._sign_record(AnchorRecord(
                root_hash="",
                entry_count=0,
                chain_valid=False,
                error_message=f"read_error: {exc}",
            ))

        if not entries:
            return self._sign_record(AnchorRecord(root_hash="", entry_count=0, chain_valid=True))

        root_hash = entries[0].get("entry_hash", "")

        # Verify chain linkage
        for i in range(1, len(entries)):
            prev_hash = entries[i - 1].get("entry_hash", "")
            declared_prev = entries[i].get("previous_hash")
            if declared_prev != prev_hash:
                return self._sign_record(AnchorRecord(
                    root_hash=root_hash,
                    entry_count=len(entries),
                    chain_valid=False,
                    broken_at_index=i,
                    error_message=(
                        f"chain_broken: entry[{i}].previous_hash={declared_prev!r} "
                        f"!= entry[{i-1}].entry_hash={prev_hash!r}"
                    ),
                ))

        return self._sign_record(AnchorRecord(
            root_hash=root_hash,
            entry_count=len(entries),
            chain_valid=True,
        ))

    def root_fingerprint(self) -> str:
        """Return a short hex fingerprint of the audit root hash.

        Combines root_hash with entry_count for a compact chain identifier.
        """
        record = self.anchor()
        payload = f"{record.root_hash}:{record.entry_count}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def anchor_from_jsonl(path: str) -> AnchorRecord:
    """Convenience function — create an AuditAnchor and return its AnchorRecord."""
    return AuditAnchor(path).anchor()


def verify_anchor_signature(
    record: AnchorRecord,
    *,
    signing_key: str,
) -> bool:
    """Verify HMAC signature for an AnchorRecord.

    Returns False when the record is unsigned or uses an unsupported algorithm.
    """
    if not record.signature or record.signature_algorithm != "hmac-sha256":
        return False
    payload = AuditAnchor._signature_payload(record).encode("utf-8")
    expected = hmac.new(
        signing_key.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(record.signature, expected)


def export_verify_command(
    *,
    jsonl_path: str,
    anchor_record_path: str,
    key_env_var: str = "REMORA_AUDIT_ANCHOR_KEY",
) -> str:
    """Return a copy-paste command for external auditors.

    The verifier expects the signing key in the provided env var.
    """
    return (
        "python scripts/verify_audit_anchor.py "
        f"--audit-jsonl {jsonl_path} "
        f"--anchor-record {anchor_record_path} "
        f"--key-env {key_env_var}"
    )
