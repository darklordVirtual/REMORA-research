# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The bcr-linkage-v1 contract: a run record can be linked to a profile and a
Bounded Claim Reproduction level, but the linkage can never raise the level,
translate the status or stand on bytes other than the committed record."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
INTEROP = ROOT / "artifacts" / "interop"
SCHEMA = INTEROP / "schemas" / "bcr-linkage-v1.schema.json"
SOURCE = INTEROP / "runs" / "exact-call-binding-v1-exact_call_binding-author-runtime-L0.json"
REV = "4d2eee1" + "0" * 33


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _condition(cid: str, satisfied: bool = True) -> dict[str, Any]:
    return {"id": cid, "statement": f"{cid} as METHOD.md states it", "satisfied": satisfied, "evidence": "run report section 3"}


BCR3 = ["BCR3-NEGATIVE-CASES", "BCR3-MUTATION-CASES", "BCR3-NO-PRODUCER-MAINTAINER"]
BCR4 = BCR3 + [
    "BCR4-EXTERNAL-ENVIRONMENT", "BCR4-EXTERNAL-RUNNER", "BCR4-EXTERNAL-EXECUTION",
    "BCR4-EXTERNAL-EVIDENCE-CAPTURE", "BCR4-PUBLISHED-EVIDENCE",
]


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = _load(SCHEMA)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture()
def linkage() -> dict[str, Any]:
    """A linkage of the committed L0 author run, which is all that exists today."""
    run = _load(SOURCE)
    return {
        "schema_version": "remora-bcr-linkage-v1",
        "linkage_id": "exact-call-binding-v1-exact-call-binding-1",
        "contract_id": run["contract_id"],
        "package_digest": run["fixture"]["package_digest"],
        "source_record": {
            "schema_version": "remora-interop-result-v1",
            "path": SOURCE.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            "claim": run["claim"],
        },
        "profile": {
            "project": "Agent Authority Conformance Profiles",
            "repository": "darklordVirtual/agent-authority-conformance",
            "profile_id": "AACP-EXACT-CALL-BINDING-1",
            "revision": REV,
        },
        "method": {"name": "Bounded Claim Reproduction", "version": "0.1-draft", "document": "METHOD.md", "revision": REV},
        "remora_independence_level": run["independence_level"],
        "bcr_level": "BCR-0",
        "conditions": [],
        "source_status": run["status"],
        "claim_ceiling": {
            "implies_endorsement": False,
            "implies_production_safety": False,
            "implies_broader_validity": False,
            "confers_authority": False,
            "implies_certification": False,
        },
        "recorded_at": "2026-10-04",
        "recorded_by": "test",
    }


def _errors(validator: Draft202012Validator, record: dict[str, Any]) -> list[str]:
    return [e.message for e in validator.iter_errors(record)]


def test_schema_is_indexed_and_a_level_zero_linkage_validates(validator: Draft202012Validator, linkage: dict[str, Any]) -> None:
    index = _load(INTEROP / "index.json")
    assert index["schemas"]["bcr_linkage"] == SCHEMA.relative_to(ROOT).as_posix()
    assert index["linkages"]["directory"] == "artifacts/interop/linkages"
    assert _errors(validator, linkage) == []


def test_no_linkage_record_is_committed_yet() -> None:
    assert sorted((INTEROP / "linkages").glob("*.json")) == [], "a committed linkage needs a published profile revision first"


@pytest.mark.parametrize(
    ("level", "too_high"),
    [
        ("L0_SELF_TEST", "BCR-1"),
        ("L1_REPRODUCTION", "BCR-2"),
        ("L2_SECOND_IMPLEMENTATION", "BCR-3"),
        ("L3_INDEPENDENT_RECOMPUTATION", "BCR-4"),
    ],
)
def test_bcr_level_cannot_exceed_the_remora_level(validator: Draft202012Validator, linkage: dict[str, Any], level: str, too_high: str) -> None:
    linkage["remora_independence_level"] = level
    linkage["bcr_level"] = too_high
    linkage["conditions"] = [_condition(c) for c in BCR4]
    assert _errors(validator, linkage), f"{too_high} over {level} must be refused"


def test_bcr3_and_bcr4_require_every_additional_condition_documented_as_satisfied(
    validator: Draft202012Validator, linkage: dict[str, Any]
) -> None:
    linkage["remora_independence_level"] = "L4_INDEPENDENT_HOST_RUN"
    linkage["bcr_level"] = "BCR-3"
    assert _errors(validator, linkage), "BCR-3 with no conditions listed"
    linkage["conditions"] = [_condition(c) for c in BCR3[:-1]] + [_condition(BCR3[-1], satisfied=False)]
    assert _errors(validator, linkage), "BCR-3 with one condition unmet"
    linkage["conditions"] = [_condition(c) for c in BCR3]
    assert _errors(validator, linkage) == []
    linkage["bcr_level"] = "BCR-4"
    assert _errors(validator, linkage), "BCR-4 with only the BCR-3 conditions"
    linkage["conditions"] = [_condition(c) for c in BCR4]
    assert _errors(validator, linkage) == []


def test_a_profile_result_is_assigned_by_a_named_reviewer_never_computed(validator: Draft202012Validator, linkage: dict[str, Any]) -> None:
    linkage["profile_result"] = {"value": "ESTABLISHED"}
    assert _errors(validator, linkage), "a bare translated value is refused"
    linkage["profile_result"] = {
        "value": "NOT_APPLICABLE", "assigned_by": "AACP reviewer", "assigned_at": "2026-10-04",
        "rationale": "profile revision 1 does not cover single-use authorization",
    }
    assert _errors(validator, linkage) == []


