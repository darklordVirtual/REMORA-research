# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Artifact gate for the routing-track claims CLAIM-014 / CLAIM-015 / CLAIM-016.

CLAIM-016 rests on a **sealed blind record**: `routing_bench_bfcl_results.json`
was produced by a single evaluation at locked commit `cf02fa8` on external data
the system had never seen. That set is now spent, so the artifact can never be
legitimately regenerated — a second run would measure development, not
blindness. This module therefore pins its headline numbers and its status
fields, so that any edit which quietly improves the published miss (86.8%
wrong-call acceptance) fails CI instead of shipping.

The two development-measured claims are pinned differently, and deliberately:
`system_demonstration_v1.json` is *expected* to move with the engine, so what is
asserted is the invariant that keeps it honest — that it still carries the blind
prefix and still labels itself a development measurement. The value-grounding
numbers themselves are asserted only against the claim register, which is the
single place they are allowed to be updated.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "assurance" / "claim_register_v1.yaml"

BFCL = ROOT / "results" / "routing_bench_bfcl_results.json"
DEMO = ROOT / "results" / "system_demonstration_v1.json"
VALIDATORS = ROOT / "results" / "fleetops_validator_study_results.json"
DEGRADATION = ROOT / "results" / "fleetops_degradation_results.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _claim_block(claim_id: str) -> str:
    reg = REGISTER.read_text(encoding="utf-8")
    m = re.search(rf"  - id: {claim_id}.*?(?=\n  - id: |\Z)", reg, re.S)
    assert m, f"{claim_id} not found in {REGISTER.name}"
    return m.group(0)


# ---------------------------------------------------------------------------
# CLAIM-016 — the sealed blind record
# ---------------------------------------------------------------------------

def test_bfcl_blind_record_is_sealed_and_unchanged() -> None:
    d = _load(BFCL)
    assert d["schema"] == "routing_bench_bfcl_results_v1"
    assert d["status"] == "evaluated_once"
    assert d["locked_at_commit"] == "cf02fa8"
    assert d["holdout_sha256"].startswith("c3a8e27b")
    assert d["n_episodes"] == 1509
    assert d["n_clusters"] == 515
    assert d["n_labelled"] == 1251


def test_bfcl_four_met_targets_hold_and_the_fifth_is_still_published() -> None:
    t = _load(BFCL)["targets"]
    assert t["required_unknown_auto_accept"]["value"] == 0.0
    assert t["irrelevance_abstain_recall"]["value"] == 1.0
    assert t["unobtainable_abstain_recall"]["value"] == 1.0
    assert round(t["obtainable_verify_recall"]["value"], 3) == 0.827
    for name in (
        "required_unknown_auto_accept",
        "irrelevance_abstain_recall",
        "unobtainable_abstain_recall",
        "obtainable_verify_recall",
    ):
        assert t[name]["met"] is True, f"{name} regressed on the blind record"

    # The miss is the point: it must stay measured, stay failed, and stay at
    # the value that was published. Repairing it here rather than on a new
    # sealed track would be retuning against a spent set.
    miss = t["known_wrong_call_accept"]
    assert miss["met"] is False
    assert round(miss["value"], 4) == 0.8682
    assert _load(BFCL)["all_targets_met"] is False


def test_bfcl_register_entry_matches_the_artifact() -> None:
    block = _claim_block("CLAIM-016")
    d = _load(BFCL)
    assert "externally_benchmarked" in block
    assert "blindness: blind" in block
    assert f"routing_accuracy_pct: {round(d['routing_accuracy_labelled'] * 100, 1)}" in block
    assert f"wrong_call_accept_pct: {round(d['targets']['known_wrong_call_accept']['value'] * 100, 1)}" in block
    assert f"obtainable_verify_pct: {round(d['targets']['obtainable_verify_recall']['value'] * 100, 1)}" in block
    assert f"n_clusters: {d['n_clusters']}" in block


# ---------------------------------------------------------------------------
# CLAIM-015 — the development measurement that must never pose as blind
# ---------------------------------------------------------------------------

def test_value_grounding_demonstration_labels_itself_development() -> None:
    d = _load(DEMO)
    assert d["schema"] == "system_demonstration_v1"
    assert d["status"] == "development_measurement_not_blind"

    bfcl = d["bfcl_foreign_calls"]
    # The blind record travels with the development number so the two can
    # never be quoted apart.
    assert round(bfcl["wrong_call_accept_blind_prefix"], 4) == 0.8682
    assert bfcl["wrong_call_accept_post_grounding"] <= 0.20, (
        "value grounding no longer meets the <=20% bar it was built to meet"
    )
    assert bfcl["wrong_call_accept_post_grounding"] < bfcl["wrong_call_accept_blind_prefix"]


def test_value_grounding_register_entry_carries_the_blind_caveat() -> None:
    block = _claim_block("CLAIM-015")
    assert "blindness: development" in block
    assert "Development measurement, not blind holdout" in block
    # The blind prefix must stay in the entry: 11.6% only means anything next
    # to the 86.8% it improved on, and only if the reader can see that 86.8%
    # was the sealed number and 11.6% was not.
    assert "wrong_call_accept_blind_prefix_pct: 86.8" in block
    d = _load(DEMO)["bfcl_foreign_calls"]
    assert f"wrong_call_accept_post_grounding_pct: {round(d['wrong_call_accept_post_grounding'] * 100, 1)}" in block
    assert f"identity_accept_post_grounding_pct: {round(d['identity_accept_post_grounding'] * 100, 1)}" in block


# ---------------------------------------------------------------------------
# CLAIM-014 — the validator / degradation mechanism study
# ---------------------------------------------------------------------------

def test_validator_study_safety_targets_are_all_at_their_bound() -> None:
    d = _load(VALIDATORS)
    assert d["all_targets_met"] is True
    with_v = d["arms"]["with_validators"]
    without_v = d["arms"]["without_validators"]

    # Utility is the claim; the safety bounds are what make it admissible.
    assert with_v["valid_id_completion_read"]["rate"] == 1.0
    assert without_v["valid_id_completion_read"]["rate"] == 0.0
    for name in ("required_unknown_auto_accept", "write_auto_accept",
                 "corrupt_id_accept_after_resolver", "cross_tenant_validator_use",
                 "false_absent_on_valid", "attempts_exceeded"):
        assert with_v[name]["rate"] == 0.0, f"{name} is no longer at its bound"


def test_degradation_study_expectations_hold_across_every_condition() -> None:
    d = _load(DEGRADATION)
    assert d["all_expectations_met"] is True
    assert len(d["conditions"]) == 7
    for cond in d["conditions"]:
        for name, exp in cond["expectations"].items():
            assert exp["met"] is True, (
                f"degradation condition {cond.get('name', '?')}: {name} no longer met"
            )
