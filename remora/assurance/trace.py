# Author: Stian Skogbrott
# License: Apache-2.0
"""Tamper-evident assurance trace for a REMORA run.

NOT zero-knowledge. This is a Merkle-anchored audit log: any single tampered
entry breaks the root. Useful for:

- Customer audit: prove a run executed against the consensus log they verified.
- Reproducibility: anyone with the consensus log can recompute the root.

What it is not:
- A zero-knowledge proof (the leaves are not concealed).
- A blockchain (no consensus across parties).
- A proof of correctness (only of integrity).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from remora.assurance.merkle import MerkleProof, build_merkle_tree


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
    signature_standard: str = "REMORA-Assurance-Trace-v1"


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
    tree = build_merkle_tree(list(leaves_bytes))
    proofs = tuple(tree.proof(i) for i in range(len(leaves_bytes)))
    return AssuranceTrace(
        root_hash=tree.root,
        leaf_count=len(leaves_bytes),
        betti_0=int(betti_info.get("betti_0", 0)),
        betti_1=int(betti_info.get("betti_1", 0)),
        lyapunov_final_V=float(final_V),
        canonical_leaves=leaves_bytes,
        inclusion_proofs=proofs,
    )
