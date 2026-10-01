# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regression tests for the additive evidence-sufficiency-v1.1 corpus and runner."""
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

FROZEN_V1 = {
    "checker.py": "c4ca50aee2b2918b11c6fbde1f8615ca6c6bf1e5b6fa2ac1775f49c5e8c20be0",
    "cases.json": "a0048cc021ab7cd7f7d1b09a93e13c7dbdee9f7a685ea617a112da8af3c88d7e",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load_runner():
    spec = importlib.util.spec_from_file_location("evidence_sufficiency_v1_1_runner", V11 / "run_evidence_sufficiency.py")
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


def test_v1_cases_are_carried_verbatim() -> None:
    v1 = json.loads((V1 / "cases.json").read_text(encoding="utf-8"))["cases"]
    v11 = json.loads((V11 / "cases.json").read_text(encoding="utf-8"))["cases"]
    assert v11[: len(v1)] == v1


def test_new_cases_declare_origin_and_rationale() -> None:
    cases = json.loads((V11 / "cases.json").read_text(encoding="utf-8"))["cases"]
    new = cases[26:]
    assert new, "v1.1 adds cases"
    for case in new:
        assert case["gap"] in {"G1", "G2", "G3", "G4", "G5"}, case["id"]
        assert case["rationale"], case["id"]
        assert case["derived_from"], case["id"]


def test_record_has_no_failures(record: dict) -> None:
    assert record["failures"] == []
    assert record["checker_is_frozen_v1"] is True
    assert record["authored_expectations"]["matched"] == record["authored_expectations"]["total"] == 50


def test_every_checker_reason_is_an_expected_reason(record: dict) -> None:
    coverage = record["reason_coverage"]
    assert coverage["checker_reasons"] == 28
    assert coverage["unreached"] == []
    assert coverage["undeclared_guidance"] == []
    assert coverage["orphan_guidance"] == []


def test_guidance_contract_holds_everywhere(record: dict) -> None:
    assert record["guidance_contract_failures"] == []


def test_every_declared_precedence_pair_is_witnessed(record: dict) -> None:
    assert len(record["precedence_witnesses"]) == 15
    assert all(item["holds"] for item in record["precedence_witnesses"])


def test_every_inconclusive_reason_has_an_isolation_witness(record: dict) -> None:
    assert len(record["isolation_witnesses"]) == 22
    assert all(item["holds"] for item in record["isolation_witnesses"])


def test_erasure_and_shortcut_properties_carry_over(record: dict) -> None:
    checks = record["evidence_erasure_checks"]
    assert checks["inconclusive_strengthening_failures"] == []
    assert checks["polarity_flip_failures"] == []
    assert all(item["rejected"] for item in record["wrong_shortcuts"].values())
    assert all(v["status"] == "not_established" for v in record["empty_observations"].values())


def test_guidance_contract_detects_a_wrong_decisive_if() -> None:
    guidance = json.loads((V11 / "guidance.json").read_text(encoding="utf-8"))["guidance"]
    reason = "observation_window_open"
    verdict = {
        "status": "not_established",
        "reason": reason,
        "missing_evidence": guidance[reason]["missing_evidence"],
        "decisive_if": "something else",
    }
    assert RUNNER.guidance_problem(verdict, guidance) == "decisive_if_differs_from_declared_guidance"
    decisive = {"status": "violated", "reason": "x", "missing_evidence": ["y"]}
    assert RUNNER.guidance_problem(decisive, guidance) == "decisive_verdict_carries_guidance"


def test_reason_vocabulary_is_read_from_source_not_tables() -> None:
    vocab = RUNNER.reason_vocabulary(
        "def f(o):\n"
        "    return _unknown(claim, 'a', scope)\n"
        "def g(o):\n"
        "    return _result(claim, EvidenceStatus.VIOLATED, 'b', scope)\n"
    )
    assert vocab == {"inconclusive": {"a"}, "decisive": {"b"}}


def test_committed_artifact_reproduces_exactly() -> None:
    proc = subprocess.run(
        [sys.executable, str(V11 / "run_evidence_sufficiency.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
