# Author: Stian Skogbrott
# License: Apache-2.0
"""CLAIM-005 backing artifact: the critical-phase trust split is reproducible,
shows the trust inversion, and is consistent with the committed 20/32 aggregate."""
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
    """The committed artifact must equal a fresh deterministic regeneration."""
    committed = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    regen = _regenerate()
    for key in ("n_critical", "aggregate_correct", "low_trust_bucket",
                "high_trust_bucket", "median_critical_trust"):
        assert committed[key] == regen[key], f"drift in {key}"


def test_trust_inversion_and_consistency() -> None:
    d = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    lo, hi = d["low_trust_bucket"], d["high_trust_bucket"]
    # 32 critical items total, split covers all of them.
    assert d["n_critical"] == 32
    assert lo["n"] + hi["n"] == 32
    # Inversion: lower-trust critical items are MORE often correct.
    assert d["trust_inversion_present"] is True
    assert lo["accuracy"] > hi["accuracy"]
    # Bucket correct counts must reconcile with the committed 20/32 aggregate
    # (the exact inconsistency that sank the old 71.4/27.3 numbers).
    assert lo["correct"] + hi["correct"] == d["aggregate_correct"] == 20
    assert d["consistency_check"]["matches_aggregate"] is True
