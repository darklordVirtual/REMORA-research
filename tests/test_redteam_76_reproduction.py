# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The reproduction of NEGATIVE_RESULTS §76's count: its summary logic and committed result."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "artifacts" / "assurance" / "pre-federation-redteam-2026-11-10" / "result.json"


def _module():
    spec = importlib.util.spec_from_file_location(
        "reproduce_pre_federation_redteam",
        ROOT / "scripts" / "reproduce_pre_federation_redteam.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_junit_rows_carry_file_outcome_and_the_first_line_of_a_failure(tmp_path):
    m = _module()
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuites><testsuite>'
        '<testcase classname="tests.zz_original_test_pre_federation_x" name="test_a"/>'
        '<testcase classname="tests.zz_original_test_pre_federation_x" name="test_b">'
        '<failure message="AssertionError: boom\n  second line">trace</failure></testcase>'
        '<testcase classname="tests.zz_original_test_pre_federation_x" name="test_c">'
        '<skipped message="no"/></testcase>'
        '</testsuite></testsuites>', encoding="utf-8")
    rows = m.parse_junit(report, "zz_original_")
    assert [(r["file"], r["test"], r["outcome"]) for r in rows] == [
        ("tests/test_pre_federation_x.py", "test_a", "passed"),
        ("tests/test_pre_federation_x.py", "test_b", "failed"),
        ("tests/test_pre_federation_x.py", "test_c", "skipped")]
    assert rows[1]["failure"] == "AssertionError: boom second line"
    assert m.counts(rows) == {"probes": 3, "failed": 1, "passed": 1, "skipped": 1,
                              "per_file": {"tests/test_pre_federation_x.py": {
                                  "failed": 1, "passed": 1, "skipped": 1}}}


def test_summary_says_reproduced_only_on_the_stated_count():
    m = _module()
    row = lambda i, outcome: {"file": "tests/t.py", "test": f"t{i}", "outcome": outcome,  # noqa: E731
                              "failure": "x"}
    base = [row(i, "failed") for i in range(36)] + [row(i, "passed") for i in range(36, 46)]
    out = m.summary({"at_baseline": base, "original_probes_today": base[:1] + base[36:],
                     "repository_probes_today": base[36:] * 2})
    assert out["reproduces_the_stated_count"] is True
    assert len(out["original_probes_still_failing"]) == 1
    off = m.summary({"at_baseline": base[1:], "original_probes_today": [],
                     "repository_probes_today": []})
    assert off["reproduces_the_stated_count"] is False


def test_committed_result_reproduces_the_count_and_classifies_what_still_fails():
    m = _module()
    d = json.loads(RESULT.read_text(encoding="utf-8"))
    assert d["baseline_commit"] == "9a3d321" and d["stated"] == {"probes": 46, "red": 36,
                                                                 "green": 10}
    assert m.summary(d) == d["summary"]
    s = d["summary"]
    assert s["reproduces_the_stated_count"] is True
    assert (s["at_baseline"]["failed"], s["at_baseline"]["passed"]) == (36, 10)
    assert (s["original_probes_today"]["failed"], s["original_probes_today"]["passed"]) == (8, 38)
    assert s["repository_probes_today"] == {**s["repository_probes_today"], "probes": 54,
                                            "failed": 0, "passed": 54}
    still = s["original_probes_still_failing"]
    by_file = {}
    for r in still:
        by_file.setdefault(r["file"], []).append(r)
    assert {f: len(v) for f, v in by_file.items()} == {
        "tests/test_pre_federation_fixture_adequacy_adversarial.py": 5,
        "tests/test_pre_federation_receipt_adversarial.py": 3}
    # The three receipt probes are refused earlier than they expect, not accepted.
    assert all("assessment_decision_unknown" in r["failure"] or "409" in r["failure"]
               or "poisoned" in r["failure"]
               for r in by_file["tests/test_pre_federation_receipt_adversarial.py"])


def test_every_original_probe_that_still_fails_has_a_passing_successor_of_the_same_name():
    d = json.loads(RESULT.read_text(encoding="utf-8"))
    today = {(r["file"], r["test"]): r["outcome"] for r in d["repository_probes_today"]}
    for r in d["summary"]["original_probes_still_failing"]:
        assert today.get((r["file"], r["test"])) == "passed", r["test"]
