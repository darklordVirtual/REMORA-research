# Author: Stian Skogbrott
# License: Apache-2.0
"""Merkle root computation and daily root-hash export for REMORA audit chains.

Provides a lightweight optional anchoring layer that allows external parties
to verify the integrity of the audit chain without holding a full copy.

IMPORTANT: This module makes the audit trail tamper-DETECTABLE, not
tamper-resistant.  The Merkle root is only meaningful if it is published to
an external, independent, append-only store (e.g. Transparency Log,
WORM/S3-object-lock, blockchain).  Storing the root in the same system
as the chain provides no additional security guarantee.

See ``docs/enterprise/audit-anchoring-guide.md`` for deployment options:
  - AWS S3 with Object Lock (WORM)
  - Azure Blob Storage with Immutability Policy
  - Google Cloud Storage with retention policies
  - Transparency Logs (Trillian / Sigstore)
  - RFC 3161 Trusted Timestamp Authority
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.audit.hash_chain import HashChainEntry


def compute_merkle_root(entries: list["HashChainEntry"]) -> str:
    """Compute a deterministic Merkle root over a list of hash-chain entries.

    The leaf hash for each entry is SHA-256 of its canonical JSON representation
    (all fields, sorted keys).  Pairs are combined as SHA-256(left + right);
    odd trees are completed by duplicating the last leaf.

    Parameters
    ----------
    entries:
        Ordered list of audit chain entries.

    Returns
    -------
    str
        64-character lowercase hex SHA-256 Merkle root, or ``""`` for empty input.

    Notes
    -----
    The Merkle root is deterministic given identical entry contents.  Any
    modification to a single entry changes the root, making the root suitable
    as a tamper-detection digest over the entire audit window.
    """
    if not entries:
        return ""

    import dataclasses

    def _leaf(entry: "HashChainEntry") -> str:
        canonical = json.dumps(dataclasses.asdict(entry), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _combine(left: str, right: str) -> str:
        return hashlib.sha256((left + right).encode("utf-8")).hexdigest()

    hashes = [_leaf(e) for e in entries]
    while len(hashes) > 1:
        if len(hashes) % 2 != 0:
            hashes.append(hashes[-1])  # duplicate last leaf for odd trees
        hashes = [_combine(hashes[i], hashes[i + 1]) for i in range(0, len(hashes), 2)]
    return hashes[0]


def sign_root(root_hash: str, *, key: str) -> str:
    """Produce an HMAC-SHA256 signature of a Merkle root hash.

    Parameters
    ----------
    root_hash:
        The 64-char hex Merkle root to sign.
    key:
        The signing key (e.g. from ``REMORA_ENVELOPE_SIGNING_KEY``).

    Returns
    -------
    str
        64-character hex HMAC-SHA256 signature.

    Notes
    -----
    This is a symmetric HMAC, not an asymmetric signature.  For non-repudiation
    or public auditability, replace with an asymmetric scheme (Ed25519, ECDSA).
    The key must be kept secret; anyone who holds it can forge a valid signature.
    """
    return hmac.new(
        key.encode("utf-8"),
        root_hash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_signed_root(root_hash: str, signature: str, *, key: str) -> bool:
    """Verify an HMAC-SHA256 signature against a Merkle root hash.

    Uses ``hmac.compare_digest`` to prevent timing-oracle attacks.

    Returns
    -------
    bool
        ``True`` if the signature is valid for the given root and key.
    """
    expected = sign_root(root_hash, key=key)
    return hmac.compare_digest(expected, signature)


def export_daily_root(
    root_hash: str,
    *,
    directory: Path | str,
    signing_key: str | None = None,
    n_entries: int | None = None,
    timestamp: str | None = None,
) -> Path:
    """Append a Merkle root record to the daily audit-root JSONL file.

    The file is named ``audit-root-YYYY-MM-DD.jsonl`` inside *directory*.
    Each line is a JSON record.  The file is opened in append mode so that
    multiple exports on the same day are all preserved.

    Parameters
    ----------
    root_hash:
        The 64-char hex Merkle root to record.
    directory:
        Directory to write the JSONL file to (created if absent).
    signing_key:
        If provided, an HMAC-SHA256 ``signature`` field is added to the record.
    n_entries:
        Optional: number of audit chain entries the root covers.
    timestamp:
        ISO-8601 UTC timestamp (default: ``datetime.now(tz=timezone.utc).isoformat()``).

    Returns
    -------
    Path
        Absolute path of the JSONL file written to.

    Notes
    -----
    Writing to the same filesystem as the audit chain provides no additional
    security — an adversary who can rewrite the chain can also rewrite this
    file.  For meaningful anchoring, copy or publish the root to an external
    system immediately after export.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    record: dict = {
        "ts": timestamp or datetime.now(tz=timezone.utc).isoformat(),
        "merkle_root": root_hash,
    }
    if n_entries is not None:
        record["n_entries"] = n_entries
    if signing_key is not None:
        record["signature"] = sign_root(root_hash, key=signing_key)

    path = directory / f"audit-root-{today}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return path
