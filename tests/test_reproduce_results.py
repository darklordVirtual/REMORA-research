# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The CI regeneration check ignores only declared volatile fields (Q1.2)."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import reproduce_results as rr  # noqa: E402

COMMITTED = {
    "timestamp": "2026-06-01",
    "baselines": {"a": {"rate": 0.0, "performance": {"elapsed_seconds": 1.2}},
                  "b": {"rate": 0.1, "performance": {"elapsed_seconds": 3.4}}},
}
ENTRY = {"path": "results/x.json", "class": "regenerable",
         "volatile": [".timestamp", ".baselines.*.performance.elapsed_seconds"]}


def _regenerated(**changes):
    new = copy.deepcopy(COMMITTED)
    new["timestamp"] = "2026-09-28"
    new["baselines"]["a"]["performance"]["elapsed_seconds"] = 9.9
    for key, value in changes.items():
        new["baselines"][key]["rate"] = value
    return new


def test_declared_volatile_fields_are_ignored():
    assert rr.compare_entry(ENTRY, copy.deepcopy(COMMITTED), _regenerated()) == []


def test_a_changed_number_is_reported_with_its_path():
    assert rr.compare_entry(ENTRY, copy.deepcopy(COMMITTED), _regenerated(b=0.2)) == [".baselines.b.rate"]


def test_undeclared_volatile_field_is_a_difference():
    entry = {**ENTRY, "volatile": [".timestamp"]}
    changed = rr.compare_entry(entry, copy.deepcopy(COMMITTED), _regenerated())
    assert changed == [".baselines.a.performance.elapsed_seconds"]


def test_added_or_removed_fields_and_list_length_are_differences():
    new = _regenerated()
    new["baselines"]["c"] = {"rate": 0.0}
    assert rr.compare_entry(ENTRY, copy.deepcopy(COMMITTED), new) == [".baselines.c"]
    assert rr._diff([1, 2], [1, 2, 3]) == ["[len]"]


def test_repository_manifest_gives_ci_something_to_check():
    entries = rr._entries()
    assert len(entries) >= 30
    assert all(rr.ROUND_MARKER not in e["verified_by"] for e in entries)
    generators = {e["generator"] for e in entries}
    assert all(g.startswith("python ") for g in generators)
