# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Evidence-sufficiency v1.5: classes instead of fault lists (v1.3 spec, section 15).

v1.4 is frozen by this change. v1.5 must carry it verbatim, add exactly the cases
rule-coverage profile v2 derives, keep the model's rules while widening its
lattice, and pass the three generated sections against the frozen checker. Each
generated section must also catch a fault of the class it exists for.
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
V1 = ROOT / "conformance" / "evidence-sufficiency-v1"
V14 = ROOT / "conformance" / "evidence-sufficiency-v1.4"
V15 = ROOT / "conformance" / "evidence-sufficiency-v1.5"

# v1.4 as scored by the blind probes (NEGATIVE_RESULTS.md §70); the README is prose and is not pinned.
FROZEN_V14 = {
    "cases.json": "d42a5979333a7b3468a485d82969245c9e76de302ee9b0e67a2bacf5a6bba0ab",
    "guidance.json": "eeb951e7073e7cc108a1d4886c4d03080b010287321a934f97ad763bb772542c",
    "ladders.json": "e5b5cd88356625b0593062736fb2a386fe36e9334004e99f34e5861f10acd400",
    "invariants.json": "15ba2341280b09e7b2dd44e93c1a0b185b4209f0a0c4f6c351f8d92a633bd687",
    "model.json": "861e5dc80ff1983e2b3a640ad0f20b340fb0157c6ecfc6df259d1c2083dba201",
    "run_evidence_sufficiency.py": "cf546398a0af0368610e02a12ce10f2cdaca00779c2c0e35a78f9252a5fc5772",
    "run-record.json": "da9ed98d533ba27f18677e26d1053a13b665510a3df068b537ceb2ec624e1699",
}
#: Digest of the profile-v2 derivation over the v1.4 corpus, recorded in the v1.3 spec, section 15.
DERIVED_SHA256 = "7c2712a5f8b39c29e4419113b20bce2ca4373e7ed35613ca81d7065b04a51269"


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


RUNNER = _load("evidence_sufficiency_v1_5_runner", V15 / "run_evidence_sufficiency.py")
RC = _load("rule_coverage_for_v1_5_tests", ROOT / "scripts" / "rule_coverage_evidence_sufficiency.py")


@pytest.fixture(scope="module")
def record() -> dict:
    return RUNNER.build_record()


def _faulty(tmp_path: Path, anchor: str, replacement: str, label: str):
    source = (V1 / "checker.py").read_text(encoding="utf-8")
    assert source.count(anchor) == 1, anchor
    path = tmp_path / f"checker_{label}.py"
    path.write_text(source.replace(anchor, replacement), encoding="utf-8")
    return _load(f"v15_faulty_{label}_{tmp_path.name}", path)


def test_v14_is_frozen() -> None:
    for name, digest in FROZEN_V14.items():
        assert _sha(V14 / name) == digest, name


def test_v14_tables_are_carried_and_the_model_keeps_its_rules() -> None:
    for name in ("guidance.json", "ladders.json", "invariants.json"):
        assert _sha(V15 / name) == _sha(V14 / name), name
    before = json.loads((V14 / "model.json").read_text(encoding="utf-8"))
    after = json.loads((V15 / "model.json").read_text(encoding="utf-8"))
    assert after["claims"] == before["claims"] and after["semantics"] == before["semantics"]
    for key in ("premise_values", "typed_values", "state_values"):
        old = before["lattice"][key]
        assert after["lattice"][key][: len(old)] == old, key
    assert None in after["lattice"]["state_values"]


def test_v14_cases_are_carried_verbatim_and_in_order() -> None:
    before, after = _cases(V14), _cases(V15)
    assert after[: len(before)] == before
    corpus = json.loads((V15 / "cases.json").read_text(encoding="utf-8"))
    assert corpus["base_corpus"]["sha256"] == FROZEN_V14["cases.json"]


def test_new_cases_are_exactly_the_profile_v2_derivation() -> None:
    before, after = _cases(V14), _cases(V15)
    new = after[len(before):]
    text = json.dumps(new, indent=2, ensure_ascii=False) + "\n"
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == DERIVED_SHA256
    model = json.loads((V15 / "model.json").read_text(encoding="utf-8"))
    assert new == RC.derive_v2(model, before)
    assert all(case["gap"] == "N1" and case["obligations"] for case in new)


def test_record_has_no_failures(record: dict) -> None:
    assert record["failures"] == [] and record["crashes"] == []
    assert record["rule_coverage"]["open"] == [] and record["rule_coverage_v2"]["open"] == []
    assert record["input_contract"]["failures"] == [] and record["return_isolation"]["failures"] == []
    assert record["reference_model"]["disagreement_count"] == 0


def test_runner_and_script_define_the_same_v2_obligations() -> None:
    model = RUNNER.load_json(V15 / "model.json")
    ours, theirs = RUNNER.rule_obligations_v2(model), RC.obligations_v2(model)
    assert len(ours) == len(theirs)
    for a, b in zip(ours, theirs):
        assert (a["rule"], a["claim"], tuple(a["outcome"]), a["premise"]) == (b["rule"], b["claim"], tuple(b["outcome"]), b["premise"])
        for cases in (_cases(V14), _cases(V15)):
            assert RUNNER.rule_discharged_v2(a, cases) == RC.covered_v2(b, cases)


def test_profile_v2_is_open_on_the_v1_4_corpus() -> None:
    model = RUNNER.load_json(V15 / "model.json")
    open_on_v14 = [o for o in RUNNER.rule_obligations_v2(model) if not RUNNER.rule_discharged_v2(o, _cases(V14))]
    assert open_on_v14 and not [o for o in RUNNER.rule_obligations_v2(model) if not RUNNER.rule_discharged_v2(o, _cases(V15))]


@pytest.mark.parametrize(
    ("label", "anchor", "replacement", "section"),
    [
        # A container the checker must accept as observations.
        ("container", "validate_json(dict(observations))", "validate_json(observations)", "input_contract:container"),
        # A near miss of premise_source let through.
        ("premise_source", 'if premise_source != "synthetic_fixture":',
         'if premise_source.strip().lower() != "synthetic_fixture":', "input_contract:premise_source"),
        # A returned mapping that aliases the verdict.
        ("alias", '"scope": dict(self.scope),', '"scope": self.scope,', "return_isolation"),
        # A null state read as missing.
        ("null_state", 'if "expected_state" not in o or "observed_state" not in o:',
         'if o.get("expected_state") is None or o.get("observed_state") is None:', "E"),
    ],
)
def test_each_generated_section_catches_its_class(tmp_path: Path, label: str, anchor: str, replacement: str, section: str) -> None:
    failures = RUNNER.build_record(_faulty(tmp_path, anchor, replacement, label))["failures"]
    assert any(f.startswith(section) for f in failures), (label, failures[:5])


def test_record_states_the_shallow_scope_limit(record: dict) -> None:
    assert any("copies a scope shallowly" in limit for limit in record["limits"])
    assert any("gap N1" in limit and "not independent evidence" in limit for limit in record["limits"])


def test_committed_artifact_reproduces_exactly() -> None:
    proc = subprocess.run([sys.executable, str(V15 / "run_evidence_sufficiency.py"), "--check"],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
