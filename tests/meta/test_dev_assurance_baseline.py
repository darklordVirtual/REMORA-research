# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""S0: pin the initial DEV requirement-to-test inventory without inflating claims.

These checks concern the completeness and honesty of the inventory, not the
runtime correctness of the mapped security controls.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "conformance/dev_assurance_s0/baseline.json"
EXPECTED = {f"INV-{i:02d}" for i in range(1, 15)}
VALID_STATE = "NOT_ESTABLISHED_IN_DEPLOYMENT"


def check_manifest(record: dict[str, Any], *, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    if record.get("schema") != "remora-dev-assurance-s0-v1":
        errors.append("unknown schema")
    baseline = record.get("baseline", {})
    if baseline.get("branch") != "dev":
        errors.append("source branch is not dev")
    commit = baseline.get("commit", "")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        errors.append("baseline commit must be a full 40-digit hex SHA")
    if record.get("evidence_level") != "REFERENCE_TEST_INVENTORY_ONLY":
        errors.append("evidence level must not claim tested deployment behavior")
    if record.get("execution_result") != "NOT_RUN_BY_THIS_MANIFEST":
        errors.append("inventory must not claim to execute tests")
    if record.get("implementation_progress") != "NOT_ASSESSED":
        errors.append("inventory must not claim completed implementation")
    inv = record.get("invariants")
    if not isinstance(inv, list):
        return errors + ["invariants must be a list"]
    names = [r.get("id") for r in inv if isinstance(r, dict)]
    if len(names) != len(inv) or set(names) != EXPECTED or len(names) != len(set(names)):
        errors.append("invariant IDs must match INV-01 to INV-14 exactly once")
    for entry in inv:
        if not isinstance(entry, dict):
            errors.append("malformed invariant entry")
            continue
        key = entry.get("id", "?")
        if entry.get("coverage") != VALID_STATE:
            errors.append(f"{key}: unsupported coverage promotion")
        gap = entry.get("open_gap")
        if not isinstance(gap, str) or len(gap.strip()) < 30:
            errors.append(f"{key}: missing explicit gap statement")
        refs = entry.get("reference_tests")
        if not isinstance(refs, list) or not refs:
            errors.append(f"{key}: no related tests")
            continue
        for rel in refs:
            if not isinstance(rel, str) or not rel.startswith("tests/") or not rel.endswith(".py"):
                errors.append(f"{key}: invalid test path {rel!r}")
            elif not (root / rel).is_file():
                errors.append(f"{key}: absent test file {rel}")
    return errors


def test_s0_inventory_is_complete_and_conservatively_scoped() -> None:
    record = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert check_manifest(record) == []


def test_s0_inventory_rejects_unearned_promotions_and_missing_tests() -> None:
    source = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cases = []
    changed = copy.deepcopy(source)
    changed["invariants"][0]["coverage"] = "ENFORCED_PRODUCTION"
    cases.append(changed)
    changed = copy.deepcopy(source)
    changed["invariants"][0]["reference_tests"] = ["tests/no_such_proof.py"]
    cases.append(changed)
    changed = copy.deepcopy(source)
    changed["invariants"].append(copy.deepcopy(changed["invariants"][0]))
    cases.append(changed)
    changed = copy.deepcopy(source)
    changed["execution_result"] = "PASSED"
    cases.append(changed)
    changed = copy.deepcopy(source)
    changed["invariants"][3]["open_gap"] = ""
    cases.append(changed)
    for corrupted in cases:
        assert check_manifest(corrupted), "a false assurance promotion was accepted"
