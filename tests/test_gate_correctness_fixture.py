# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The injected validator faults do what the pre-registration says (WS7 item 1).

The study result itself is regenerated and compared in CI by
scripts/reproduce_results.py; these tests pin the fault definitions, so a
change to a fault cannot silently change what the study measured.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import experiments.gate_correctness_study as study  # noqa: E402

LIVE = {"vehicle_id": frozenset({f"V-{i:04d}" for i in range(100)})}


def test_correct_lookup_is_exact():
    look = study.fault_lookup("correct", LIVE)
    assert look("vehicle_id", "V-0007") is True
    assert look("vehicle_id", "V-0007_XX") is False


def test_prefix_matcher_accepts_a_corrupted_identifier():
    assert study.fault_lookup("prefix_matcher", LIVE)("vehicle_id", "V-0007_XX") is True


def test_stale_snapshot_loses_the_stated_fraction_and_invents_nothing():
    look = study.fault_lookup("stale_snapshot", LIVE)
    present = sum(look("vehicle_id", v) for v in LIVE["vehicle_id"])
    assert present == 85
    assert look("vehicle_id", "V-0007_XX") is False


def test_fail_open_answers_exists_for_about_its_rate():
    look = study.fault_lookup("fail_open", LIVE)
    opened = sum(look("vehicle_id", f"X-{i}") is True for i in range(2000))
    assert 0.15 < opened / 2000 < 0.25


def test_partial_export_differs_only_in_what_a_miss_means():
    closed = study.fault_lookup("partial_closed_world", LIVE)
    unknown = study.fault_lookup("partial_unknown", LIVE)
    misses = [v for v in sorted(LIVE["vehicle_id"]) if closed("vehicle_id", v) is False]
    assert len(misses) == 30
    assert all(unknown("vehicle_id", v) is None for v in misses)


def test_committed_result_reports_every_prediction():
    result = json.loads((ROOT / "results/gate_correctness_study_v1.json").read_text(encoding="utf-8"))
    assert set(result["predictions"]) == {f"P{i}" for i in range(1, 8)}
    assert set(result["arms"]) == set(study.ARMS)
    assert all(result["arms"][a]["write_auto_accept"] == 0.0 for a in study.ARMS if a != "no_gate")
