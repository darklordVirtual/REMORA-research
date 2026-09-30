# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Specification mutation over the evidence-sufficiency reference model (v1.3 spec, section 13).

These tests pin the harness, not a result: the catalogue matches the digest the
spec pre-registered, every mutant differs from the model, the unmutated model
passes the runner as a checker, the equivalence domain is what section 13.3
argues, and a known misreading is told apart.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "spec_mutation_evidence_sufficiency.py"
SPEC = ROOT / "docs" / "design" / "evidence-sufficiency-v1.3.md"


def _load():
    spec = importlib.util.spec_from_file_location("spec_mutation_evidence_sufficiency", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SM = _load()


@pytest.fixture(scope="module")
def first() -> list[dict]:
    return SM.catalogue()


def test_catalogue_matches_the_pre_registered_digest() -> None:
    # Section 13.2 pins the digest; a changed operator must show up as a changed spec.
    text = SPEC.read_text(encoding="utf-8")
    assert f"`--catalogue-sha256` prints its digest: `{SM.catalogue_sha256()}`" in text


def test_every_operator_yields_mutants_and_every_mutant_differs(first: list[dict]) -> None:
    assert {m["operator"] for m in first} == set(SM.OPERATORS)
    ids = [m["id"] for m in first]
    assert len(ids) == len(set(ids))
    original = json.dumps(SM.load_model(), sort_keys=True)
    for m in first:
        assert json.dumps(m["model"], sort_keys=True) != original, m["id"]


def test_second_order_pairs_are_seeded_and_on_one_claim(first: list[dict]) -> None:
    pairs = SM.second_order(first, 20, 7)
    assert pairs == SM.second_order(first, 20, 7)
    by_id = {m["id"]: m for m in first}
    for pair in pairs:
        a, b = pair["id"].removeprefix("second:").split("+")
        assert by_id[a]["claim"] == by_id[b]["claim"] == pair["claim"]
        assert by_id[a]["step"] != by_id[b]["step"]


def test_unmutated_model_passes_the_runner_as_a_checker() -> None:
    assert SM.runner_failures_of(SM.load_model()) == []


def test_model_checker_agrees_with_the_frozen_checker_on_every_authored_case() -> None:
    runner = SM._runner()
    module = SM.model_checker(SM.load_model(), "es_spec_mutation_test_model_checker")
    try:
        for case in runner.load_json(SM.V13 / "cases.json")["cases"]:
            assert module.assess(case["claim"], case["observations"]).as_dict() == \
                runner.checker.assess(case["claim"], case["observations"]).as_dict(), case["id"]
    finally:
        sys.modules.pop("es_spec_mutation_test_model_checker", None)


def test_value_classes_separate_every_predicate() -> None:
    # Section 13.3: every predicate is constant on each class, and no two classes read
    # alike under every predicate, so eight classes are needed and enough.
    predicates = ("is_true", "is_false", "truthy", "falsy", "eq_true", "eq_false",
                  "not_false", "not_true", "not_none", "present")
    signatures = set()
    for value in SM.ALL_CLASSES:
        present = value is not SM.ABSENT
        signatures.add(tuple(SM._pred(p, present, None if not present else value) for p in predicates))
    assert len(signatures) == len(SM.ALL_CLASSES)
    # Other members of the truthy and falsy non-boolean classes read like their representative.
    for member, representative in (([True], "true"), ({"value": True}, "true"), ([], ""), ({}, "")):
        assert [SM._pred(p, True, member) for p in predicates] == [SM._pred(p, True, representative) for p in predicates]


def test_untouched_premises_are_read_exactly(first: list[dict]) -> None:
    # The domain argument needs every premise an edit does not name to keep an exact reading.
    exact = {"is_true", "is_false"}
    for m in first:
        for _, _, _, step in SM._walk(m["model"]["claims"][m["claim"]]["steps"], m["claim"]):
            for field, predicate in step.get("require", {}).items():
                assert predicate in exact or field in m["touched"], m["id"]
            if "branch" in step:
                preds = {step.get("true_pred", "is_true"), step.get("false_pred", "is_false")}
                assert preds <= exact or step["branch"] in m["touched"], m["id"]


def test_a_truthiness_misreading_is_found_non_equivalent_with_a_witness(first: list[dict]) -> None:
    original = SM.load_model()
    mutant = next(m for m in first if m["description"] == "read `scope_accepted` as `truthy`")
    witness = SM.equivalence_witness(original, mutant)
    assert witness is not None
    assert type(witness["observations"]["scope_accepted"]) is not bool


def test_an_unchanged_model_is_found_equivalent() -> None:
    # A control for the equivalence computation: a mutant with no edit must be equivalent.
    original = SM.load_model()
    mutant = {"claim": "admission_accounting", "touched": [], "model": SM.load_model()}
    assert SM.equivalence_witness(original, mutant) is None


# ── The gate and the recorded result ─────────────────────────────────────────


def _report(row1: list[str], row3: list[str], digest: str = "d") -> dict:
    empty = {"row1_survivors": [], "row3_survivors": []}
    return {
        "catalogue_sha256": digest,
        "summary": {"first_order": {"row1_survivors": row1, "row3_survivors": row3}, "second_order": empty},
    }


def test_gate_fails_on_a_new_survivor_on_either_row_and_on_a_changed_catalogue() -> None:
    baseline = {"row1 a", "row3 b"}
    assert SM.compare(_report(["a"], ["b"]), "d", baseline) == ([], [], [])
    errors, new, dead = SM.compare(_report(["a", "c"], []), "d", baseline)
    assert (errors, new, dead) == ([], ["row1 c"], ["row3 b"])
    errors, _, _ = SM.compare(_report(["a"], ["b"], digest="other"), "d", baseline)
    assert errors and "differs" in errors[0]


def test_baseline_header_carries_the_pre_registered_digest() -> None:
    digest, entries = SM.read_baseline(SM.BASELINE)
    assert digest == SM.catalogue_sha256()
    assert entries and all(e.split(" ", 1)[0] in ("row1", "row3") for e in entries)


@pytest.mark.docgate
def test_committed_report_matches_the_baseline_and_the_published_result() -> None:
    import gzip

    report = json.loads(gzip.decompress(
        (ROOT / "artifacts" / "evidence-sufficiency-spec-mutation-2026-09-30" / "spec-mutation.json.gz").read_bytes()
    ))
    assert report["catalogue_sha256"] == SM.catalogue_sha256()
    _, entries = SM.read_baseline(SM.BASELINE)
    assert SM.survivors(report) == entries
    # Section 13.6 and NEGATIVE_RESULTS.md §68 publish these; a rerun that moves them must
    # move the record with it.
    first, second = report["summary"]["first_order"], report["summary"]["second_order"]
    assert (first["mutants"], first["equivalent"], first["row1_killed"], first["row3_killed"]) == (446, 54, 380, 392)
    assert (second["mutants"], second["equivalent"], second["row1_killed"], second["row3_killed"]) == (300, 2, 298, 298)
    # Consistency the computation allows: no mutant the domain calls equivalent fails the runner.
    assert first["equivalent_killed_on_row3"] == second["equivalent_killed_on_row3"] == []
    # Every row-1 survivor is a cross-branch premise added to the admission ladder (§68).
    survivors = [r for r in report["rows"] if r["id"] in first["row1_survivors"]]
    assert survivors and all(r["operator"] == "add_premise" and r["claim"] == "admission_accounting" for r in survivors)
    assert all(r["row3_labels"] == ["reference_model"] for r in survivors)


def test_a_cross_branch_premise_survives_the_authored_cases_but_not_the_runner() -> None:
    # One §68 survivor, scored live: the authored cases cannot see it, the runner can.
    original = SM.load_model()
    mutant = next(m for m in SM.catalogue(original) if m["id"] == "add_premise:admission_accounting:20")
    row = SM.score(({k: v for k, v in mutant.items() if k != "_edit"}, original))
    assert not row["equivalent"]
    assert row["row1_cases"] == [] and row["row3_kill"]
