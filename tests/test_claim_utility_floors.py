# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The utility-floor gate: a safety claim must carry its utility cost.

A false-accept rate of zero is cheap if the gate refuses everything. These
tests pin the rules that keep the utility side of an active safety claim
visible and machine-checked instead of left in prose.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_claim_utility_floors as gate  # noqa: E402

FLOOR = {
    "metric": "read_autonomy_pct",
    "min": 75.0,
    "source": "docs/assurance/statistical_analysis_plan_v5_bfcl_semantic.md",
    "status": "missed",
}

CLAIM = {
    "id": "CLAIM-900",
    "status": "active",
    "metrics": {"far_pct": 0.0, "read_autonomy_pct": 26.6},
    "metric_bindings": {
        "far_pct": {"path": "results/x.json#far", "scale": 100},
        "read_autonomy_pct": {"path": "results/x.json#read_autonomy", "scale": 100},
    },
    "utility_floors": [FLOOR],
}


def _check(*claims: dict) -> list[str]:
    errors, _rows = gate.check({"claims": list(claims)}, root=ROOT)
    return errors


def _with(**changes) -> dict:
    claim = copy.deepcopy(CLAIM)
    floor = claim["utility_floors"][0]
    for key, value in changes.items():
        if value is None:
            floor.pop(key, None)
        else:
            floor[key] = value
    return claim


def test_a_missed_floor_declared_as_missed_passes():
    assert _check(CLAIM) == []


def test_a_missed_floor_declared_as_met_fails():
    errors = _check(_with(status="met"))
    assert errors == [
        "CLAIM-900: utility floor read_autonomy_pct >= 75.0 is missed "
        "(26.6), but the register declares 'met'"
    ]


def test_a_ceiling_is_checked_in_the_other_direction():
    claim = _with(min=None, max=40.0, status="met")
    claim["metrics"]["read_autonomy_pct"] = 100.0
    errors = _check(claim)
    assert errors == [
        "CLAIM-900: utility floor read_autonomy_pct <= 40.0 is missed "
        "(100.0), but the register declares 'met'"
    ]


def test_a_floor_needs_exactly_one_bound():
    assert any("exactly one of 'min' or 'max'" in e
               for e in _check(_with(max=10.0)))
    assert any("exactly one of 'min' or 'max'" in e
               for e in _check(_with(min=None)))


def test_a_floor_on_an_unbound_metric_fails():
    claim = copy.deepcopy(CLAIM)
    claim["metric_bindings"]["read_autonomy_pct"] = {"unbound": "prose only"}
    errors = _check(claim)
    assert errors == [
        "CLAIM-900: utility floor on read_autonomy_pct, which is not bound "
        "to an artifact; a floor must be checkable"
    ]


def test_a_floor_on_a_metric_the_claim_lacks_fails():
    errors = _check(_with(metric="nonexistent_pct"))
    assert errors == [
        "CLAIM-900: utility floor names nonexistent_pct, which is not in "
        "the claim's metrics"
    ]


def test_a_floor_source_must_exist():
    errors = _check(_with(source="docs/no_such_plan.md"))
    assert errors == [
        "CLAIM-900: utility floor source docs/no_such_plan.md does not exist"
    ]


def test_an_unknown_status_fails():
    assert any("status must be one of" in e
               for e in _check(_with(status="probably")))


def test_a_safety_claim_without_floor_or_exemption_fails():
    claim = copy.deepcopy(CLAIM)
    del claim["utility_floors"]
    errors = _check(claim)
    assert errors == [
        "CLAIM-900: active safety claim (far_pct) declares neither "
        "utility_floors nor a utility_floor_exempt reason"
    ]


def test_an_exemption_with_a_reason_passes():
    claim = copy.deepcopy(CLAIM)
    del claim["utility_floors"]
    claim["utility_floor_exempt"] = "corpus holds only harmful items"
    assert _check(claim) == []


def test_an_empty_exemption_does_not_count():
    claim = copy.deepcopy(CLAIM)
    del claim["utility_floors"]
    claim["utility_floor_exempt"] = "  "
    assert len(_check(claim)) == 1


def test_superseded_and_non_safety_claims_are_not_required():
    superseded = copy.deepcopy(CLAIM)
    superseded["status"] = "superseded"
    del superseded["utility_floors"]
    other = {"id": "CLAIM-901", "status": "active",
             "metrics": {"accuracy_pct": 90.0}}
    assert _check(superseded, other) == []


def test_the_committed_register_passes():
    import yaml

    register = yaml.safe_load(gate.REGISTER.read_text(encoding="utf-8"))
    errors, rows = gate.check(register, root=ROOT)
    assert errors == []
    assert rows, "the register declares at least one utility floor"
