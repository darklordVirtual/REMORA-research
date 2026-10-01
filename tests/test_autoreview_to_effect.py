# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The AutoReview-to-Effect benchmark: REMORA conforms, a naive layer does not.

The naive adapter is the discrimination control. A vector that a
boolean-gate execution layer also passes proves nothing, so the test asserts
divergence there as firmly as it asserts a match for REMORA.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SUITE = Path(__file__).resolve().parents[1] / "conformance" / "autoreview-to-effect-v1"


def _run(adapter: str, out: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SUITE / "run_benchmark.py"), "--adapter", adapter,
         "--out", str(out), *extra],
        capture_output=True, text=True,
    )


def _record(tmp_path_factory: pytest.TempPathFactory, adapter: str) -> dict:
    out = tmp_path_factory.mktemp(adapter) / "run-record.json"
    proc = _run(adapter, out)
    assert proc.returncode == 0, proc.stderr
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def remora(tmp_path_factory: pytest.TempPathFactory) -> dict:
    return _record(tmp_path_factory, "remora")


@pytest.fixture(scope="module")
def naive(tmp_path_factory: pytest.TempPathFactory) -> dict:
    return _record(tmp_path_factory, "naive")


def _suite() -> dict:
    return json.loads((SUITE / "vectors.json").read_text(encoding="utf-8"))


def _ids() -> list[str]:
    return [v["id"] for v in _suite()["vectors"]]


def _adversarial_ids() -> list[str]:
    return [v["id"] for v in _suite()["vectors"] if v["property"] != "control"]


@pytest.mark.parametrize("vector_id", _ids())
def test_remora_matches(remora: dict, vector_id: str) -> None:
    r = next(r for r in remora["results"] if r["id"] == vector_id)
    assert r["status"] == "MATCH", r


def test_remora_blocks_run_nothing(remora: dict) -> None:
    for r in remora["results"]:
        if r["verdict"] == "BLOCK":
            assert r["executions"] == 0, r


def test_no_unmapped_reasons(remora: dict) -> None:
    assert not [r for r in remora["results"] if "UNMAPPED" in r["observed"]]


def test_naive_passes_the_control(naive: dict) -> None:
    control = [v["id"] for v in _suite()["vectors"] if v["property"] == "control"]
    assert control
    for r in naive["results"]:
        if r["id"] in control:
            assert r["status"] == "MATCH", r


@pytest.mark.parametrize("vector_id", _adversarial_ids())
def test_naive_diverges_on_every_adversarial_vector(naive: dict, vector_id: str) -> None:
    r = next(r for r in naive["results"] if r["id"] == vector_id)
    assert r["status"] == "DIVERGENT", r


def test_skeleton_reports_only_unsupported(tmp_path: Path) -> None:
    out = tmp_path / "rr.json"
    assert _run("skeleton", out).returncode == 0
    record = json.loads(out.read_text(encoding="utf-8"))
    assert {r["status"] for r in record["results"]} == {"UNSUPPORTED"}


def test_every_vector_expectation_is_classified() -> None:
    suite = _suite()
    for v in suite["vectors"]:
        assert suite["verdict_of_class"][v["expect"]] == v["expect_verdict"], v["id"]
        assert v["expect"] in suite["outcome_classes"]


def test_committed_record_reproduces() -> None:
    proc = subprocess.run(
        [sys.executable, str(SUITE / "run_benchmark.py"), "--check"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
