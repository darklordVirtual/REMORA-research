# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Rule coverage over the evidence-sufficiency model (v1.3 spec, section 14).

The tests pin the criterion and the derivation rule that section 14
pre-registers, and the held-out catalogue's digest. They read no mutant score.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "design" / "evidence-sufficiency-v1.3.md"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RC = _load("rule_coverage_evidence_sufficiency", ROOT / "scripts" / "rule_coverage_evidence_sufficiency.py")
SM = _load("spec_mutation_evidence_sufficiency_for_rc", ROOT / "scripts" / "spec_mutation_evidence_sufficiency.py")
RUNNER = _load("es_v1_3_runner_for_rc", ROOT / "conformance" / "evidence-sufficiency-v1.3" / "run_evidence_sufficiency.py")
MODEL = RC.load_model("evidence-sufficiency-v1.3")
V13_CASES = RC.load_cases("evidence-sufficiency-v1.3")


def test_every_decisive_outcome_of_the_model_has_a_path() -> None:
    outcomes = {(claim, tuple(outcome)) for claim, _, _, outcome in RC.decisive_paths(MODEL)}
    decisive = set()
    for claim, spec in MODEL["claims"].items():
        for status, reason in SM._decisive(spec):
            decisive.add((claim, (status, reason)))
    assert outcomes == decisive


def test_path_conditions_reach_their_outcome_under_the_model() -> None:
    # The configuration RC derives from (path met, every off-path premise true) must
    # itself give the outcome, or every derived case would rest on a wrong base.
    for claim, cond, states, outcome in RC.decisive_paths(MODEL):
        fields = MODEL["claims"][claim]["fields"]
        obs = {f: cond.get(f, True) for f in fields}
        if states:
            obs.update(states)
        assert RUNNER.interpret_model(MODEL, claim, obs) == outcome, (claim, outcome)


def test_derivation_matches_the_pre_registered_digest() -> None:
    import hashlib

    text = json.dumps(RC.derive(MODEL, V13_CASES), indent=2, ensure_ascii=False) + "\n"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert f"`{digest}`" in SPEC.read_text(encoding="utf-8")


def test_derived_cases_close_every_obligation_and_agree_with_the_runner_model() -> None:
    derived = RC.derive(MODEL, V13_CASES)
    assert RC.uncovered(MODEL, V13_CASES + derived) == []
    ids = [c["id"] for c in V13_CASES + derived]
    assert len(ids) == len(set(ids))
    for case in derived:
        expected = RUNNER.interpret_model(MODEL, case["claim"], case["observations"])
        assert expected == (case["expected"]["status"], case["expected"]["reason"]), case["id"]
        assert case["gap"] == "L1" and case["obligations"] and case["rationale"], case["id"]


def test_each_rule_is_violated_by_removing_its_witness() -> None:
    # Guards the coverage check itself: dropping the only witness reopens the obligation.
    derived = RC.derive(MODEL, V13_CASES)
    for case in derived:
        rest = [c for c in V13_CASES + derived if c["id"] != case["id"]]
        assert RC.uncovered(MODEL, rest), case["id"]


def test_held_out_catalogue_matches_the_pre_registered_digest_and_is_disjoint() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert f"Its digest is `{SM.catalogue_sha256(name='heldout')}`." in text
    assert SM.catalogue_sha256() == "2fbf983a5b29f7f6c2b4bba8319fd8c8d7a59105651f38e11b4e6b3d8c5bd5a8"
    heldout = SM.catalogue(operators=SM.HELDOUT_OPERATORS)
    assert {m["operator"] for m in heldout} == set(SM.HELDOUT_OPERATORS)
    v1_models = {json.dumps(m["model"], sort_keys=True) for m in SM.catalogue()}
    original = json.dumps(SM.load_model(), sort_keys=True)
    for m in heldout:
        rendered = json.dumps(m["model"], sort_keys=True)
        assert rendered != original, m["id"]
        assert rendered not in v1_models, m["id"]
