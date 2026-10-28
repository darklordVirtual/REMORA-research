# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
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


def compute_merkle_root(entries: list["HashChainEntry"], *, version: int = 2) -> str:
    """Compute a deterministic Merkle root over a list of hash-chain entries.

    Version 2 (default since 2026-10-28, SR-14 / SEC-03) uses RFC 6962
    domain separation: leaves hash as SHA-256(0x00 || canonical JSON), nodes
    as SHA-256(0x01 || left || right) over raw digest bytes, and an odd node
    is promoted unchanged rather than duplicated — so [a,b,c] and [a,b,c,c]
    no longer share a root, and an interior node can never pass as a leaf.

    Version 1 is the legacy construction (SHA-256 of canonical JSON leaves;
    SHA-256 over concatenated hex pairs; last node duplicated on odd levels).
    It is retained so anchors recorded before 2026-10-28 still verify, and is
    documented as ambiguous: it does not commit to the entry count.

    Parameters
    ----------
    entries:
        Ordered list of audit chain entries.
    version:
        2 (default) or 1 (legacy, for verifying pre-v2 anchors).

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
    if version not in (1, 2):
        raise ValueError(f"unsupported merkle version {version!r}")
    if not entries:
        return ""

    import dataclasses

    def _canonical(entry: "HashChainEntry") -> bytes:
        return json.dumps(
            dataclasses.asdict(entry), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    if version == 1:
        def _leaf_v1(entry: "HashChainEntry") -> str:
            return hashlib.sha256(_canonical(entry)).hexdigest()

        def _combine_v1(left: str, right: str) -> str:
            return hashlib.sha256((left + right).encode("utf-8")).hexdigest()

        hashes_v1 = [_leaf_v1(e) for e in entries]
        while len(hashes_v1) > 1:
            if len(hashes_v1) % 2 != 0:
                hashes_v1.append(hashes_v1[-1])  # legacy: duplicate last leaf
            hashes_v1 = [_combine_v1(hashes_v1[i], hashes_v1[i + 1])
                         for i in range(0, len(hashes_v1), 2)]
        return hashes_v1[0]

    def _leaf_v2(entry: "HashChainEntry") -> bytes:
        return hashlib.sha256(b"\x00" + _canonical(entry)).digest()

    def _combine_v2(left: bytes, right: bytes) -> bytes:
        return hashlib.sha256(b"\x01" + left + right).digest()

    level = [_leaf_v2(e) for e in entries]
    while len(level) > 1:
        paired = [_combine_v2(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            paired.append(level[-1])  # RFC 6962: promote the odd node unchanged
        level = paired
    return level[0].hex()


def sign_root(root_hash: str, *, key: str, n_entries: int | None = None,
              version: int = 1) -> str:
    """Produce an HMAC-SHA256 signature of a Merkle root hash.

    Parameters
    ----------
    root_hash:
        The 64-char hex Merkle root to sign.
    key:
        The signing key (e.g. from ``REMORA_ENVELOPE_SIGNING_KEY``).
    n_entries:
        Version 2 only: the leaf count the root commits to (required; SR-14).
    version:
        2 signs ``v2:<n_entries>:<root>`` so the signature binds the count;
        1 (legacy) signs the bare root.

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
    if version == 2:
        if n_entries is None:
            raise ValueError("version-2 root signatures require n_entries (SEC-03)")
        preimage = f"v2:{n_entries}:{root_hash}"
    else:
        preimage = root_hash
    return hmac.new(
        key.encode("utf-8"),
        preimage.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_signed_root(root_hash: str, signature: str, *, key: str,
                       n_entries: int | None = None, version: int = 1) -> bool:
    """Verify an HMAC-SHA256 signature against a Merkle root hash.

    Uses ``hmac.compare_digest`` to prevent timing-oracle attacks. With
    ``version=2`` the count is part of the preimage, so a record whose
    ``n_entries`` was edited after signing fails.

    Returns
    -------
    bool
        ``True`` if the signature is valid for the given root and key.
    """
    expected = sign_root(root_hash, key=key, n_entries=n_entries, version=version)
    return hmac.compare_digest(expected, signature)


def export_daily_root(
    root_hash: str,
    *,
    directory: Path | str,
    signing_key: str | None = None,
    n_entries: int | None = None,
    timestamp: str | None = None,
    version: int = 2,
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

    if version == 2 and n_entries is None:
        # SEC-03 (SR-14): a root that does not commit to its leaf count cannot
        # tell [a,b,c] from a truncated or padded list.
        raise ValueError("version-2 exports require n_entries")

    today = date.today().isoformat()
    record: dict = {
        "ts": timestamp or datetime.now(tz=timezone.utc).isoformat(),
        "merkle_root": root_hash,
    }
    if version == 2:
        record["v"] = 2
    if n_entries is not None:
        record["n_entries"] = n_entries
    if signing_key is not None:
        record["signature"] = sign_root(
            root_hash, key=signing_key, n_entries=n_entries, version=version,
        )

    path = directory / f"audit-root-{today}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return path
