# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Evidence-sufficiency v1.4: v1.3 verbatim plus the rule-coverage cases (v1.3 spec, section 14).

v1.3 is frozen by this change. v1.4 must carry it byte for byte, add exactly the
cases the pre-registered derivation rule produces, and fail on any rule-coverage
obligation of the model that no authored case discharges.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V13 = ROOT / "conformance" / "evidence-sufficiency-v1.3"
V14 = ROOT / "conformance" / "evidence-sufficiency-v1.4"

# v1.3 as measured by specification mutation (section 13) and by the independent
# analysis of 2026-09-30; the README is prose and is not pinned.
FROZEN_V13 = {
    "cases.json": "7fc6d42459fc019d84f9b9b723b7f312f1db9a9c2edebf3ad1f9e4a38da1fb81",
    "guidance.json": "eeb951e7073e7cc108a1d4886c4d03080b010287321a934f97ad763bb772542c",
    "ladders.json": "e5b5cd88356625b0593062736fb2a386fe36e9334004e99f34e5861f10acd400",
    "invariants.json": "15ba2341280b09e7b2dd44e93c1a0b185b4209f0a0c4f6c351f8d92a633bd687",
    "model.json": "861e5dc80ff1983e2b3a640ad0f20b340fb0157c6ecfc6df259d1c2083dba201",
    "run_evidence_sufficiency.py": "68b1dc872c5d67f8b17a9d547df6e1449ab8a6c016aee0292f812819eb8a30e3",
    "run-record.json": "3d907900dc7377f08d68ba35c10639644f3b4a5c5ca177870785342b7cb3d775",
}
#: The digest section 14.3 of the v1.3 spec pre-registered for the derived cases.
DERIVED_SHA256 = "2b1838624cdacdf29a0fff461fcb5913497eebec8c5f5a31bb24e2d4c5b361df"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _cases(directory: Path) -> list[dict]:
    return json.loads((directory / "cases.json").read_text(encoding="utf-8"))["cases"]


RUNNER = _load("evidence_sufficiency_v1_4_runner", V14 / "run_evidence_sufficiency.py")
RC = _load("rule_coverage_for_v1_4_tests", ROOT / "scripts" / "rule_coverage_evidence_sufficiency.py")


@pytest.fixture(scope="module")
def record() -> dict:
    return RUNNER.build_record()


def test_v13_is_frozen() -> None:
    for name, digest in FROZEN_V13.items():
        assert _sha(V13 / name) == digest, name


def test_v13_tables_and_model_are_carried_byte_for_byte() -> None:
    for name in ("guidance.json", "ladders.json", "invariants.json", "model.json"):
        assert _sha(V14 / name) == _sha(V13 / name), name


def test_v13_cases_are_carried_verbatim_and_in_order() -> None:
    before, after = _cases(V13), _cases(V14)
    assert after[: len(before)] == before
    corpus = json.loads((V14 / "cases.json").read_text(encoding="utf-8"))
    assert corpus["base_corpus"]["sha256"] == FROZEN_V13["cases.json"]
    assert corpus["base_corpus"]["cases_carried_verbatim"] == len(before)
    assert corpus["rejections"] == json.loads((V13 / "cases.json").read_text(encoding="utf-8"))["rejections"]


def test_new_cases_are_exactly_the_pre_registered_derivation() -> None:
    before, after = _cases(V13), _cases(V14)
    new = after[len(before):]
    text = json.dumps(new, indent=2, ensure_ascii=False) + "\n"
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == DERIVED_SHA256
    assert new == RC.derive(RC.load_model("evidence-sufficiency-v1.3"), before)
    for case in new:
        assert case["gap"] == "L1" and case["obligations"] and case["rationale"], case["id"]


def test_record_has_no_failures_and_every_obligation_is_discharged(record: dict) -> None:
    assert record["failures"] == []
    assert record["crashes"] == []
    coverage = record["rule_coverage"]
    assert coverage["open"] == []
    assert coverage["discharged"] == coverage["obligations"] == len(RC.obligations(RC.load_model("evidence-sufficiency-v1.4")))
    assert record["reference_model"]["disagreement_count"] == 0


def test_runner_and_script_define_the_same_obligations() -> None:
    model = RUNNER.load_json(V14 / "model.json")
    runner_view = [(o["rule"], o["claim"], tuple(o["outcome"]), o["premise"], tuple(sorted(o["path"].items())))
                   for o in RUNNER.rule_obligations(model)]
    script_view = [(o["rule"], o["claim"], tuple(o["outcome"]), o["premise"], tuple(sorted(o["path"].items())))
                   for o in RC.obligations(model)]
    assert runner_view == script_view
    for ours, theirs in zip(RUNNER.rule_obligations(model), RC.obligations(model)):
        for cases in (_cases(V13), _cases(V14)):
            assert RUNNER.rule_discharged(ours, cases) == RC.covered(theirs, cases)


def test_the_rule_coverage_section_fails_on_the_v1_3_corpus() -> None:
    # With v1.3's cases the v1.4 runner must name every obligation section 14.2 counts as open.
    load = RUNNER.load_json

    def v13_cases(path: Path):
        return load(V13 / "cases.json") if path.name == "cases.json" else load(path)

    RUNNER.load_json = v13_cases
    try:
        failures = RUNNER.build_record()["failures"]
    finally:
        RUNNER.load_json = load
    open_labels = sorted(f for f in failures if f.startswith("rule_coverage:"))
    expected = sorted(
        f"rule_coverage:{o['rule']}:{o['claim']}:{o['outcome'][1]}:{o['premise']}"
        for o in RC.uncovered(RC.load_model("evidence-sufficiency-v1.3"), _cases(V13))
    )
    assert open_labels == expected and len(expected) == 22
    assert [f for f in failures if not f.startswith("rule_coverage:")] == []


def test_record_discloses_that_the_l1_cases_are_fitted(record: dict) -> None:
    assert any("gap L1" in limit and "not independent evidence" in limit for limit in record["limits"])


def test_committed_artifact_reproduces_exactly() -> None:
    proc = subprocess.run(
        [sys.executable, str(V14 / "run_evidence_sufficiency.py"), "--check"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
