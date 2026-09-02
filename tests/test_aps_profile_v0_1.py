# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from remora.interop.aps.adapter import run_actionref_fixture, run_profile
from remora.interop.aps.mappings import (
    MappingRefused,
    accountability_decision,
    actionref_canonical,
)


def test_actionref_mapping_matches_current_aps_fixture() -> None:
    suite = Path(__file__).resolve().parents[2] / "aps-conformance-suite"
    if not suite.is_dir():
        pytest.skip("APS suite sibling clone is not present")
    report = run_actionref_fixture(
        suite / "fixtures/actionref-canonical/actionref-canonical-fixture-v1.json"
    )
    assert report["summary"] == {
        "vectors": 6,
        "passed": 6,
        "divergences": 0,
        "refused": 0,
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"credential_scope": []},
        {"action_type": ""},
        {"toolspec_bundle_verified": False},
    ],
)
def test_actionref_mapping_fails_closed(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "actor_identity": "principal",
        "action_type": "document.sign",
        "credential_scope": ["repo:write"],
        "issued_at": "2026-07-10T00:00:00Z",
        "toolspec_bundle_verified": True,
    }
    values.update(kwargs)
    with pytest.raises(MappingRefused):
        actionref_canonical(**values)  # type: ignore[arg-type]


def test_core_never_imports_aps_boundary() -> None:
    root = Path(__file__).resolve().parents[1] / "remora"
    for package in ("policy", "enforcement", "execution", "governance"):
        for path in (root / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = [
                node.module or ""
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            ]
            assert not any(name.startswith("remora.interop.aps") for name in imports), path


def test_full_profile_reports_declined_family_without_claiming_it() -> None:
    suite = Path(__file__).resolve().parents[2] / "aps-conformance-suite"
    if not suite.is_dir():
        pytest.skip("APS suite sibling clone is not present")
    report = run_profile(suite)
    assert report["summary"] == {
        "families_declared": 4,
        "families_run": 3,
        "families_not_run": 1,
        "vectors_run": 25,
        "passed": 25,
        "divergences": 0,
        "mapping_checks": 5,
        "mapping_divergences": 0,
    }
    instruction = report["families"][3]
    assert instruction["family"] == "instruction-provenance"
    assert instruction["status"] == "NOT_RUN"


@pytest.mark.parametrize(
    "verdict,executed,resolved,expected",
    [
        ("ACCEPT", True, False, ("allow", True)),
        ("ACCEPT", False, False, ("allow", False)),
        ("VERIFY", False, False, ("halt", False)),
        ("ESCALATE", False, True, ("deny", False)),
        ("ABSTAIN", False, False, ("deny", False)),
    ],
)
def test_frozen_accountability_mapping(
    verdict: str, executed: bool, resolved: bool, expected: tuple[str, bool]
) -> None:
    assert accountability_decision(
        remora_verdict=verdict,
        executed=executed,
        review_resolved_as_refused=resolved,
    ) == expected
