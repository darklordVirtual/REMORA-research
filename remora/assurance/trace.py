# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tamper-evident assurance trace for a REMORA run.

NOT zero-knowledge. This is a Merkle-anchored audit log: any single tampered
entry breaks the root. Useful for:

- Customer audit: prove a run executed against the consensus log they verified.
- Reproducibility: anyone with the consensus log can recompute the root.

What it is not:
- A zero-knowledge proof (the leaves are not concealed).
- A blockchain (no consensus across parties).
- A proof of correctness (only of integrity).

Versions (AACP-X-02). ``signature_standard`` names the Merkle construction:
``REMORA-Assurance-Trace-v1`` traces were built with the legacy, ambiguous
tree (:data:`remora.assurance.merkle.MERKLE_V1`) and verify only under it;
new traces are ``REMORA-Assurance-Trace-v2`` (:data:`MERKLE_V2`). Use
:func:`verify_assurance_trace`, which picks the construction from the
standard and rejects an unknown one; a v1 root is never re-read as v2.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from remora.assurance.merkle import (
    MERKLE_V1,
    MERKLE_V2,
    MerkleProof,
    UnsupportedMerkleVersion,
    build_merkle_tree,
    verify_inclusion,
)

TRACE_STANDARD_V1 = "REMORA-Assurance-Trace-v1"
TRACE_STANDARD_V2 = "REMORA-Assurance-Trace-v2"
_MERKLE_FOR_STANDARD = {TRACE_STANDARD_V1: MERKLE_V1, TRACE_STANDARD_V2: MERKLE_V2}


def merkle_version_for(signature_standard: str) -> str:
    """The Merkle construction a trace standard uses; unknown ones raise."""
    try:
        return _MERKLE_FOR_STANDARD[signature_standard]
    except (KeyError, TypeError):
        raise UnsupportedMerkleVersion(
            f"unsupported assurance trace standard {signature_standard!r}") from None


def _canonicalise(entry: dict) -> bytes:
    keep = {
        "t": entry.get("t"),
        "winning_fp": entry.get("winning_fp"),
        "V": round(float(entry.get("V", 0.0)), 6),
        "D": round(float(entry.get("D", 0.0)), 6),
        "H": round(float(entry.get("H", 0.0)), 6),
        "weighted_support": entry.get("weighted_support"),
    }
    return json.dumps(keep, sort_keys=True).encode("utf-8")


@dataclass(frozen=True)
class AssuranceTrace:
    root_hash: str
    leaf_count: int
    betti_0: int
    betti_1: int
    lyapunov_final_V: float
    canonical_leaves: tuple[bytes, ...] = ()
    inclusion_proofs: tuple[MerkleProof, ...] = ()
    signature_standard: str = TRACE_STANDARD_V2


def generate_assurance_trace(
    state_consensus_log: list[dict],
    final_V: float,
    betti_info: dict,
) -> AssuranceTrace:
    if not state_consensus_log:
        return AssuranceTrace(
            root_hash="",
            leaf_count=0,
            betti_0=int(betti_info.get("betti_0", 0)),
            betti_1=int(betti_info.get("betti_1", 0)),
            lyapunov_final_V=float(final_V),
        )
    leaves_bytes = tuple(_canonicalise(e) for e in state_consensus_log)
    tree = build_merkle_tree(list(leaves_bytes), version=MERKLE_V2)
    proofs = tuple(tree.proof(i) for i in range(len(leaves_bytes)))
    return AssuranceTrace(
        root_hash=tree.root,
        leaf_count=len(leaves_bytes),
        betti_0=int(betti_info.get("betti_0", 0)),
        betti_1=int(betti_info.get("betti_1", 0)),
        lyapunov_final_V=float(final_V),
        canonical_leaves=leaves_bytes,
        inclusion_proofs=proofs,
        signature_standard=TRACE_STANDARD_V2,
    )


def verify_assurance_trace(trace: AssuranceTrace) -> bool:
    """Recompute a trace's root from its leaves and check every proof.

    The construction comes from ``signature_standard``; an unknown standard,
    a proof of another version, a ``leaf_count`` that disagrees with the
    leaves or proofs, or any leaf that does not reproduce the root is a
    rejection. An empty trace verifies only with an empty root.
    """
    try:
        version = merkle_version_for(trace.signature_standard)
    except UnsupportedMerkleVersion:
        return False
    leaves = trace.canonical_leaves
    if trace.leaf_count != len(leaves) or len(trace.inclusion_proofs) != len(leaves):
        return False
    if not leaves:
        return trace.root_hash == ""
    if build_merkle_tree(list(leaves), version=version).root != trace.root_hash:
        return False
    return all(
        p.leaf_index == i and verify_inclusion(leaf, p, trace.root_hash, version=version)
        for i, (leaf, p) in enumerate(zip(leaves, trace.inclusion_proofs, strict=True))
    )
