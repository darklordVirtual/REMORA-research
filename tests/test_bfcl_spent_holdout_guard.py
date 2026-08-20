# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""SAP v5 §10: a spent BFCL holdout can never be presented as blind again.

Pins (a) the C-ext2 manifest on disk is permanently 'evaluated'; (b) the
runner's run() refuses an evaluated manifest and anything not
locked_never_run; (c) the frozen 28/258 result artifact still carries the
exact baseline numbers the README/claim register cite, split cleanly from
the constructed wrong-tool mutants.
"""
from __future__ import annotations

import pytest

import json
import sys
from pathlib import Path

#: Documentation/register consistency gate, not a behaviour test.
#: Split out so a documentation drift and a governance regression do
#: not fail the same way (self-review 2026-08-20).
pytestmark = pytest.mark.docgate

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = _ROOT / "data" / "routing_bench_bfcl_v4" / "manifest.json"
_RESULT = _ROOT / "results" / "routing_bench_bfcl_v4_results.json"


def test_cext2_manifest_is_permanently_evaluated() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "evaluated", (
        "the spent C-ext2 holdout must never be re-armed as blind"
    )


def _patched_runner(tmp_path: Path, monkeypatch, status: str):
    import scripts.run_bfcl_holdout as runner

    (tmp_path / "manifest.json").write_text(
        json.dumps({"status": status}), encoding="utf-8"
    )
    monkeypatch.setattr(runner, "HOLDOUT", tmp_path)
    return runner


def test_runner_refuses_an_evaluated_manifest(tmp_path: Path, monkeypatch) -> None:
    runner = _patched_runner(tmp_path, monkeypatch, "evaluated")
    assert runner.run() != 0, "run() must refuse a spent holdout"


def test_runner_refuses_anything_not_locked(tmp_path: Path, monkeypatch) -> None:
    runner = _patched_runner(tmp_path, monkeypatch, "sealed_never_run")
    assert runner.run() != 0, "run() must require an explicit lock step first"


def test_frozen_baseline_numbers_are_intact_and_split() -> None:
    result = json.loads(_RESULT.read_text(encoding="utf-8"))
    wrong = result["targets"]["known_wrong_call_accept"]
    assert (wrong["n"], wrong["d"]) == (28, 258)
    fam = result["predicted_by_family"]
    native = fam["native:substituted"]
    assert native["accept"] == 28 and sum(native.values()) == 258
    mutants = fam["wrong_tool"]
    assert mutants["accept"] == 6 and sum(mutants.values()) == 99
    # The two populations must stay separable in the frozen artifact — the
    # 28/258 headline is the native metric alone.
    assert wrong["d"] == sum(native.values())
