# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regression tests for the additive evidence-sufficiency-v1.2 corpus and runner."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "conformance" / "evidence-sufficiency-v1"
V11 = ROOT / "conformance" / "evidence-sufficiency-v1.1"
V12 = ROOT / "conformance" / "evidence-sufficiency-v1.2"

FROZEN_V1 = {
    "checker.py": "c4ca50aee2b2918b11c6fbde1f8615ca6c6bf1e5b6fa2ac1775f49c5e8c20be0",
    "cases.json": "a0048cc021ab7cd7f7d1b09a93e13c7dbdee9f7a685ea617a112da8af3c88d7e",
}
# v1.1 as merged in 8772d85. The external run measured 57ee0351; the cases, guidance and
# ladders are byte-identical, and the runner differs only in one limits string.
FROZEN_V11 = {
    "cases.json": "ffc453c3f4cf90a39374ee574086827974ad5e0f221e4cfdaef5f9acb5068521",
    "guidance.json": "eeb951e7073e7cc108a1d4886c4d03080b010287321a934f97ad763bb772542c",
    "ladders.json": "e5b5cd88356625b0593062736fb2a386fe36e9334004e99f34e5861f10acd400",
    "run_evidence_sufficiency.py": "a007df2910b99c62b9fcd4a38eae1e2bec0e9b41a5c5b8dd9ef30a50149eaa88",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _cases(directory: Path) -> list[dict]:
    return json.loads((directory / "cases.json").read_text(encoding="utf-8"))["cases"]


def _load_runner():
    spec = importlib.util.spec_from_file_location("evidence_sufficiency_v1_2_runner", V12 / "run_evidence_sufficiency.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


@pytest.fixture(scope="module")
def record() -> dict:
    return RUNNER.build_record()


def test_v1_tested_bytes_are_frozen() -> None:
    for name, digest in FROZEN_V1.items():
        assert _sha(V1 / name) == digest, name


def test_v11_tested_bytes_are_frozen() -> None:
    for name, digest in FROZEN_V11.items():
        assert _sha(V11 / name) == digest, name


def test_v11_guidance_and_ladders_are_carried_byte_for_byte() -> None:
    for name in ("guidance.json", "ladders.json"):
        assert _sha(V12 / name) == _sha(V11 / name), name


def test_v11_cases_are_carried_verbatim() -> None:
    v11 = _cases(V11)
    assert _cases(V12)[: len(v11)] == v11


def test_new_cases_pin_exact_state_comparison() -> None:
    new = _cases(V12)[len(_cases(V11)):]
    assert [case["id"] for case in new] == ["E18", "E19", "E20"]
    for case in new:
        assert case["gap"] == "H1", case["id"]
        assert case["derived_from"] == "E02", case["id"]
        assert case["rationale"], case["id"]
        assert case["claim"] == "postcondition_observed", case["id"]
        assert case["expected"] == {
            "reason": "declared_postcondition_disagreed_at_named_point",
            "status": "violated",
        }, case["id"]
        obs = case["observations"]
        assert obs["expected_state"] != obs["observed_state"], case["id"]


# The three withheld faults from the external v1.1 run (corpus-adequacy/remora-es-v11-adequacy
# at 9f38519, additional-faults-FROZEN.json). Each one merges states that differ.
CANONICAL = 'return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)'
CANONICAL_FAULTS = {
    "case_folded": (
        'return json.dumps(value.casefold() if isinstance(value, str) else value, '
        'sort_keys=True, separators=(",", ":"), ensure_ascii=False)'
    ),
    "list_order_erased": (
        "return json.dumps(sorted(value, key=lambda x: json.dumps(x, sort_keys=True)) "
        'if isinstance(value, list) else value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)'
    ),
    "mapping_values_ignored": (
        "return json.dumps(sorted(value.keys()) if isinstance(value, dict) else value, "
        'sort_keys=True, separators=(",", ":"), ensure_ascii=False)'
    ),
}


def _faulty_checker(tmp_path: Path, replacement: str):
    source = (V1 / "checker.py").read_text(encoding="utf-8")
    assert source.count(CANONICAL) == 1
    path = tmp_path / "checker.py"
    path.write_text(source.replace(CANONICAL, replacement), encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"faulty_checker_{tmp_path.name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("fault", sorted(CANONICAL_FAULTS))
def test_each_canonical_fault_is_told_apart_by_a_new_case(tmp_path: Path, fault: str) -> None:
    faulty = _faulty_checker(tmp_path, CANONICAL_FAULTS[fault])
    new = _cases(V12)[len(_cases(V11)):]
    divergent = [
        case["id"]
        for case in new
        if faulty.assess(case["claim"], case["observations"]).as_dict()["status"] != case["expected"]["status"]
    ]
    assert divergent, f"{fault} survives the v1.2 cases"


def test_record_has_no_failures(record: dict) -> None:
    assert record["failures"] == []
    assert record["checker_is_frozen_v1"] is True
    assert record["authored_expectations"]["matched"] == record["authored_expectations"]["total"] == 53


def test_v11_runner_properties_carry_over(record: dict) -> None:
    assert record["reason_coverage"]["unreached"] == []
    assert record["guidance_contract_failures"] == []
    assert len(record["precedence_witnesses"]) == 15
    assert all(item["holds"] for item in record["precedence_witnesses"])
    assert len(record["isolation_witnesses"]) == 22
    assert all(item["holds"] for item in record["isolation_witnesses"])
    checks = record["evidence_erasure_checks"]
    assert checks["inconclusive_strengthening_failures"] == []
    assert checks["polarity_flip_failures"] == []


def test_record_discloses_that_h1_was_written_after_the_faults(record: dict) -> None:
    assert any("H1" in limit and "not independent evidence" in limit for limit in record["limits"])


def test_committed_artifact_reproduces_exactly() -> None:
    proc = subprocess.run(
        [sys.executable, str(V12 / "run_evidence_sufficiency.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
