# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Documents a known Merkle ambiguity (odd-node duplication).

The roots are persisted (export_daily_root files, checkpoints, provenance
DAG, docs), so the algorithm is deliberately NOT changed here: doing so would
invalidate verification of existing data. Callers must commit the entry count
(export_daily_root(n_entries=...)) next to the root.
"""
from __future__ import annotations

import json

from remora.audit.hash_chain import AuditHashChain
from remora.audit.merkle import compute_merkle_root, export_daily_root


def test_odd_node_duplication_ambiguity_is_documented(tmp_path):
    chain = AuditHashChain()
    for i in range(3):
        chain.append(timestamp="t", question_hash=f"q{i}", action="accept",
                     trust_score=0.5, phase="p", metadata={})
    a, b, c = chain.entries()
    # Known limitation: [a,b,c] and [a,b,c,c] share a root.
    assert compute_merkle_root([a, b, c]) == compute_merkle_root([a, b, c, c])
    # Mitigation: the exported record carries the entry count.
    path = export_daily_root(compute_merkle_root([a, b, c]), directory=tmp_path, n_entries=3)
    assert json.loads(path.read_text().splitlines()[0])["n_entries"] == 3
