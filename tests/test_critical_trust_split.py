# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""CLAIM-005 backing artifact: the critical-phase trust split at the tau=0.10
groupthink boundary is reproducible, shows the inversion, and is consistent with
the committed 20/32 critical aggregate."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "results" / "critical_trust_split_v1.json"


def _regenerate() -> dict:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cts", ROOT / "scripts" / "compute_critical_trust_split.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.compute()


def test_artifact_reproduces_from_script() -> None:
    committed = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    regen = _regenerate()
    for key in ("n_critical", "aggregate_correct", "low_trust_bucket",
                "high_trust_bucket", "tau_groupthink_boundary", "quartile_view"):
        assert committed[key] == regen[key], f"drift in {key}"


def test_trust_inversion_and_consistency() -> None:
    d = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    lo, hi = d["low_trust_bucket"], d["high_trust_bucket"]
    assert d["n_critical"] == 32
    # Sample sizes match the published N=21 / N=11 framing.
    assert lo["n"] == 21 and hi["n"] == 11
    assert lo["n"] + hi["n"] == 32
    # Inversion: lower-trust critical items are MORE often correct.
    assert d["trust_inversion_present"] is True
    assert lo["accuracy_pct"] > hi["accuracy_pct"]
    # Bucket correct counts reconcile with the committed 20/32 aggregate
    # (the exact inconsistency that sank the old 71.4/27.3 numbers, 15+3=18).
    assert lo["correct"] + hi["correct"] == d["aggregate_correct"] == 20
    assert d["consistency_check"]["matches_aggregate"] is True
