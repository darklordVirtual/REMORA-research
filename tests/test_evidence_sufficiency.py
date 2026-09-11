# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regression tests for the additive evidence-sufficiency-v1 research artifact."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "conformance" / "evidence-sufficiency-v1"


def _load_checker():
    spec = importlib.util.spec_from_file_location("evidence_sufficiency_checker", SUITE / "checker.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = _load_checker()


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = tmp_path_factory.mktemp("evidence-sufficiency") / "run-record.json"
    proc = subprocess.run(
        [sys.executable, str(SUITE / "run_evidence_sufficiency.py"), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_authored_expectations_are_regression_checks_not_conformance(record: dict) -> None:
    assert record["authored_expectations"] == {
        "matched": 26,
        "note": "expectation matches are regression checks, not a conformance score",
        "total": 26,
    }
    assert record["record_kind"] == "synthetic-author-run"


def test_property_verdicts_are_kept_separate_from_case_result(record: dict) -> None:
    assert set(record["case_results"].values()) == {"MATCH"}
    assert record["property_verdict_distribution"] == {
        "established": 4,
        "not_established": 18,
        "violated": 4,
    }


def test_indistinguishable_worlds_stay_inconclusive(record: dict) -> None:
    assert all(item["identical_visible_input"] for item in record["indistinguishable_world_pairs"])
    assert all(item["distinct_hidden_truth"] for item in record["indistinguishable_world_pairs"])
    assert all(item["same_nondecisive_verdict"] for item in record["indistinguishable_world_pairs"])


def test_evidence_erasure_never_strengthens_or_flips(record: dict) -> None:
    checks = record["evidence_erasure_checks"]
    assert checks["inconclusive_single_field_removals"] == 150
    assert checks["inconclusive_strengthening_failures"] == []
    assert checks["decisive_single_field_removals"] > 0
    assert checks["polarity_flip_failures"] == []


def test_empty_observations_never_become_decisive(record: dict) -> None:
    assert all(
        verdict["status"] == "not_established"
        for verdict in record["empty_observations"].values()
    )


def test_inconclusive_verdict_explains_what_is_missing() -> None:
    verdict = CHECKER.assess(
        "admission_accounting",
        {
            "effect_source_accepted": True,
            "effect_seen": True,
            "scope_accepted": True,
            "admission_present": False,
            "mandatory_admission": True,
            "window_finalized": True,
            "admission_coverage_complete": False,
        },
    )
    assert verdict.status.value == "not_established"
    assert "complete admission coverage" in verdict.missing_evidence[0]
    assert verdict.decisive_if is not None


def test_production_premises_are_rejected_by_construction() -> None:
    with pytest.raises(ValueError, match="synthetic_fixture"):
        CHECKER.assess(
            "postcondition_observed",
            {},
            premise_source="caller_asserted_production",
        )


def test_committed_artifact_reproduces_exactly() -> None:
    proc = subprocess.run(
        [sys.executable, str(SUITE / "run_evidence_sufficiency.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
