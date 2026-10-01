# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regression tests for the safety-case evidence profile v0.1."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "conformance" / "safety-case-evidence-profile-v0.1"
V1 = ROOT / "conformance" / "evidence-sufficiency-v1"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = _load("safety_case_profile_checker", PROFILE / "profile_checker.py")
RUNNER = _load("safety_case_profile_runner", PROFILE / "run_profile.py")


@pytest.fixture(scope="module")
def record() -> dict:
    return RUNNER.build_record()


def _cases() -> list[dict]:
    return json.loads((PROFILE / "cases.json").read_text(encoding="utf-8"))["cases"]


def test_record_has_no_failures(record: dict) -> None:
    assert record["failures"] == []


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["id"])
def test_case_matches_expectation(case: dict) -> None:
    v = CHECKER.assess(case["claim"], case["independent_verification"])
    assert (v.verdict.value, v.reason) == (case["expected"]["verdict"], case["expected"]["reason"])


def test_case_ids_unique() -> None:
    ids = [c["id"] for c in _cases()]
    assert len(ids) == len(set(ids))


def test_every_claim_has_every_verdict(record: dict) -> None:
    for claim, counts in record["verdict_coverage"].items():
        assert all(n > 0 for n in counts.values()), claim


def test_producer_evidence_never_moves_a_verdict(record: dict) -> None:
    assert record["producer_invariance"]["checks"] > 0
    assert record["producer_invariance"]["failures"] == []


def test_assess_does_not_accept_producer_evidence() -> None:
    import inspect

    params = set(inspect.signature(CHECKER.assess).parameters)
    assert not any("producer" in p for p in params)


def test_decisive_verdicts_carry_a_bounded_downstream_claim(record: dict) -> None:
    for t in record["traces"]:
        if t["verdict"] == "NOT_ESTABLISHED":
            assert t["permitted_downstream_claim"] is None, t["id"]
            assert t["evidence_sufficiency"]["missing_evidence"], t["id"]
            assert t["evidence_sufficiency"].get("decisive_if"), t["id"]
        else:
            assert t["permitted_downstream_claim"], t["id"]


def test_delegated_claims_agree_with_frozen_v1() -> None:
    v1 = _load("es_v1_checker_for_profile_test", V1 / "checker.py")
    for case in _cases():
        v1_claim = CHECKER.DELEGATED.get(case["claim"])
        if v1_claim is None:
            continue
        ours = CHECKER.assess(case["claim"], case["independent_verification"])
        theirs = v1.assess(v1_claim, case["independent_verification"])
        assert ours.reason == theirs.reason, case["id"]
        assert ours.verdict.value == {
            "established": "SUPPORTED", "violated": "REFUTED", "not_established": "NOT_ESTABLISHED",
        }[theirs.status.value], case["id"]


def test_v1_checker_hash_is_recorded(record: dict) -> None:
    digest = hashlib.sha256((V1 / "checker.py").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert record["inputs_sha256"]["evidence-sufficiency-v1/checker.py"] == digest


def test_non_synthetic_premises_are_refused() -> None:
    with pytest.raises(ValueError):
        CHECKER.assess("monitor_active", {}, premise_source="production")


def test_heartbeat_alone_is_not_detection() -> None:
    premises = {
        "heartbeat_observation_accepted": True, "scope_accepted": True,
        "declared_max_gap_s": 30, "observed_max_gap_s": 1,
        "window_finalized": True, "heartbeat_coverage_complete": True,
    }
    assert CHECKER.assess("monitor_active", premises).verdict.value == "NOT_ESTABLISHED"


def test_committed_record_reproduces() -> None:
    proc = subprocess.run(
        [sys.executable, str(PROFILE / "run_profile.py"), "--check"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
