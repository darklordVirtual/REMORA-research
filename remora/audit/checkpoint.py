# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Chain-agnostic Merkle checkpoint layer over REMORA audit hash chains.

Wires the existing Merkle primitives (``remora.audit.merkle``) to the hash
chains REMORA actually produces, via thin leaf adapters:

  * per-tenant envelope chain (``remora.governance.tenant_chain`` —
    ``ChainEntry.entry_hash``),
  * shadow/replay DecisionEnvelope chain (``remora.shadow.replay`` —
    ``envelope.audit.hash``, the same field
    ``verify_envelope_hash_chain`` checks),
  * plain lists of 64-char hex SHA-256 digests (covers
    ``remora.audit.hash_chain`` entry hashes and any future chain).

A :class:`Checkpoint` commits to a contiguous span ``[seq_start, seq_end]``
of a chain's entry-hash sequence with a Merkle root, and links to the
previous checkpoint's root so a sequence of checkpoints is itself a chain.
``signing_payload()`` provides a stable byte string for future external
anchoring (transparency log / WORM publication — NOT implemented here;
tracked as REM-025 in ``docs/assurance/remediation_register.yaml``).

IMPORTANT: Like the underlying chains, checkpoints stored next to the chain
are tamper-EVIDENT only.  They become tamper-RESISTANT for post-checkpoint
history only once roots are published to an external, independent,
append-only store — and even then nothing here makes the writer honest at
write time.  See ``docs/enterprise/audit-anchoring-guide.md``.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from remora.audit.merkle import sign_root, verify_signed_root

if TYPE_CHECKING:
    from remora.governance.envelope import DecisionEnvelope
    from remora.governance.tenant_chain import ChainEntry

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

# Version tag for the checkpoint signing payload.  Bump only with a new
# payload layout; verifiers key their parsing on this prefix.
_PAYLOAD_PREFIX = "remora-ckpt-v1"


def merkle_root_from_hex_leaves(leaves: Sequence[str]) -> str:
    """Merkle root over leaves that are already 64-char hex digests.

    ``remora.audit.merkle.compute_merkle_root`` is typed for
    ``HashChainEntry`` objects and derives each leaf by hashing the entry's
    canonical JSON, so it cannot take raw hex leaves.  This is the smallest
    adapter: the inputs (chain entry hashes) are used as leaf digests
    directly, and the tree uses the same pairing rule as
    ``compute_merkle_root`` — pairs combine as SHA-256(left + right) over
    the concatenated hex strings, odd trees duplicate the last node.

    Parameters
    ----------
    leaves:
        Ordered hex digests (one per chain entry).

    Returns
    -------
    str
        64-character lowercase hex SHA-256 Merkle root, or ``""`` for
        empty input (mirrors ``compute_merkle_root``).
    """
    if not leaves:
        return ""

    def _combine(left: str, right: str) -> str:
        return hashlib.sha256((left + right).encode("utf-8")).hexdigest()

    hashes = list(leaves)
    while len(hashes) > 1:
        if len(hashes) % 2 != 0:
            hashes.append(hashes[-1])  # duplicate last node for odd trees
        hashes = [_combine(hashes[i], hashes[i + 1]) for i in range(0, len(hashes), 2)]
    return hashes[0]


def tenant_chain_leaves(entries: Sequence["ChainEntry"]) -> list[str]:
    """Leaf adapter for the per-tenant envelope chain (REM-034 core).

    Extracts ``entry_hash`` from each ``remora.governance.tenant_chain``
    entry, in chain order.

    Raises
    ------
    ValueError
        If any entry carries a malformed ``entry_hash``.
    """
    leaves: list[str] = []
    for i, entry in enumerate(entries):
        entry_hash = entry.entry_hash
        if not isinstance(entry_hash, str) or not _HEX64_RE.match(entry_hash):
            raise ValueError(f"tenant chain entry {i} has invalid entry_hash: {entry_hash!r}")
        leaves.append(entry_hash)
    return leaves


def envelope_chain_leaves(envelopes: Sequence["DecisionEnvelope"]) -> list[str]:
    """Leaf adapter for the shadow/replay DecisionEnvelope hash chain.

    Extracts ``envelope.audit.hash`` from each envelope — the same field
    ``remora.shadow.replay.verify_envelope_hash_chain`` recomputes.  Run
    that verifier first; this adapter only extracts, it does not re-verify
    the chain linkage.

    Raises
    ------
    ValueError
        If any envelope has no (or a malformed) audit hash.
    """
    leaves: list[str] = []
    for i, envelope in enumerate(envelopes):
        envelope_hash = envelope.audit.hash
        if not isinstance(envelope_hash, str) or not _HEX64_RE.match(envelope_hash):
            raise ValueError(f"envelope {i} has no valid audit hash: {envelope_hash!r}")
        leaves.append(envelope_hash)
    return leaves


