# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regression tests for the evidence-sufficiency-v1.3 corpus, runner and mutation gate.

Three groups. The first pins the bytes the external runs measured and checks
that v1.3 carries the earlier corpora verbatim. The second scores deliberately
faulty checkers: one representative of each survivor family the mutation
sweep named (docs/assurance/mutation_testing_v1.md) must be told apart by the
v1.3 runner and, to show that v1.3 adds the power rather than inherits it,
must survive the v1.2 runner. The third checks the metamorphic relations of
`invariants.json` on generated inputs with Hypothesis (Claessen and Hughes,
2000), derandomised so a CI run is reproducible; a relation that holds on the
authored corpus is only known to hold on the authored corpus.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "conformance" / "evidence-sufficiency-v1"
V11 = ROOT / "conformance" / "evidence-sufficiency-v1.1"
V12 = ROOT / "conformance" / "evidence-sufficiency-v1.2"
V13 = ROOT / "conformance" / "evidence-sufficiency-v1.3"

FROZEN_V1 = {
    "checker.py": "c4ca50aee2b2918b11c6fbde1f8615ca6c6bf1e5b6fa2ac1775f49c5e8c20be0",
    "cases.json": "a0048cc021ab7cd7f7d1b09a93e13c7dbdee9f7a685ea617a112da8af3c88d7e",
}
# v1.1 as merged in 8772d85 and v1.2 as measured at c1345b1 (cases, guidance, ladders;
# the v1.2 runner and record carry the reworded H1 limit, pinned in test_evidence_sufficiency_v1_2.py).
FROZEN_V11 = {
    "cases.json": "ffc453c3f4cf90a39374ee574086827974ad5e0f221e4cfdaef5f9acb5068521",
    "guidance.json": "eeb951e7073e7cc108a1d4886c4d03080b010287321a934f97ad763bb772542c",
    "ladders.json": "e5b5cd88356625b0593062736fb2a386fe36e9334004e99f34e5861f10acd400",
}
FROZEN_V12 = {
    "cases.json": "9f0cdd33a2b115e289ac99fe808596ad11ba672aecfc0426a04aa5bf508156ed",
    "guidance.json": "eeb951e7073e7cc108a1d4886c4d03080b010287321a934f97ad763bb772542c",
    "ladders.json": "e5b5cd88356625b0593062736fb2a386fe36e9334004e99f34e5861f10acd400",
}

CANONICAL = 'return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)'

#: One representative per survivor family of the sweep over the v1.2 corpus
#: (docs/assurance/mutation_testing_v1.md, families A, B, D and E). Each is a
#: (anchor, replacement) edit of the frozen checker's source.
FAMILY_FAULTS = {
    "A_claim_not_echoed": (
        '    claim = "postcondition_observed"\n',
        '    claim = None\n',
    ),
    "B_scope_not_echoed": (
        "        scope=_scope(scope),\n",
        "        scope=_scope(None),\n",
    ),
    "B_scope_default_wrong": (
        '        return {"kind": "synthetic_fixture", "bounded": True}\n',
        '        return {"kind": "synthetic_fixture", "bounded": False}\n',
    ),
    "D_validation_short_circuits": (
        "    if value is None or type(value) in (str, bool, int):\n",
        "    if value is not None or type(value) in (str, bool, int):\n",
    ),
    "D_malformed_observations_assessed": (
        "    if claim not in ASSESSORS or not isinstance(observations, Mapping):\n",
        "    if claim not in ASSESSORS and not isinstance(observations, Mapping):\n",
    ),
    "D_nested_values_unvalidated": (
        "        for item in value:\n            validate_json(item)\n",
        "        for item in value:\n            validate_json(None)\n",
    ),
    "E_key_order_compared": (
        CANONICAL,
        'return json.dumps(value, separators=(",", ":"), ensure_ascii=False)',
    ),
}

