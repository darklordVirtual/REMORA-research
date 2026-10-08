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
    recorded = ("faults", "row1", "row2", "row3")
    v12 = {k: tables["evidence-sufficiency-v1.2"]["hand_picked"][k] for k in recorded}
    v13 = {k: tables["evidence-sufficiency-v1.3"]["hand_picked"][k] for k in recorded}
    assert v12 == {"faults": 24, "row1": 23, "row2": 22, "row3": 23}
    assert v13 == {"faults": 24, "row1": 24, "row2": 23, "row3": 24}
    # H24 (raw `==` for canonical) is the one hand-picked fault row 2 cannot see by
    # rule R-6; the applicability column names it and the raw row-2 count is unchanged.
    for suite in ("evidence-sufficiency-v1.2", "evidence-sufficiency-v1.3"):
        assert tables[suite]["hand_picked"]["row2_not_applicable_by_r6"] == 1
        rows = {r["id"]: r for r in record["rows"][suite]}
        assert not rows["H24"]["row2_applicable"] and not rows["H24"]["row2_kill"]
        assert rows["H24"]["row1_kill"] and rows["H24"]["row3_kill"]


def test_criterion_counts_an_unlabelled_survivor_as_an_open_gap_and_honours_equivalent() -> None:
    record = H.score(_subset({"H15"}), ("evidence-sufficiency-v1.2",), {})
    assert record["criterion"]["open_gaps"] == ["H15"] and not record["criterion"]["met"]
    record = H.score(_subset({"H15"}), ("evidence-sufficiency-v1.2",), {"H15": "equivalent"})
    assert record["criterion"]["met"]
    record = H.score(_subset({"H15"}), ("evidence-sufficiency-v1.2",), {"H15": "out_of_scope"})
    assert not record["criterion"]["met"], "a bare out_of_scope string is an open gap, as before v1.8"


def test_out_of_scope_leaves_the_denominator_only_with_a_cited_contract_ref() -> None:
    # v1.8 spec, D-25. The earlier probe label files use bare strings and keep their results.
    bare = H.score(_subset({"H15"}), ("evidence-sufficiency-v1.2",), {"H15": {"label": "out_of_scope"}})
    assert bare["criterion"]["open_gaps"] == ["H15"] and not bare["criterion"]["met"]
    blank = H.score(_subset({"H15"}), ("evidence-sufficiency-v1.2",),
                    {"H15": {"label": "out_of_scope", "contract_ref": "  "}})
    assert not blank["criterion"]["met"]
    cited = H.score(_subset({"H15"}), ("evidence-sufficiency-v1.2",),
                    {"H15": {"label": "out_of_scope", "contract_ref": "v1.3 spec section 15.3, scope coercion"}})
    assert cited["criterion"]["met"] and cited["criterion"]["open_gaps"] == []
    assert cited["criterion"]["out_of_scope"] == {"H15": "v1.3 spec section 15.3, scope coercion"}
    assert cited["criterion"]["row3_survivors"] == ["H15"], "the survivor is still reported"
    with pytest.raises(ValueError, match="malformed label"):
        H.normalise_label({"contract_ref": "no label key"})


def test_default_suites_are_discovered_and_end_with_the_newest_on_disk() -> None:
    # R-37 of the v1.8 spec: the fixed (v1.2, v1.3, v1.4) default went stale three suites later.
    on_disk = sorted(
        (p.name for p in (ROOT / "conformance").glob("evidence-sufficiency-v1.*")
         if (p / "run_evidence_sufficiency.py").exists() and (p / "cases.json").exists()),
        key=H.suite_version,
    )
    expected = tuple(name for name in on_disk if H.suite_version(name) >= H.OLDEST_DEFAULT)
    assert H.DEFAULT_SUITES == expected
    assert H.DEFAULT_SUITES[0] == "evidence-sufficiency-v1.2"
    assert H.suite_version(H.DEFAULT_SUITES[-1]) >= (1, 7)
    assert H.suite_version("evidence-sufficiency-v1.10") > H.suite_version("evidence-sufficiency-v1.9")


def test_newest_scores_only_the_newest_suite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    faults = tmp_path / "faults.json"
    faults.write_text(json.dumps(_subset({"S01"})), encoding="utf-8")
    digest = H.sha256(faults.read_bytes())
    out = tmp_path / "record.json"
    assert H.main([str(faults), "--expect-sha256", digest, "--newest", "--json", str(out)]) == 0
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["suites"] == [H.DEFAULT_SUITES[-1]]
    assert H.main([str(faults), "--expect-sha256", digest, "--newest", "--suite", "evidence-sufficiency-v1.2"]) == 2
    assert "exclude each other" in capsys.readouterr().err


def test_row2_applicability_is_decided_by_the_unmutated_checker() -> None:
    # A fault killed on row 2 is applicable whatever the cases; a fault that changes no
    # authored case at all is applicable too (nothing to hide behind R-6); only a fault
    # whose every row-1 change is on a case decisive under the unmutated checker is n/a.
    record = H.score(_subset({"H15", "H24"}), ("evidence-sufficiency-v1.3",), {})
    rows = {r["id"]: r for r in record["rows"]["evidence-sufficiency-v1.3"]}
    assert rows["H15"]["row2_kill"] and rows["H15"]["row2_applicable"]
    assert not rows["H24"]["row2_kill"] and not rows["H24"]["row2_applicable"]
    cases = H.runner("evidence-sufficiency-v1.3").load_json(
        H.CONFORMANCE / "evidence-sufficiency-v1.3" / "cases.json")["cases"]
    expected = {c["id"]: c["expected"]["status"] for c in cases}
    assert all(expected[c] != "not_established" for c in rows["H24"]["row1_cases"])


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