@dataclass(frozen=True)
class Checkpoint:
    """Merkle commitment to a contiguous span of a chain's hash sequence.

    Attributes
    ----------
    seq_start:
        0-based index of the first entry hash covered by this checkpoint.
    seq_end:
        0-based index of the last entry hash covered (inclusive).
    root:
        Hex Merkle root over the span (``merkle_root_from_hex_leaves``).
    prev_checkpoint_root:
        Root of the immediately preceding checkpoint, or ``None`` for the
        first checkpoint of a chain.  Links checkpoints into their own
        chain so a dropped or reordered checkpoint is detectable.
    """

    seq_start: int
    seq_end: int
    root: str
    prev_checkpoint_root: str | None

    def signing_payload(self) -> bytes:
        """Stable byte string for signing / future external anchoring.

        Format: ``b"remora-ckpt-v1|<seq_start>|<seq_end>|<root>|<prev>"``
        where ``<prev>`` is the previous checkpoint root or the empty
        string for the first checkpoint.  All fields are decimal integers
        or lowercase hex, so ``|`` is an unambiguous delimiter.
        """
        prev = self.prev_checkpoint_root or ""
        return f"{_PAYLOAD_PREFIX}|{self.seq_start}|{self.seq_end}|{self.root}|{prev}".encode(
            "utf-8"
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Checkpoint":
        return cls(
            seq_start=d["seq_start"],
            seq_end=d["seq_end"],
            root=d["root"],
            prev_checkpoint_root=d.get("prev_checkpoint_root"),
        )


def make_checkpoint(
    hashes: Sequence[str],
    seq_start: int,
    prev: Checkpoint | None = None,
) -> Checkpoint:
    """Build a checkpoint over *hashes* starting at chain position *seq_start*.

    Parameters
    ----------
    hashes:
        Non-empty ordered span of 64-char hex entry hashes.
    seq_start:
        0-based chain position of ``hashes[0]``.
    prev:
        The immediately preceding checkpoint (``None`` for the first).
        Spans must be contiguous: ``seq_start == prev.seq_end + 1``.

    Raises
    ------
    ValueError
        On an empty span, malformed hash, negative ``seq_start``, or a
        non-contiguous link to *prev*.
    """
    if not hashes:
        raise ValueError("cannot checkpoint an empty span")
    if seq_start < 0:
        raise ValueError(f"seq_start must be >= 0, got {seq_start}")
    for i, h in enumerate(hashes):
        if not isinstance(h, str) or not _HEX64_RE.match(h):
            raise ValueError(f"span position {i} is not a 64-char hex hash: {h!r}")
    if prev is not None and seq_start != prev.seq_end + 1:
        raise ValueError(
            f"non-contiguous checkpoint: seq_start={seq_start} but "
            f"prev.seq_end={prev.seq_end} (expected seq_start={prev.seq_end + 1})"
        )
    return Checkpoint(
        seq_start=seq_start,
        seq_end=seq_start + len(hashes) - 1,
        root=merkle_root_from_hex_leaves(hashes),
        prev_checkpoint_root=prev.root if prev is not None else None,
    )


def verify_span(hashes: Sequence[str], checkpoint: Checkpoint) -> bool:
    """Recompute-and-compare span verification.

    Returns ``True`` only when *hashes* has exactly the length the
    checkpoint declares AND its recomputed Merkle root equals
    ``checkpoint.root``.  Any tamper (a single flipped bit in any hash) or
    length mismatch returns ``False``.  Leaves are expected to be strings
    (malformed hex simply fails the root comparison); non-string leaves
    raise ``TypeError``.
    """
    declared_len = checkpoint.seq_end - checkpoint.seq_start + 1
    if declared_len <= 0 or len(hashes) != declared_len:
        return False
    return merkle_root_from_hex_leaves(list(hashes)) == checkpoint.root


def verify_checkpoint_chain(checkpoints: Sequence[Checkpoint]) -> tuple[bool, list[str]]:
    """Consistency check over consecutive checkpoints; reports every break.

    Checks, per checkpoint: the span is well-formed (``seq_end >=
    seq_start``); from the second checkpoint on, ``prev_checkpoint_root``
    equals the previous checkpoint's ``root`` and spans are contiguous
    (``seq_start == previous.seq_end + 1``).  The first checkpoint's
    ``prev_checkpoint_root`` anchors outside the given window and is not
    checked here.

    Returns
    -------
    tuple[bool, list[str]]
        ``(ok, problems)`` in the same style as
        ``remora.governance.tenant_chain.TenantAuditChain.verify``.
    """
    problems: list[str] = []
    for i, checkpoint in enumerate(checkpoints):
        if checkpoint.seq_end < checkpoint.seq_start:
            problems.append(f"invalid_span_at:{i}")
        if i == 0:
            continue
        previous = checkpoints[i - 1]
        if checkpoint.prev_checkpoint_root != previous.root:
            problems.append(f"linkage_break_at:{i}")
        if checkpoint.seq_start != previous.seq_end + 1:
            problems.append(f"span_gap_at:{i}")
    return (not problems, problems)


def sign_checkpoint(checkpoint: Checkpoint, *, key: str) -> str:
    """HMAC-SHA256 signature over ``signing_payload()``.

    Reuses ``remora.audit.merkle.sign_root`` (same key semantics and the
    same symmetric-HMAC caveat: anyone holding the key can forge).
    """
    return sign_root(checkpoint.signing_payload().decode("utf-8"), key=key)


def verify_checkpoint_signature(checkpoint: Checkpoint, signature: str, *, key: str) -> bool:
    """Verify an HMAC-SHA256 checkpoint signature (constant-time compare)."""
    return verify_signed_root(checkpoint.signing_payload().decode("utf-8"), signature, key=key)
