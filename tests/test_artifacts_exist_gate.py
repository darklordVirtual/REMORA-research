# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The artifact-existence gate must cover the remediation register too.

A documentation audit on 2026-09-02 found REM-019, a P0 release blocker,
citing ``scripts/run_false_accept_regression.py`` and
``tests/test_false_accept_regression.py`` as its evidence. Neither has ever
existed in this repository. Nothing checked those pointers, so the drift was
invisible for months. These tests pin the check that closes that hole.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

#: Register/artifact consistency gate, not a behaviour test.
pytestmark = pytest.mark.docgate

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_artifacts_exist.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_artifacts_exist", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_artifacts_exist"] = module
    spec.loader.exec_module(module)
    return module


def test_remediation_register_is_read_at_all() -> None:
    """The register must yield artifact refs, or the gate is a no-op."""
    module = _load()
    refs = module.remediation_artifact_refs()
    assert refs, "no artifacts parsed from remediation_register.yaml"
    ids = {rem_id for rem_id, _ in refs}
    assert "REM-019" in ids, "the P0 blocker that motivated this gate is not covered"


def test_every_remediation_artifact_exists() -> None:
    """Live repository state: no REM entry may cite a file that is absent."""
    module = _load()
    missing = [
        f"{rem_id}: {ref}"
        for rem_id, ref in module.remediation_artifact_refs()
        if not (ROOT / ref).exists()
    ]
    assert not missing, (
        "remediation_register.yaml cites evidence that does not exist here: "
        + ", ".join(missing)
    )


def test_missing_artifact_fails_the_gate(monkeypatch, capsys) -> None:
    """A fabricated pointer must fail, not warn."""
    module = _load()
    monkeypatch.setattr(
        module,
        "remediation_artifact_refs",
        lambda: [("REM-999", "results/this_file_does_not_exist.json")],
    )
    with pytest.raises(SystemExit) as excinfo:
        module.check_remediation_register()
    assert excinfo.value.code == 1
    assert "REM-999" in capsys.readouterr().out


def test_urls_are_not_treated_as_paths() -> None:
    """An endpoint recorded as an artifact is not a repository file."""
    module = _load()
    assert module.REMEDIATION_REGISTER.exists()
    refs = module.remediation_artifact_refs()
    assert all("://" not in ref for _, ref in refs)
