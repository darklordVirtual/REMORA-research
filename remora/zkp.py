# Author: Stian Skogbrott
# License: Apache-2.0
from __future__ import annotations
"""DEPRECATED shim — use remora.assurance.

This module used to expose AssuranceCertificate and a linear-hash-chain trace
under the misleading name "Zero-Knowledge Proof". The trace was tamper-evident
but never zero-knowledge. Migrate to:

    from remora.assurance.trace import AssuranceTrace, generate_assurance_trace

The shim below preserves the old API surface for one release cycle.
"""
import warnings
from dataclasses import dataclass

from remora.stability import RESEARCH_ONLY
__stability__ = RESEARCH_ONLY

from remora.assurance.trace import (
    AssuranceTrace,
    generate_assurance_trace as _generate_trace,
)

warnings.warn(
    "remora.zkp is deprecated; import from remora.assurance.trace instead."
    " Will be removed in v0.7.0.",
    DeprecationWarning,
    stacklevel=2,
)


@dataclass
class AssuranceCertificate:
    root_hash: str
    merkle_path: list[str]
    betti_0: int
    betti_1: int
    lyapunov_final_V: float
    total_oracles: int
    signature_standard: str = "REMORA-Assurance-Trace-v1"


def generate_assurance_certificate(
    state_consensus_log: list[dict],
    final_V: float,
    betti_info: dict,
) -> AssuranceCertificate:
    trace: AssuranceTrace = _generate_trace(state_consensus_log, final_V, betti_info)
    path: list[str] = []
    if trace.canonical_leaves:
        from remora.assurance.merkle import build_merkle_tree
        tree = build_merkle_tree(list(trace.canonical_leaves))
        for level in tree.levels:
            path.extend(level)
    return AssuranceCertificate(
        root_hash=trace.root_hash,
        merkle_path=path,
        betti_0=trace.betti_0,
        betti_1=trace.betti_1,
        lyapunov_final_V=trace.lyapunov_final_V,
        total_oracles=trace.leaf_count,
    )
