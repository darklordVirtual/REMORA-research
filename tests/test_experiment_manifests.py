# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Experiment-manifest gate tests.

Manifests give every experiment traceable hypothesis/status/artifact metadata
without production-grade ceremony. Malformed manifests fail HARD (they are
machine-readable registers); missing manifests and missing provenance
sidecars are ADVISORY (a backlog, not a build breaker).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_experiment_manifests.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_experiment_manifests", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_repository_passes_experiment_manifest_gate() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT
    )
    assert proc.returncode == 0, proc.stderr


def test_agentharm_manifest_exists_and_is_valid() -> None:
    path = ROOT / "experiments" / "agentharm" / "experiment_manifest.yaml"
    assert path.is_file()
    with open(path, encoding="utf-8") as f:
        m = yaml.safe_load(f)
    for key in ("experiment_id", "title", "status", "hypothesis", "result_artifacts"):
        assert key in m, key


def test_missing_required_key_is_hard_error(tmp_path: Path) -> None:
    mod = _load_module()
    d = tmp_path / "experiments" / "exp1"
    d.mkdir(parents=True)
    (d / "experiment_manifest.yaml").write_text(
        "experiment_id: EXP-TEST-1\ntitle: t\nstatus: exploratory\n",
        encoding="utf-8",
    )
    mod.ROOT = tmp_path
    errors: list[str] = []
    warnings: list[str] = []
    mod.check_manifests(errors, warnings)
    assert any("hypothesis" in e for e in errors), errors


def test_unknown_status_is_hard_error(tmp_path: Path) -> None:
    mod = _load_module()
    d = tmp_path / "experiments" / "exp1"
    d.mkdir(parents=True)
    (d / "experiment_manifest.yaml").write_text(
        "experiment_id: EXP-TEST-1\ntitle: t\nstatus: production_ready\n"
        "hypothesis: h\nresult_artifacts: []\n",
        encoding="utf-8",
    )
    mod.ROOT = tmp_path
    errors: list[str] = []
    warnings: list[str] = []
    mod.check_manifests(errors, warnings)
    assert any("status" in e for e in errors), errors


def test_missing_artifact_and_sidecar_warn_not_fail(tmp_path: Path) -> None:
    mod = _load_module()
    d = tmp_path / "experiments" / "exp1"
    d.mkdir(parents=True)
    (d / "experiment_manifest.yaml").write_text(
        "experiment_id: EXP-TEST-1\ntitle: t\nstatus: exploratory\n"
        "hypothesis: h\nresult_artifacts:\n- results/not_yet_generated.json\n",
        encoding="utf-8",
    )
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "orphan.json").write_text("{}", encoding="utf-8")
    mod.ROOT = tmp_path
    errors: list[str] = []
    warnings: list[str] = []
    mod.check_manifests(errors, warnings)
    mod.check_provenance_coverage(warnings)
    assert errors == [], errors
    assert any("not_yet_generated.json" in w for w in warnings), warnings
    assert any("provenance" in w for w in warnings), warnings


def test_duplicate_experiment_id_is_hard_error(tmp_path: Path) -> None:
    mod = _load_module()
    for name in ("exp1", "exp2"):
        d = tmp_path / "experiments" / name
        d.mkdir(parents=True)
        (d / "experiment_manifest.yaml").write_text(
            "experiment_id: EXP-DUP-1\ntitle: t\nstatus: exploratory\n"
            "hypothesis: h\nresult_artifacts: []\n",
            encoding="utf-8",
        )
    mod.ROOT = tmp_path
    errors: list[str] = []
    warnings: list[str] = []
    mod.check_manifests(errors, warnings)
    assert any("duplicate" in e.lower() and "EXP-DUP-1" in e for e in errors), errors