#: Faults the earlier corpora already told apart; kept so the differential test
#: below cannot pass by accident of a runner that reports failures for everything.
CONTROL_FAULTS = {
    "H1_case_folded": (
        CANONICAL,
        'return json.dumps(value.casefold() if isinstance(value, str) else value, '
        'sort_keys=True, separators=(",", ":"), ensure_ascii=False)',
    ),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = _load("evidence_sufficiency_v1_3_runner", V13 / "run_evidence_sufficiency.py")
RUNNER_V12 = _load("evidence_sufficiency_v1_2_runner_for_v1_3", V12 / "run_evidence_sufficiency.py")
CHECKER = RUNNER.checker


def _cases(directory: Path) -> list[dict]:
    return json.loads((directory / "cases.json").read_text(encoding="utf-8"))["cases"]


def _faulty_checker(tmp_path: Path, label: str, anchor: str, replacement: str):
    source = (V1 / "checker.py").read_text(encoding="utf-8")
    assert source.count(anchor) == 1, label
    path = tmp_path / f"checker_{label}.py"
    path.write_text(source.replace(anchor, replacement), encoding="utf-8")
    return _load(f"faulty_checker_{label}_{tmp_path.name}", path)


@pytest.fixture(scope="module")
def record() -> dict:
    return RUNNER.build_record()


# ── Frozen bytes and verbatim carry-over ───────────────────────────────────────


def test_earlier_tested_bytes_are_frozen() -> None:
    for name, digest in FROZEN_V1.items():
        assert _sha(V1 / name) == digest, name
    for name, digest in FROZEN_V11.items():
        assert _sha(V11 / name) == digest, name
    for name, digest in FROZEN_V12.items():
        assert _sha(V12 / name) == digest, name


def test_v12_guidance_and_ladders_are_carried_byte_for_byte() -> None:
    for name in ("guidance.json", "ladders.json"):
        assert _sha(V13 / name) == _sha(V12 / name), name


def test_v12_cases_are_carried_verbatim_and_in_order() -> None:
    v12 = _cases(V12)
    v13 = _cases(V13)
    assert v13[: len(v12)] == v12
    corpus = json.loads((V13 / "cases.json").read_text(encoding="utf-8"))
    assert corpus["base_corpus"]["sha256"] == FROZEN_V12["cases.json"]
    assert corpus["base_corpus"]["cases_carried_verbatim"] == len(v12)


def test_new_cases_declare_origin_and_rationale() -> None:
    new = _cases(V13)[len(_cases(V12)):]
    assert [case["id"] for case in new[:3]] == ["E21", "E22", "E23"]
    for case in new:
        assert case["gap"] in {"I1", "K1"}, case["id"]
        assert case["derived_from"], case["id"]
        assert case["rationale"], case["id"]
    for case in new[:3]:
        assert case["gap"] == "I1" and case["claim"] == "postcondition_observed", case["id"]
    lattice = [case for case in new if case["gap"] == "K1"]
    assert lattice, "the lattice-derived cases are missing"
    for case in lattice:
        typed = [k for k, v in case["observations"].items() if not isinstance(v, bool) and k not in ("expected_state", "observed_state")]
        assert len(typed) == 1, case["id"]
        assert case["separates"], case["id"]
        assert case["expected"]["status"] == "not_established", case["id"]


def test_lattice_cases_agree_with_the_reference_model() -> None:
    model = RUNNER.load_json(V13 / "model.json")
    for case in _cases(V13):
        expected = RUNNER.interpret_model(model, case["claim"], case["observations"])
        assert expected == (case["expected"]["status"], case["expected"]["reason"]), case["id"]


def test_key_order_cases_differ_only_in_key_order_as_loaded() -> None:
    """The file's key order is the fault E21 and E23 expose; a sorted rewrite would erase it."""
    by_id = {case["id"]: case for case in _cases(V13)}
    for case_id in ("E21", "E23"):
        obs = by_id[case_id]["observations"]
        assert obs["expected_state"] == obs["observed_state"], case_id
        exp, seen = obs["expected_state"], obs["observed_state"]
        while isinstance(exp, dict) and list(exp) == list(seen):
            exp, seen = next(iter(exp.values())), next(iter(seen.values()))
        assert isinstance(exp, dict) and list(exp) != list(seen), case_id
    members = by_id["E22"]["observations"]
    assert members["expected_state"] != members["observed_state"]


def test_rejections_declare_origin_and_a_valueerror() -> None:
    corpus = json.loads((V13 / "cases.json").read_text(encoding="utf-8"))
    ids = [r["id"] for r in corpus["rejections"]]
    assert len(ids) == len(set(ids))
    for rejection in corpus["rejections"]:
        assert rejection["gap"] == "J1", rejection["id"]
        assert rejection["expected"] == {"raises": "ValueError"}, rejection["id"]
        assert rejection["rationale"], rejection["id"]
    assert set(RUNNER.NON_JSON_REJECTIONS).isdisjoint(ids)


# ── The committed record ───────────────────────────────────────────────────────


def test_record_has_no_failures(record: dict) -> None:
    assert record["failures"] == []
    assert record["checker_is_frozen_v1"] is True
    assert record["authored_expectations"]["matched"] == record["authored_expectations"]["total"]
    assert record["authored_expectations"]["by_origin"]["I1"] == 3


def test_v12_runner_properties_carry_over(record: dict) -> None:
    assert record["reason_coverage"]["unreached"] == []
    assert record["guidance_contract_failures"] == []
    assert all(item["holds"] for item in record["precedence_witnesses"])
    assert all(item["holds"] for item in record["isolation_witnesses"])
    checks = record["evidence_erasure_checks"]
    assert checks["inconclusive_strengthening_failures"] == []
    assert checks["polarity_flip_failures"] == []
    assert all(item["rejected"] for item in record["wrong_shortcuts"].values())


def test_every_rejection_is_refused_with_valueerror(record: dict) -> None:
    assert record["rejections"], "the rejection set is empty"
    assert all(item["rejected"] for item in record["rejections"]), record["rejections"]


def test_every_declared_relation_is_executed_and_holds(record: dict) -> None:
    declared = {r["id"] for r in json.loads((V13 / "invariants.json").read_text(encoding="utf-8"))["relations"]}
    executed = {r["id"] for r in record["metamorphic_relations"]}
    assert executed == declared
    for relation in record["metamorphic_relations"]:
        assert relation["checked"] > 0, relation["id"]
        assert relation["holds"], relation


def test_reference_model_agrees_on_the_whole_lattice(record: dict) -> None:
    reference = record["reference_model"]
    assert reference["disagreement_count"] == 0, reference["disagreements"]
    assert reference["lattice_documents"] > 60000
    assert reference["typed_documents"] > 0
    assert reference["authored_cases"] == record["authored_expectations"]["total"]
    assert reference["ladders_consistent"] and reference["reasons_consistent"]


def test_reference_model_tells_apart_a_fault_no_authored_case_reaches(tmp_path: Path) -> None:
    """A typed premise read by truthiness on a field no v1.2 case types: only the lattice sees it.

    The K1 cases now pin these too; this test keeps the model as the check that would
    have caught the fault without them, by scoring a corpus that lacks the K1 cases."""
    faulty = _faulty_checker(
        tmp_path, "truthiness_on_effect_seen",
        '    if o.get("effect_source_accepted") is not True or o.get("effect_seen") is not True:\n',
        '    if o.get("effect_source_accepted") is not True or not o.get("effect_seen"):\n',
    )
    failures = RUNNER.build_record(faulty)["failures"]
    assert any(f.startswith("reference_model:disagreements:") for f in failures), failures
    assert any(f.startswith("A") and f[1:3].isdigit() for f in failures), "a K1 case pins it too"


def test_record_discloses_that_the_new_checks_were_written_after_the_sweep(record: dict) -> None:
    assert any("mutation sweep" in limit and "not independent evidence" in limit for limit in record["limits"])
    assert any("dict()" in limit for limit in record["limits"])


def test_committed_artifact_reproduces_exactly() -> None:
    proc = subprocess.run(
        [sys.executable, str(V13 / "run_evidence_sufficiency.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ── Seeded faults: v1.3 tells the survivor families apart, v1.2 does not ──────


@pytest.mark.parametrize("label", sorted(FAMILY_FAULTS))
def test_each_survivor_family_is_told_apart_by_v1_3(tmp_path: Path, label: str) -> None:
    anchor, replacement = FAMILY_FAULTS[label]
    faulty = _faulty_checker(tmp_path, label, anchor, replacement)
    assert RUNNER.build_record(faulty)["failures"], f"{label} survives the v1.3 corpus"


@pytest.mark.parametrize("label", sorted(FAMILY_FAULTS))
def test_each_survivor_family_survives_v1_2(tmp_path: Path, label: str) -> None:
    """The differential: these faults are what v1.3 adds. If one is killed by v1.2,
    it is not a v1.3 gain and the family table in mutation_testing_v1.md is wrong."""
    anchor, replacement = FAMILY_FAULTS[label]
    faulty = _faulty_checker(tmp_path, label, anchor, replacement)
    assert _v12_failures(faulty) == [], f"{label} was already told apart by v1.2"


@pytest.mark.parametrize("label", sorted(CONTROL_FAULTS))
def test_control_fault_is_told_apart_by_both(tmp_path: Path, label: str) -> None:
    anchor, replacement = CONTROL_FAULTS[label]
    faulty = _faulty_checker(tmp_path, label, anchor, replacement)
    assert RUNNER.build_record(faulty)["failures"]
    assert _v12_failures(faulty)


def _v12_failures(faulty) -> list[str]:
    """Run the v1.2 runner's checks against a faulty checker by swapping its module globals."""
    saved = {name: getattr(RUNNER_V12, name) for name in ("checker", "EvidenceStatus", "assess", "canonical")}
    try:
        RUNNER_V12.checker = faulty
        RUNNER_V12.EvidenceStatus = faulty.EvidenceStatus
        RUNNER_V12.assess = faulty.assess
        RUNNER_V12.canonical = faulty.canonical
        try:
            return RUNNER_V12.build_record()["failures"]
        except Exception as exc:  # noqa: BLE001 - a crash is a kill in the external harness
            return [f"crash:{type(exc).__name__}"]
    finally:
        for name, value in saved.items():
            setattr(RUNNER_V12, name, value)


# ── Metamorphic relations on generated inputs ─────────────────────────────────

INVARIANTS = json.loads((V13 / "invariants.json").read_text(encoding="utf-8"))
PREMISE_FIELDS = {
    claim: INVARIANTS["acceptance_premises"][claim] + INVARIANTS["observation_values"][claim]
    for claim in INVARIANTS["acceptance_premises"]
}
DECISIVE = {"established", "violated"}

json_scalars = st.one_of(st.none(), st.booleans(), st.integers(-3, 3), st.sampled_from(["closed", "open", "Closed", "true", ""]))
json_values = st.recursive(
    json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(st.sampled_from(["state", "lock", "s", "a"]), children, max_size=3),
    ),
    max_leaves=6,
)
premise_values = st.one_of(json_scalars, st.lists(st.sampled_from(["closed", "open"]), max_size=2))


@st.composite
def claim_and_observations(draw):
    claim = draw(st.sampled_from(sorted(PREMISE_FIELDS)))
    fields = PREMISE_FIELDS[claim] + ["unrelated"]
    keys = draw(st.lists(st.sampled_from(fields), unique=True, max_size=len(fields)))
    values = [draw(json_values if key in ("expected_state", "observed_state") else premise_values) for key in keys]
    return claim, dict(zip(keys, values))


HYPOTHESIS = settings(max_examples=150, derandomize=True, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _outcome(verdict: dict) -> dict:
    return {k: v for k, v in verdict.items() if k in ("status", "reason", "missing_evidence", "decisive_if")}


@HYPOTHESIS
@given(json_values, json_values)
def test_canonical_separates_exactly_the_structurally_distinct_values(a, b) -> None:
    same = RUNNER._same_json(a, b)
    assert (CHECKER.canonical(a) == CHECKER.canonical(b)) == same


@HYPOTHESIS
@given(json_values)
def test_canonical_ignores_mapping_key_order_at_every_depth(value) -> None:
    assert CHECKER.canonical(value) == CHECKER.canonical(RUNNER._reorder(value))


@HYPOTHESIS
@given(claim_and_observations())
def test_scope_key_order_and_unrelated_fields_never_change_a_verdict(inputs) -> None:
    claim, obs = inputs
    base = CHECKER.assess(claim, deepcopy(obs)).as_dict()
    outcome = _outcome(base)
    for scope in INVARIANTS["scopes"]:
        verdict = CHECKER.assess(claim, deepcopy(obs), scope=deepcopy(scope)).as_dict()
        assert verdict["claim"] == claim
        assert verdict["scope"] == (dict(scope) if scope else INVARIANTS["default_scope"])
        assert _outcome(verdict) == outcome
    assert _outcome(CHECKER.assess(claim, RUNNER._reorder(obs)).as_dict()) == outcome
    assert _outcome(CHECKER.assess(claim, {**obs, "another_unrelated_field": 1}).as_dict()) == outcome
    assert CHECKER.assess(claim, deepcopy(obs)).as_dict() == base
    assert (base["status"] == "not_established") == bool(base["missing_evidence"]) == ("decisive_if" in base)


@HYPOTHESIS
@given(claim_and_observations())
def test_removing_evidence_never_strengthens_or_inverts_a_verdict(inputs) -> None:
    claim, obs = inputs
    base = CHECKER.assess(claim, deepcopy(obs)).status.value
    for field in obs:
        reduced = {k: v for k, v in obs.items() if k != field}
        after = CHECKER.assess(claim, reduced).status.value
        if base == "not_established":
            assert after == "not_established", (obs, field, after)
        elif after in DECISIVE:
            assert after == base, (obs, field, after)


@HYPOTHESIS
@given(claim_and_observations())
def test_flipping_an_acceptance_premise_never_inverts_polarity(inputs) -> None:
    claim, obs = inputs
    base = CHECKER.assess(claim, deepcopy(obs)).status.value
    if base not in DECISIVE:
        return
    for field in INVARIANTS["acceptance_premises"][claim]:
        if field in obs:
            after = CHECKER.assess(claim, {**obs, field: False}).status.value
            assert after == base or after == "not_established", (obs, field, after)


@HYPOTHESIS
@given(json_values, json_values)
def test_state_comparison_is_symmetric(expected, observed) -> None:
    base = {k: True for k in INVARIANTS["acceptance_premises"]["postcondition_observed"]}
    one = CHECKER.assess("postcondition_observed", {**base, "expected_state": expected, "observed_state": observed})
    two = CHECKER.assess("postcondition_observed", {**base, "expected_state": observed, "observed_state": expected})
    assert one.as_dict() == two.as_dict()
    assert (one.status.value == "established") == RUNNER._same_json(expected, observed)


# ── The mutation gate's own logic ─────────────────────────────────────────────


def test_mutation_gate_compares_survivors_against_the_baseline() -> None:
    gate = _load("mutation_evidence_sufficiency_gate", ROOT / "scripts" / "mutation_evidence_sufficiency.py")
    results = gate.parse_results(
        "    es.checker.x_canonical__mutmut_1: killed\n"
        "    es.checker.x_canonical__mutmut_2: survived\n"
        "    es.checker.x_assess__mutmut_3: survived\n"
        "noise line\n"
    )
    assert results == {
        "es.checker.x_canonical__mutmut_1": "killed",
        "es.checker.x_canonical__mutmut_2": "survived",
        "es.checker.x_assess__mutmut_3": "survived",
    }
    new, dead = gate.compare(results, {"es.checker.x_assess__mutmut_3", "es.checker.x_canonical__mutmut_1"})
    assert new == ["es.checker.x_canonical__mutmut_2"]
    assert dead == ["es.checker.x_canonical__mutmut_1"]


def test_mutation_baseline_is_well_formed_and_classified() -> None:
    gate = _load("mutation_evidence_sufficiency_gate_baseline", ROOT / "scripts" / "mutation_evidence_sufficiency.py")
    baseline = gate.BASELINE
    assert baseline.exists()
    ids = gate.read_baseline(baseline)
    assert ids, "an empty baseline would let every survivor through as expected"
    assert all(id_.startswith("es.checker.x") and "__mutmut_" in id_ for id_ in ids)
    text = baseline.read_text(encoding="utf-8")
    assert "mutmut" in text.splitlines()[3], "the header must record the mutmut version the ids belong to"


# ── The second operator set ───────────────────────────────────────────────────


def _ast_gate():
    return _load("mutation_evidence_sufficiency_ast_gate", ROOT / "scripts" / "mutation_evidence_sufficiency_ast.py")


def test_second_operator_set_covers_every_operator_and_every_assessor() -> None:
    gate = _ast_gate()
    source = gate.Source((V1 / "checker.py").read_text(encoding="utf-8"))
    mutants = gate.catalogue(source)
    operators = {m["operator"] for m in mutants}
    assert operators == set(gate.OPERATORS)
    for assessor in gate.ASSESSORS:
        assert any(m["function"] == assessor for m in mutants), assessor
    ids = [m["id"] for m in mutants]
    assert len(ids) == len(set(ids))
    for m in mutants:
        text = gate.mutated_source(source, m)
        assert text != source.text, m["id"]
        compile(text, "checker", "exec")


def test_second_order_pairs_do_not_overlap_and_are_seeded() -> None:
    gate = _ast_gate()
    source = gate.Source((V1 / "checker.py").read_text(encoding="utf-8"))
    first = gate.catalogue(source)
    pairs = gate.second_order(first, 25, 7)
    assert len(pairs) == 25
    assert pairs == gate.second_order(first, 25, 7)
    for pair in pairs:
        (a0, a1), (b0, b1) = (e["span"] for e in pair["edits"])
        assert a1 <= b0 or b1 <= a0, pair["id"]


def test_second_operator_set_kills_a_sample_and_the_original_passes() -> None:
    gate = _ast_gate()
    source = gate.Source((V1 / "checker.py").read_text(encoding="utf-8"))
    _, failures, _ = gate.score(("original", source.text))
    assert failures == []
    # One mutant per operator is a smoke test of the scorer; the full sweep is the
    # mutation workflow's job and each score is a whole runner pass under coverage.
    mutants = gate.catalogue(source)
    sample = [next(m for m in mutants if m["id"].startswith(prefix)) for prefix in ("status_polarity:", "state_comparison:")]
    for m in sample:
        _, failures, _ = gate.score((m["id"], gate.mutated_source(source, m)))
        assert failures, m["id"]


def test_label_of_collapses_failures_to_their_check() -> None:
    gate = _ast_gate()
    assert gate.label_of("A01") == "A01"
    assert gate.label_of("A01-effect_seen:decisive_verdict_carries_guidance") == "guidance:A01"
    assert gate.label_of("MR-10:E01:source_accepted") == "MR-10"
    assert gate.label_of("reference_model:disagreements:3") == "reference_model"
    assert gate.label_of("crash:reference_model:TypeError") == "crash"
    assert gate.label_of("rejection:R05:returned") == "rejection"


def test_second_operator_set_baseline_is_well_formed() -> None:
    gate = _ast_gate()
    assert gate.BASELINE.exists()
    ids = gate.read_baseline(gate.BASELINE)
    assert all(":" in i for i in ids)
    assert "checker sha256" in gate.BASELINE.read_text(encoding="utf-8")


# ── Reproducing the section 7 rows (independent analysis, 2026-09-30) ────────


def test_reconstructed_corpora_remove_only_the_derived_additions() -> None:
    gate = _ast_gate()
    expected = {
        "merged": (True, True),
        "without-k1": (False, True),
        "first-run": (False, False),
    }
    for corpus, (has_k1, has_later_rejections) in expected.items():
        runner = gate._runner(corpus)
        cases = runner.load_json(runner.HERE / "cases.json")["cases"]
        assert any(c.get("gap") == "K1" for c in cases) is has_k1, corpus
        assert [c["id"] for c in cases if c.get("gap") != "K1"] == [
            c["id"] for c in json.loads((V13 / "cases.json").read_text(encoding="utf-8"))["cases"] if c.get("gap") != "K1"
        ], corpus
        later = set(gate.LATER_REJECTIONS) <= set(runner.NON_JSON_REJECTIONS)
        assert later is has_later_rejections, corpus
        assert set(runner.NON_JSON_REJECTIONS) >= {k for k in RUNNER.NON_JSON_REJECTIONS if k not in gate.LATER_REJECTIONS}
    # Reconstructing a corpus must not leak into the runner the gate scores with.
    assert len(gate._runner("merged").NON_JSON_REJECTIONS) == len(RUNNER.NON_JSON_REJECTIONS)


def test_first_run_corpus_lets_the_isinstance_relaxations_survive() -> None:
    # Guards the correction of spec section 7: the 60 one-check kills (17 on the
    # rejection contract) belong to the corpus with R18-R20 and without K1, not to
    # the first run. These three mutants are killed by R18-R20 alone.
    gate = _ast_gate()
    source = gate.Source((V1 / "checker.py").read_text(encoding="utf-8"))
    by_id = {m["id"]: m for m in gate.catalogue(source)}
    for mutant_id in ("type_vocabulary:validate_json:0", "type_vocabulary:validate_json:1", "type_vocabulary:validate_json:6"):
        text = gate.mutated_source(source, by_id[mutant_id])
        _, first_run, _ = gate.score((mutant_id, text, "first-run"))
        _, without_k1, _ = gate.score((mutant_id, text, "without-k1"))
        assert first_run == [], mutant_id
        assert {gate.label_of(f) for f in without_k1} == {"rejection"}, mutant_id


def test_in_process_sweep_scores_without_a_process_pool() -> None:
    gate = _ast_gate()
    report = gate.sweep(1, 0, gate.SEED, only="status_polarity:postcondition_observed", corpus="merged")
    assert report["corpus"] == "merged"
    assert report["mutants"] > 0 and report["killed"] == report["mutants"]


def test_mutmut_guidance_baseline_equals_the_committed_v1_3_record(record: dict) -> None:
    gate = _load("mutation_evidence_sufficiency_gate_guidance", ROOT / "scripts" / "mutation_evidence_sufficiency.py")
    assert gate.guidance_baseline("evidence-sufficiency-v1.3") == record["case_guidance"]
    v12_ids = [c["id"] for c in json.loads((V12 / "cases.json").read_text(encoding="utf-8"))["cases"]]
    assert sorted(gate.guidance_baseline("evidence-sufficiency-v1.2")) == sorted(v12_ids)


def test_mutmut_sandbox_can_score_with_the_v1_2_corpus(tmp_path: Path) -> None:
    gate = _load("mutation_evidence_sufficiency_gate_v12", ROOT / "scripts" / "mutation_evidence_sufficiency.py")
    gate.build_sandbox(tmp_path / "sandbox", 1, "evidence-sufficiency-v1.2")
    runner = (tmp_path / "sandbox" / "suite" / "evidence-sufficiency-v1.2" / "run_evidence_sufficiency.py").read_text(encoding="utf-8")
    assert "import es.checker as module" in runner
    assert 'reason_vocabulary((V1 / "checker.py")' in runner
    tests = (tmp_path / "sandbox" / "tests" / "test_scoring.py").read_text(encoding="utf-8")
    assert '"evidence-sufficiency-v1.2"' in tests
    assert (tmp_path / "sandbox" / "tests" / "guidance_baseline.json").exists()
    with pytest.raises(SystemExit):
        gate.main(["--update", "--scoring-suite", "evidence-sufficiency-v1.2"])


@pytest.mark.docgate
def test_committed_sweep_outputs_match_the_baselines_and_the_reported_rows() -> None:
    # The raw outputs behind spec section 7 (NEGATIVE_RESULTS.md §67). A count and its
    # evidence must not drift apart: the survivors in each committed output equal the
    # baseline or the published row they back.
    import gzip

    out = ROOT / "artifacts" / "evidence-sufficiency-mutation-2026-09-30"
    mutmut = _load("mutation_evidence_sufficiency_gate_artifacts", ROOT / "scripts" / "mutation_evidence_sufficiency.py")
    v12 = mutmut.parse_results((out / "mutmut-results-v1.2.txt").read_text(encoding="utf-8"))
    v13 = mutmut.parse_results((out / "mutmut-results-v1.3.txt").read_text(encoding="utf-8"))
    survived = {name: {m for m, s in rows.items() if s == "survived"} for name, rows in (("v1.2", v12), ("v1.3", v13))}
    assert v12.keys() == v13.keys()
    assert survived["v1.3"] == mutmut.read_baseline(mutmut.BASELINE)
    assert survived["v1.3"] < survived["v1.2"]
    # Published row: v1.2 kills 377 of 489 (spec section 7, NEGATIVE_RESULTS.md §65).
    assert (len(v12), len(v12) - len(survived["v1.2"])) == (489, 377)
    ast_gate = _ast_gate()
    reports = {
        corpus: json.loads(gzip.decompress((out / f"ast-{corpus}.json.gz").read_bytes()))
        for corpus in ast_gate.CORPORA
    }
    assert set(reports["merged"]["survived"]) == ast_gate.read_baseline(ast_gate.BASELINE)
    for corpus, report in reports.items():
        assert report["corpus"] == corpus
        assert report["killed"] + len(report["survived"]) == report["mutants"]
        assert report["checker_sha256"] == FROZEN_V1["checker.py"]
    # Published rows of spec section 7, including the §67 correction (57, not 60).
    fragile = {c: (r["killed"], len(r["redundancy"]["fragile"])) for c, r in reports.items()}
    assert fragile == {"first-run": (898, 57), "without-k1": (901, 60), "merged": (901, 18)}


@pytest.mark.docgate
def test_independent_analysis_package_matches_its_recorded_hash() -> None:
    # The record names the fault-definition hash the analysis wrote before it opened v1.3;
    # the committed package must carry those exact bytes (.gitattributes keeps them -text).
    package = ROOT / "artifacts" / "independent-analysis-2026-09-30"
    digest = hashlib.sha256((package / "fault-definitions.json").read_bytes()).hexdigest()
    record = (ROOT / "docs" / "assurance" / "external_adequacy_evidence_sufficiency_v1.md").read_text(encoding="utf-8")
    assert f"sha256 `{digest}`" in record
    definitions = json.loads((package / "fault-definitions.json").read_text(encoding="utf-8"))
    assert definitions["source_commit"].startswith("c9113a0")
    assert len(definitions["faults"]) == len({f["id"] for f in definitions["faults"]})
