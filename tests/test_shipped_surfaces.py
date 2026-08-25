# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The shipped-surfaces matrix must bind to workflows that actually run.

A matrix nothing validates drifts on the first workflow rename: the register
keeps claiming a contract that no longer runs, which is exactly the failure a
shipped-surfaces statement exists to prevent (issue #84).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_shipped_surfaces.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("shipped_surfaces", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_register_is_clean(gate) -> None:
    assert gate.main() == 0


def test_every_reference_resolves_to_a_live_job(gate) -> None:
    """Job ids, not display names: ids survive renames, which is what makes
    them bindable."""
    register = yaml.safe_load(
        (ROOT / "docs/assurance/shipped_surfaces_v1.yaml").read_text(encoding="utf-8")
    )
    jobs = gate.workflow_jobs()
    for surface in register["surfaces"]:
        for contract in surface["contracts"]:
            wf, job_id = contract["job"].split(":", 1)
            assert job_id in jobs[wf], (surface["name"], contract["job"])


def test_the_issue_84_surface_set_is_present(gate) -> None:
    """The surfaces #84 names must all appear: source checkout, wheel, CLI,
    REST assess, execution API with SQLite and Postgres, frontend, workers."""
    register = yaml.safe_load(
        (ROOT / "docs/assurance/shipped_surfaces_v1.yaml").read_text(encoding="utf-8")
    )
    names = {s["name"] for s in register["surfaces"]}
    required = {
        "source-checkout", "wheel", "cli", "rest-assess",
        "execution-api-sqlite", "execution-api-postgres", "frontend", "workers",
    }
    assert required <= names, required - names


def test_the_baseline_matches_the_surface_count(gate) -> None:
    """The ratchet only holds if the baseline is kept at the count: a baseline
    below the count leaves silent-removal headroom."""
    register = yaml.safe_load(
        (ROOT / "docs/assurance/shipped_surfaces_v1.yaml").read_text(encoding="utf-8")
    )
    assert register["surface_baseline"] == len(register["surfaces"])


def test_a_dangling_job_reference_is_refused(gate, tmp_path, monkeypatch) -> None:
    bad = {
        "schema_version": "1",
        "surface_baseline": 1,
        "surfaces": [{
            "name": "ghost",
            "contracts": [
                {"kind": "smoke", "job": "ci.yml:job-that-does-not-exist"},
                {"kind": "test", "job": "ci.yml:test"},
            ],
        }],
    }
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    monkeypatch.setattr(gate, "REGISTER", p)
    assert gate.main() == 1


def test_removing_a_surface_below_the_baseline_is_refused(
    gate, tmp_path, monkeypatch
) -> None:
    bad = {
        "schema_version": "1",
        "surface_baseline": 2,
        "surfaces": [{
            "name": "only-one",
            "contracts": [
                {"kind": "smoke", "job": "ci.yml:test"},
                {"kind": "test", "job": "ci.yml:test"},
            ],
        }],
    }
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    monkeypatch.setattr(gate, "REGISTER", p)
    assert gate.main() == 1


def test_a_surface_without_a_functional_check_is_refused(
    gate, tmp_path, monkeypatch
) -> None:
    """Smoke alone proves it starts; type/lint/test prove it works."""
    bad = {
        "schema_version": "1",
        "surface_baseline": 1,
        "surfaces": [{
            "name": "smoke-only",
            "contracts": [{"kind": "smoke", "job": "ci.yml:test"}],
        }],
    }
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    monkeypatch.setattr(gate, "REGISTER", p)
    assert gate.main() == 1
