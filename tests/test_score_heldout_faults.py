# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The committed harness for held-out checker faults (v1.3 spec, section 8).

The reference for the harness is an independent one: the analysis of 2026-09-30
scored its 43 faults with its own scripts, and its raw rows are committed. The
harness must agree with them fault by fault and case by case.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts" / "independent-analysis-2026-09-30"
DIGEST = "241fe7d878df28021b3ee3294ea780a13a1b12c27fcba6c495fd14fe0c6d1733"


def _load():
    spec = importlib.util.spec_from_file_location("score_heldout_faults", ROOT / "scripts" / "score_heldout_faults.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


H = _load()
DEFINITIONS = json.loads((PACKAGE / "fault-definitions.json").read_text(encoding="utf-8"))
RAW = json.loads(gzip.decompress((PACKAGE / "raw-row-outputs.json.gz").read_bytes()))


def _subset(ids: set[str]) -> dict:
    return {**DEFINITIONS, "faults": [f for f in DEFINITIONS["faults"] if f["id"] in ids]}


def _agree(record: dict, versions: tuple[str, ...]) -> None:
    for version in versions:
        ours = {r["id"]: r for r in record["rows"][f"evidence-sufficiency-{version}"]}
        for theirs in RAW["versions"][version]:
            if theirs["id"] not in ours:
                continue
            row = ours[theirs["id"]]
            assert sorted(row["row1_cases"]) == sorted(theirs["row1_kill_cases"]), (version, theirs["id"])
            assert sorted(row["row2_cases"]) == sorted(theirs["row2_kill_cases"]), (version, theirs["id"])
            assert row["row3_kill"] == theirs["row3_kill"], (version, theirs["id"])


def test_harness_agrees_with_the_independent_rows_on_the_distinctive_faults() -> None:
    # H15 is the one v1.2 gap the analysis found; H24 is killed on rows 1 and 3 but not 2;
    # S01 stands for the systematic class.
    suites = ("evidence-sufficiency-v1.2", "evidence-sufficiency-v1.3")
    record = H.score(_subset({"H15", "H24", "S01"}), suites, {})
    _agree(record, ("v1.2", "v1.3"))
    v12 = {r["id"]: r for r in record["rows"]["evidence-sufficiency-v1.2"]}
    assert not v12["H15"]["row3_kill"]
    assert record["criterion"]["met"]


@pytest.mark.slow
def test_harness_reproduces_every_independent_row() -> None:
    record = H.score(DEFINITIONS, ("evidence-sufficiency-v1.2", "evidence-sufficiency-v1.3"), {})
    _agree(record, ("v1.2", "v1.3"))
    tables = record["tables"]
    assert tables["evidence-sufficiency-v1.2"]["hand_picked"] == {"faults": 24, "row1": 23, "row2": 22, "row3": 23}
    assert tables["evidence-sufficiency-v1.3"]["hand_picked"] == {"faults": 24, "row1": 24, "row2": 23, "row3": 24}


def test_criterion_counts_an_unlabelled_survivor_as_an_open_gap_and_honours_equivalent() -> None:
    record = H.score(_subset({"H15"}), ("evidence-sufficiency-v1.2",), {})
    assert record["criterion"]["open_gaps"] == ["H15"] and not record["criterion"]["met"]
    record = H.score(_subset({"H15"}), ("evidence-sufficiency-v1.2",), {"H15": "equivalent"})
    assert record["criterion"]["met"]
    record = H.score(_subset({"H15"}), ("evidence-sufficiency-v1.2",), {"H15": "out_of_scope"})
    assert not record["criterion"]["met"], "only an equivalence label leaves the denominator"


def test_an_edit_that_does_not_match_the_checker_is_refused() -> None:
    fault = {**DEFINITIONS["faults"][0], "old": "not in the checker"}
    with pytest.raises(ValueError, match="does not match"):
        H.apply_fault(H.CHECKER.read_text(encoding="utf-8"), fault)


def test_a_fault_file_that_differs_from_the_commitment_is_refused(tmp_path: Path) -> None:
    changed = tmp_path / "faults.json"
    changed.write_bytes((PACKAGE / "fault-definitions.json").read_bytes() + b" ")
    assert H.main([str(changed), "--expect-sha256", DIGEST]) == 2


def test_the_older_runners_get_their_own_checker_back() -> None:
    # v1.2 binds the checker at import; the harness swaps it for the call and restores it.
    run = H.runner("evidence-sufficiency-v1.2")
    before = run.assess
    source = H.apply_fault(H.CHECKER.read_text(encoding="utf-8"), DEFINITIONS["faults"][0])
    failures, crash = H.runner_failures("evidence-sufficiency-v1.2", H.load_source_module(source, "heldout_test_mutant"))
    assert failures or crash
    assert run.assess is before
    assert run.build_record()["failures"] == []