def test_ceiling_booleans_are_constants_and_nothing_else_is_allowed(validator: Draft202012Validator, linkage: dict[str, Any]) -> None:
    broken = copy.deepcopy(linkage)
    broken["claim_ceiling"]["implies_certification"] = True
    assert _errors(validator, broken)
    broken = copy.deepcopy(linkage)
    broken["score"] = "5/7"
    assert _errors(validator, broken)
    broken = copy.deepcopy(linkage)
    broken["profile"]["project"] = "Agent Authority Conformance"
    assert _errors(validator, broken), "the lab's name is not the profiles project"


def _tmp_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(INTEROP, root / "artifacts" / "interop")
    shutil.copytree(ROOT / "artifacts" / "runtime_surface", root / "artifacts" / "runtime_surface")
    return root


def _write(root: Path, linkage: dict[str, Any], name: str = "one.json") -> None:
    (root / "artifacts" / "interop" / "linkages" / name).write_text(json.dumps(linkage), encoding="utf-8")


def test_gate_accepts_a_faithful_linkage_and_refuses_a_raised_level_or_translated_status(tmp_path: Path, linkage: dict[str, Any]) -> None:
    module = _module("interop_package")
    root = _tmp_root(tmp_path)
    _write(root, linkage)
    assert module.check(root) == []

    raised = copy.deepcopy(linkage)
    raised["remora_independence_level"] = "L1_REPRODUCTION"
    raised["bcr_level"] = "BCR-1"
    _write(root, raised)
    assert any("a linkage never changes a level" in p for p in module.check(root))

    translated = copy.deepcopy(linkage)
    translated["source_status"] = "NOT_ESTABLISHED"
    _write(root, translated)
    assert any("a linkage never translates a status" in p for p in module.check(root))


def test_gate_refuses_a_linkage_over_other_bytes_or_another_claim(tmp_path: Path, linkage: dict[str, Any]) -> None:
    module = _module("interop_package")
    root = _tmp_root(tmp_path)

    stale = copy.deepcopy(linkage)
    stale["source_record"]["sha256"] = "0" * 64
    _write(root, stale)
    assert any("source record digest does not match" in p for p in module.check(root))

    other_claim = copy.deepcopy(linkage)
    other_claim["source_record"]["claim"] = "single_use_authorization"
    _write(root, other_claim)
    assert any("linkage says 'single_use_authorization'" in p for p in module.check(root))

    other_bytes = copy.deepcopy(linkage)
    other_bytes["package_digest"] = "sha256:" + "f" * 64
    _write(root, other_bytes)
    assert any("a level over other bytes does not count" in p for p in module.check(root))

    twice = copy.deepcopy(linkage)
    twice["remora_independence_level"] = "L4_INDEPENDENT_HOST_RUN"
    twice["bcr_level"] = "BCR-3"
    twice["conditions"] = [_condition(c) for c in BCR3] + [_condition(BCR3[0], satisfied=False)]
    _write(root, twice)
    problems = module.check(root)
    assert any("appears twice" in p for p in problems)


def test_gate_bounds_an_external_run_record_by_its_own_independence_fields(tmp_path: Path, linkage: dict[str, Any]) -> None:
    module = _module("interop_package")
    root = _tmp_root(tmp_path)
    run = _load(SOURCE)
    external = {
        "schema_version": "remora-external-run-record-v1",
        "contract_id": run["contract_id"],
        "package_digest": run["fixture"]["package_digest"],
        "consumed_revision": REV,
        "verifier": {"project": "Elsewhere", "repository": "elsewhere/verifier", "revision": REV},
        "imports": {"remora_runtime": False, "reference_verifier": False},
        "command": "python verify.py",
        "environment": {"host": "elsewhere-ci", "python": "3.12"},
        "input_digests": {"fixtures": run["fixture"]["digest"]},
        "implementation_diversity": "SECOND_IMPLEMENTATION",
        "operator": "Elsewhere",
        "independence": "NOT_INDEPENDENT",
        "results": [{"claim_id": run["claim"], "case_id": "c1", "result": "ESTABLISHED"}],
        "claim_ceiling_repeated": True,
        "non_claims_repeated": True,
        "run_ref": "https://example.invalid/run/1",
    }
    # The external record lives outside the runs directory the result gate scans.
    ext_path = root / "artifacts" / "interop" / "external-second-impl.json"
    ext_path.write_text(json.dumps(external), encoding="utf-8")

    linked = copy.deepcopy(linkage)
    linked["source_record"] = {
        "schema_version": "remora-external-run-record-v1",
        "path": "artifacts/interop/external-second-impl.json",
        "sha256": hashlib.sha256(ext_path.read_bytes()).hexdigest(),
        "claim": run["claim"],
    }
    linked["remora_independence_level"] = "L2_SECOND_IMPLEMENTATION"
    linked["bcr_level"] = "BCR-2"
    _write(root, linked)
    problems = module.check(root)
    assert [p for p in problems if "linkages" in p] == [], problems

    linked["remora_independence_level"] = "L3_INDEPENDENT_RECOMPUTATION"
    linked["bcr_level"] = "BCR-3"
    linked["conditions"] = [_condition(c) for c in BCR3]
    _write(root, linked)
    assert any("NOT_INDEPENDENT SECOND_IMPLEMENTATION record is at most L2_SECOND_IMPLEMENTATION" in p for p in module.check(root))
