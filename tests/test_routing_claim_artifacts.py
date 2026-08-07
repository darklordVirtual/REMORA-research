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
BFCL_V4 = ROOT / "results" / "routing_bench_bfcl_v4_results.json"
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
    wrong = d["targets"]["known_wrong_call_accept"]
    assert f"wrong_call_accept_pct: {round(wrong['n'] / wrong['d'] * 100, 1)}" in block
    assert f"obtainable_verify_pct: {round(d['targets']['obtainable_verify_recall']['value'] * 100, 1)}" in block
    assert f"n_clusters: {d['n_clusters']}" in block


def test_bfcl_v4_confirmation_is_sealed_and_all_five_targets_met() -> None:
    d = _load(BFCL_V4)
    assert d["schema"] == "routing_bench_bfcl_results_v1"
    assert d["status"] == "evaluated_once"
    assert d["holdout_sha256"] == (
        "00ccd5384c14eee25797b8c683f16eb4e8cac856a81feeb228a254d5702d05d3"
    )
    assert d["n_episodes"] == 1527
    assert d["n_labelled"] == 1170
    assert d["all_targets_met"] is True
    assert all(target["met"] for target in d["targets"].values())
    assert d["targets"]["required_unknown_auto_accept"]["value"] == 0.0
    assert d["targets"]["irrelevance_abstain_recall"]["value"] == 1.0
    assert d["targets"]["known_wrong_call_accept"]["value"] == 0.1085
    assert d["targets"]["obtainable_verify_recall"]["value"] == 0.9697
    assert d["targets"]["unobtainable_abstain_recall"]["value"] == 0.9899


def test_bfcl_v4_register_entry_matches_the_sealed_artifact() -> None:
    block = _claim_block("CLAIM-018")
    d = _load(BFCL_V4)
    assert "externally_benchmarked" in block
    assert "blindness: blind" in block
    assert f"routing_accuracy_pct: {round(d['routing_accuracy_labelled'] * 100, 1)}" in block
    wrong = d["targets"]["known_wrong_call_accept"]
    assert f"wrong_call_accept_pct: {round(wrong['n'] / wrong['d'] * 100, 1)}" in block
    assert f"obtainable_verify_pct: {round(d['targets']['obtainable_verify_recall']['value'] * 100, 1)}" in block


# ---------------------------------------------------------------------------
# System demonstration and superseded CLAIM-015
# ---------------------------------------------------------------------------

def test_value_grounding_demonstration_labels_itself_development() -> None:
    d = _load(DEMO)
    assert d["schema"] == "system_demonstration_v1"
    assert d["status"] == "development_rerun_plus_sealed_artifact_reference"

    bfcl = d["bfcl_foreign_calls"]
    assert bfcl["status"] == "sealed_artifact_reference_not_rerun"
    assert bfcl["all_targets_met"] is True
    assert bfcl["known_wrong_call_accept"]["met"] is True
    assert "wrong_call_accept_post_grounding" not in bfcl
    assert "wrong_call_accept_blind_prefix" not in bfcl


def test_value_grounding_register_entry_carries_the_blind_caveat() -> None:
    block = _claim_block("CLAIM-015")
    assert "status: superseded" in block
    assert "superseded_by: CLAIM-018" in block
    assert "blindness: development" in block
    assert "NEGATIVE_RESULTS.md" in block
    assert "The active external result is CLAIM-018" in block


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
