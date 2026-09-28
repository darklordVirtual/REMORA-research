# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The ledger binding gate fails on each way a number can lose its artifact (Q1.5)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_ledger_bindings as gate  # noqa: E402


def _tree(tmp_path: Path, claims: dict, artifacts: dict, baseline: list[str] | None = None) -> Path:
    for rel, data in artifacts.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / gate.LEDGER).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / gate.LEDGER).write_text(yaml.safe_dump({"claims": claims}), encoding="utf-8")
    (tmp_path / gate.BASELINE).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / gate.BASELINE).write_text(json.dumps(
        {"schema_version": 1, "entries": [{"id": b, "reason": "t"} for b in baseline or []]}), encoding="utf-8")
    return tmp_path


ART = {"results/a.json": {"accuracy": 0.9604, "rho": -0.0102, "n": 101}}


def _claim(wording: str, **extra) -> dict:
    return {"c": {"status": "supported", "wording": wording, "artifact": "results/a.json", **extra}}


def test_numbers_that_are_fields_pass(tmp_path):
    root = _tree(tmp_path, _claim("accuracy 96.04% with rho = -0.0102"), ART)
    assert gate.main(["--root", str(root)]) == 0


def test_precision_is_the_written_precision(tmp_path):
    root = _tree(tmp_path, _claim("accuracy 96.0%"), ART)
    assert gate.unbound_numbers(root)[0] == []


def test_a_stale_number_fails(tmp_path):
    root = _tree(tmp_path, _claim("accuracy 88.78%"), ART)
    assert gate.unbound_numbers(root)[0] == ["c:88.78%"]
    assert gate.main(["--root", str(root)]) == 1


def test_declared_parameters_and_retired_values_are_allowed(tmp_path):
    claims = _claim("threshold 0.1972; the old run gave 88.78%",
                    parameters=["0.1972"], retired_values=["88.78%"])
    assert gate.unbound_numbers(_tree(tmp_path, claims, ART))[0] == []


def test_also_cites_extends_the_artifacts(tmp_path):
    arts = {**ART, "results/b.json": {"coverage": 0.186}}
    claims = _claim("coverage 18.6%", also_cites="results/b.json")
    assert gate.unbound_numbers(_tree(tmp_path, claims, arts))[0] == []


def test_baseline_only_shrinks(tmp_path):
    root = _tree(tmp_path, _claim("accuracy 96.04%"), ART, baseline=["c:88.78%"])
    assert gate.main(["--root", str(root)]) == 1  # stale baseline entry


def test_missing_cited_artifact_fails(tmp_path):
    root = _tree(tmp_path, {"c": {"wording": "x 50%", "artifact": "results/gone.json"}}, {})
    assert gate.unbound_numbers(root)[1] == ["c: cited artifact results/gone.json does not exist"]


def test_the_repository_ledger_passes():
    assert gate.main(["--root", str(ROOT)]) == 0
