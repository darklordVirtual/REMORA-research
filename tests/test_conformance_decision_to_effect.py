# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The decision-to-effect conformance suite runs green against REMORA.

This suite is sent to external reviewers as evidence, so a regression here is a
correctness change in something already claimed. The test asserts per vector
rather than on a count, so a failure names the property that moved.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SUITE = Path(__file__).resolve().parents[1] / "conformance" / "decision-to-effect-v1"


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = tmp_path_factory.mktemp("d2e") / "run-record.json"
    proc = subprocess.run(
        [sys.executable, str(SUITE / "run_conformance.py"),
         "--adapter", "remora", "--out", str(out)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def _vector_ids() -> list[str]:
    suite = json.loads((SUITE / "vectors.json").read_text(encoding="utf-8"))
    return [v["id"] for v in suite["vectors"]]


@pytest.mark.parametrize("vector_id", _vector_ids())
def test_vector_matches_expectation(record: dict, vector_id: str) -> None:
    result = next(r for r in record["results"] if r["id"] == vector_id)
    assert result["status"] == "MATCH", (
        f"{vector_id} ({result['title']}, property {result['property']}): "
        f"expected {result['expected']}, observed {result['observed']}"
    )


def test_no_unmapped_refusal_reasons(record: dict) -> None:
    """An UNMAPPED reason means REMORA grew a refusal the adapter cannot name.

    Left alone it would eventually be classified as something it is not, which
    is the failure the explicit mapping table exists to prevent.
    """
    unmapped = [r for r in record["results"] if "UNMAPPED:" in str(r["observed"])]
    assert not unmapped, unmapped


def test_record_states_author_run(record: dict) -> None:
    """The record must not imply independent verification."""
    assert record["run_kind"] == "author-run"
