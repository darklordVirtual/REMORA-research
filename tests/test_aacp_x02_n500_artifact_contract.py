# SPDX-License-Identifier: BUSL-1.1
"""N500 assurance commitments name their Merkle construction and leaf counts.

Canonical leaves and inclusion proofs are not stored here. Deterministic CI
regenerates the values from actual REMORA assurance traces.
"""
from __future__ import annotations

import json
from pathlib import Path

from remora.assurance.trace import TRACE_STANDARD_V2

ARTIFACT = Path(__file__).resolve().parents[1] / "results/end_to_end_n500_v2.json"


def test_n500_commitments_are_versioned_and_leaf_counted() -> None:
    data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert data["assurance_trace_standard"] == TRACE_STANDARD_V2
    assert data["n_evaluated"] == len(data["items"]) == 544
    for item in data["items"]:
        root, count = item["assurance_root"], item["leaf_count"]
        assert isinstance(root, str) and len(root) == 64
        assert set(root) <= set("0123456789abcdef")
        assert type(count) is int and count > 0


def test_leaf_counts_exist_when_decisions_are_empty() -> None:
    data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    no_decisions = [item for item in data["items"] if not item["decisions"]]
    assert no_decisions
    assert all(type(item["leaf_count"]) is int and item["leaf_count"] > 0
               for item in no_decisions)
