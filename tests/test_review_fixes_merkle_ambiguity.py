# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The odd-node duplication ambiguity, before and after SR-14.

v1 roots are persisted (export_daily_root files, checkpoints, provenance DAG,
docs) and keep the legacy construction so old anchors still verify:
[a,b,c] and [a,b,c,c] share a v1 root. v2 (default since 2026-10-28) applies
RFC 6962 domain separation and promotes odd nodes, which removes the
ambiguity, and v2 exports must commit the entry count (SEC-03).
"""
from __future__ import annotations

import json

import pytest

from remora.audit.hash_chain import AuditHashChain
from remora.audit.merkle import compute_merkle_root, export_daily_root


def test_odd_node_duplication_ambiguity_is_fixed_in_v2_kept_in_v1(tmp_path):
    chain = AuditHashChain()
    for i in range(3):
        chain.append(timestamp="t", question_hash=f"q{i}", action="accept",
                     trust_score=0.5, phase="p", metadata={})
    a, b, c = chain.entries()
    # v1 (legacy anchors): the ambiguity is documented and unchanged.
    assert compute_merkle_root([a, b, c], version=1) == compute_merkle_root([a, b, c, c], version=1)
    # v2: fixed. Duplicating the tail changes the root.
    assert compute_merkle_root([a, b, c]) != compute_merkle_root([a, b, c, c])
    # v2 exports must commit the entry count next to the root.
    with pytest.raises((TypeError, ValueError)):
        export_daily_root(compute_merkle_root([a, b, c]), directory=tmp_path)
    path = export_daily_root(compute_merkle_root([a, b, c]), directory=tmp_path, n_entries=3)
    record = json.loads(path.read_text().splitlines()[0])
    assert record["n_entries"] == 3
    assert record["v"] == 2
