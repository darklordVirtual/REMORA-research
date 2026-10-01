# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A FAR claim below 299 independent harmful units fails (quality program Q2.1)."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("far_gate", ROOT / "scripts" / "check_far_claim_size.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)  # type: ignore[union-attr]


def _committed():
    register = yaml.safe_load((ROOT / "docs/assurance/claim_register_v1.yaml").read_text())
    baseline = json.loads((ROOT / "docs/assurance/far_claim_size_baseline.json").read_text())
    return register, baseline


def _far_claim(cid: str, n: int | None) -> dict:
    claim = {"id": cid, "status": "active", "metrics": {"far_pct": 0.0}}
    if n is not None:
        claim["far_denominator"] = n
    return claim


def test_the_committed_register_passes():
    register, baseline = _committed()
    assert gate.violations(register, baseline) == []


def test_a_new_far_claim_below_the_minimum_fails():
    register, baseline = _committed()
    register["claims"].append(_far_claim("CLAIM-NEW", 250))
    assert any("CLAIM-NEW" in p and "below" in p for p in gate.violations(register, baseline))


def test_a_far_claim_at_the_minimum_passes():
    register, baseline = _committed()
    register["claims"].append(_far_claim("CLAIM-NEW", 299))
    assert gate.violations(register, baseline) == []


def test_a_far_claim_without_a_denominator_fails():
    register, baseline = _committed()
    register["claims"].append(_far_claim("CLAIM-NEW", None))
    assert any("must declare far_denominator" in p for p in gate.violations(register, baseline))


def test_a_baselined_claim_cannot_quietly_change_its_denominator():
    register, baseline = _committed()
    claim = next(c for c in register["claims"] if c["id"] == "CLAIM-002")
    claim["far_denominator"] = 150
    assert any("CLAIM-002" in p and "repeat" in p for p in gate.violations(register, baseline))


def test_the_baseline_only_shrinks():
    register, baseline = _committed()
    claim = next(c for c in register["claims"] if c["id"] == "CLAIM-002")
    claim["far_denominator"] = 400
    assert any("CLAIM-002" in p and "stale" in p for p in gate.violations(register, baseline))


def test_a_superseded_claim_is_not_a_far_claim():
    register, baseline = _committed()
    register = copy.deepcopy(register)
    register["claims"].append({**_far_claim("CLAIM-OLD", 10), "status": "superseded"})
    assert gate.violations(register, baseline) == []


def test_every_committed_far_claim_states_its_bound_in_the_register():
    """The upper bound is the claim the evidence supports; it must be written down."""
    register, _ = _committed()
    for claim in register["claims"]:
        if claim.get("status") == "active" and "far_pct" in (claim.get("metrics") or {}):
            text = json.dumps(claim)
            assert "CI" in text or "far_ci_high_pct" in claim["metrics"] or "effective" in text, claim["id"]
