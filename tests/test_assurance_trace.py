# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for AssuranceTrace."""
from __future__ import annotations

import warnings

from remora.assurance.trace import (
    AssuranceTrace,
    generate_assurance_trace,
)


def test_generate_assurance_trace_returns_root_and_per_entry_proofs():
    log = [
        {"t": 1, "winning_fp": "abc", "V": 0.1, "H": 0.2, "D": 0.05, "weighted_support": 0.6},
        {"t": 2, "winning_fp": "abc", "V": 0.08, "H": 0.18, "D": 0.04, "weighted_support": 0.7},
        {"t": 3, "winning_fp": "abc", "V": 0.07, "H": 0.17, "D": 0.04, "weighted_support": 0.8},
    ]
    trace = generate_assurance_trace(log, final_V=0.07, betti_info={"betti_0": 1, "betti_1": 0})
    assert isinstance(trace, AssuranceTrace)
    assert trace.root_hash
    assert len(trace.inclusion_proofs) == len(log)


def test_assurance_trace_inclusion_proofs_verify_against_root():
    from remora.assurance.merkle import verify_inclusion
    log = [{"t": i, "winning_fp": f"fp{i}", "V": 0.0, "H": 0.0, "D": 0.0, "weighted_support": 0.5}
           for i in range(5)]
    trace = generate_assurance_trace(log, final_V=0.0, betti_info={"betti_0": 1, "betti_1": 0})
    for i, (leaf_bytes, proof) in enumerate(zip(trace.canonical_leaves, trace.inclusion_proofs)):
        assert verify_inclusion(leaf_bytes, proof, trace.root_hash), f"failed at i={i}"


def test_zkp_module_import_emits_deprecation_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import importlib
        import remora.zkp
        importlib.reload(remora.zkp)
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_generate_assurance_trace_empty_log_returns_empty_trace():
    trace = generate_assurance_trace([], final_V=0.0, betti_info={"betti_0": 0, "betti_1": 0})
    assert trace.root_hash == ""
    assert trace.leaf_count == 0
    assert trace.canonical_leaves == ()
    assert trace.inclusion_proofs == ()
