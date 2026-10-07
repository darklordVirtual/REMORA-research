# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The bounded-result contract: interop-result-v1, the Federation manifest,
the independence levels, the five FED invariants and the generated matrix.

Everything here asserts on committed records and schemas rather than runtime
behaviour, so it is marked ``docgate``.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml
from jsonschema import Draft202012Validator

pytestmark = pytest.mark.docgate

ROOT = Path(__file__).resolve().parents[1]
INTEROP = ROOT / "artifacts" / "interop"
INDEX = INTEROP / "index.json"
RUNS = INTEROP / "runs"
MANIFEST = INTEROP / "FEDERATION.yaml"
MATRIX = ROOT / "docs" / "interop" / "INTEROP_MATRIX.md"
LEVELS = ["L0_SELF_TEST", "L1_REPRODUCTION", "L2_SECOND_IMPLEMENTATION", "L3_INDEPENDENT_RECOMPUTATION", "L4_INDEPENDENT_HOST_RUN"]


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def index() -> dict[str, Any]:
    return _load(INDEX)


@pytest.fixture(scope="module")
def result_schema(index: dict[str, Any]) -> Draft202012Validator:
    return Draft202012Validator(_load(ROOT / index["schemas"]["interop_result"]))


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def records() -> list[dict[str, Any]]:
    return [_load(p) for p in sorted(RUNS.glob("*.json"))]


def _with(d: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    out = copy.deepcopy(d)
    node = out
    *parents, last = path.split(".")
    for p in parents:
        node = node[p]
    node[last] = value
    return out


def _without(d: dict[str, Any], path: str) -> dict[str, Any]:
    out = copy.deepcopy(d)
    node = out
    *parents, last = path.split(".")
    for p in parents:
        node = node[p]
    node.pop(last)
    return out


# ── The Federation manifest ────────────────────────────────────────────────


def test_federation_manifest_validates_and_confers_nothing(index: dict[str, Any], manifest: dict[str, Any]) -> None:
    Draft202012Validator(_load(ROOT / index["schemas"]["federation_manifest"])).validate(manifest)
    assert index["federation_manifest"] == "artifacts/interop/FEDERATION.yaml"
    assert manifest["participation"]["coordinator"] is False
    assert manifest["claim_ceiling"]["production_certified"] is False
    assert manifest["claim_ceiling"]["external_validation"] != "complete"
    for forbidden in ("authority", "trusted_projects", "status"):
        assert forbidden not in manifest
    for edge in manifest["edges"]:
        assert "status" not in edge, "status is derived from records, never declared"


def test_federation_manifest_names_the_five_invariants(manifest: dict[str, Any]) -> None:
    ids = [inv["id"] for inv in manifest["invariants"]]
    assert ids == [f"FED-INV-{n:03d}" for n in range(1, 6)]
    for inv in manifest["invariants"]:
        assert "MUST" in inv["statement"]
        for ref in inv["enforced_by"]:
            rel = ref.split("::", 1)[0].split(" (", 1)[0]
            assert (ROOT / rel).exists(), f"{inv['id']} points at missing {rel}"


def test_every_specified_edge_names_a_contract_in_the_index(index: dict[str, Any], manifest: dict[str, Any]) -> None:
    contracts = {c["id"] for c in index["contracts"]}
    for edge in manifest["edges"]:
        if edge["declared"] == "SPECIFIED":
            assert edge["contract"] in contracts, edge["id"]
        if edge["declared"] == "PRIOR_RECORD":
            assert (ROOT / edge["record"]).is_file(), edge["id"]
    assert len({e["id"] for e in manifest["edges"]}) == len(manifest["edges"])


def test_counterpart_projects_are_data_not_branches_in_the_authority_path(manifest: dict[str, Any]) -> None:
    """The names on an edge may appear in interop code and documents, never
    as a condition in the code that decides or enforces."""
    names = {e["producer"] for e in manifest["edges"]} | {e["consumer"] for e in manifest["edges"]}
    names -= {"REMORA", "any"}
    offenders = []
    for base in ("remora/policy", "remora/enforcement", "remora/execution", "remora/governance", "remora/toolcall", "servers"):
        for path in sorted((ROOT / base).rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for name in names:
                if f'"{name}"' in text or f"'{name}'" in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {name}")
    assert offenders == []


# ── interop-result-v1: a status is never the whole record ──────────────────


def test_committed_run_records_validate_and_pin_the_bytes_they_evaluated(
    index: dict[str, Any], result_schema: Draft202012Validator, records: list[dict[str, Any]]
) -> None:
    assert records, "at least one author record"
    contracts = {c["id"]: c for c in index["contracts"]}
    for record in records:
        result_schema.validate(record)
        contract = contracts[record["contract_id"]]
        assert record["fixture"]["digest"] == "sha256:" + hashlib.sha256((ROOT / record["fixture"]["path"]).read_bytes()).hexdigest()
        assert record["fixture"]["package_digest"] == contract["package_digest"]
        assert record["independence_level"] == "L0_SELF_TEST", "only author records are committed by the producer"
        assert record["does_not_establish"]
        if record["status"] == "ESTABLISHED":
            assert record["establishes"]


def test_author_records_never_advance_a_contract(index: dict[str, Any], records: list[dict[str, Any]]) -> None:
    """Author records never justify REPRODUCED or EXTERNALLY_VERIFIED.
    A contract may reach those states only when separate external_runs exist."""
    with_records = {r["contract_id"] for r in records}
    for contract in index["contracts"]:
        if contract["id"] in with_records and not contract["external_runs"]:
            assert contract["lifecycle"] in ("DRAFT", "FROZEN", "EXTERNAL_RUN_PENDING")


def test_runtime_and_reference_author_records_agree(records: list[dict[str, Any]]) -> None:
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    for record in records:
        by_key.setdefault((record["contract_id"], record["claim"]), {})[record["evaluator"]["kind"]] = record["status"]
    for key, kinds in by_key.items():
        assert set(kinds) == {"PRODUCER_RUNTIME", "REFERENCE"}, key
        assert len(set(kinds.values())) == 1, key


@pytest.fixture
def valid_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    return copy.deepcopy(records[0])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: _without(r, "does_not_establish"),
        lambda r: _with(r, "does_not_establish", []),
        lambda r: _without(r, "producer.revision"),
        lambda r: _without(r, "fixture.digest"),
        lambda r: _with(r, "fixture.digest", "md5:abc"),
        lambda r: _without(r, "schema_version"),
        lambda r: _with(r, "ceiling.implies_endorsement", True),
        lambda r: _with(r, "ceiling.implies_production_safety", True),
        lambda r: _with(r, "ceiling.implies_broader_validity", True),
        lambda r: _with(r, "ceiling.confers_authority", True),
        lambda r: _with(_with(r, "status", "ESTABLISHED"), "establishes", []),
        lambda r: _with(r, "status", "PASS"),
        lambda r: _with(r, "authority", "ACCEPT"),
        lambda r: _with(r, "runner_contract", {"runner_safe": True}),
    ],
)
def test_a_result_without_ceiling_or_provenance_is_refused(
    result_schema: Draft202012Validator, valid_record: dict[str, Any], mutate: Any
) -> None:
    with pytest.raises(jsonschema.ValidationError):
        result_schema.validate(mutate(valid_record))


def test_runner_contract_is_nine_separate_booleans(result_schema: Draft202012Validator, valid_record: dict[str, Any]) -> None:
    props = result_schema.schema["properties"]["runner_contract"]["required"]
    assert len(props) == 9 and len(set(props)) == 9
    assert "runner_safe" not in props
    result_schema.validate(_with(valid_record, "runner_contract", {p: True for p in props}))
    with pytest.raises(jsonschema.ValidationError):
        result_schema.validate(_with(valid_record, "runner_contract", {p: True for p in props[:-1]}))


# ── Independence levels ────────────────────────────────────────────────────


def _external(record: dict[str, Any], level: str) -> dict[str, Any]:
    out = _with(record, "independence_level", level)
    out = _with(out, "operator", "EXTERNAL")
    out = _with(out, "host", "EXTERNAL")
    out["evaluator"] = {"project": "other", "repository": "other/reader", "revision": "e" * 40, "kind": "SECOND_IMPLEMENTATION",
                        "maintained_by": "EXTERNAL", "imports_producer_runtime": False, "imports_reference_evaluator": False,
                        "command": "other-reader fixtures.json"}
    return out


def test_independence_levels_are_ordered_and_each_requires_its_conditions(
    result_schema: Draft202012Validator, valid_record: dict[str, Any], manifest: dict[str, Any]
) -> None:
    assert list(manifest["independence_levels"]) == LEVELS
    assert result_schema.schema["properties"]["independence_level"]["enum"] == LEVELS
    l4 = _external(valid_record, "L4_INDEPENDENT_HOST_RUN")
    result_schema.validate(l4)
    for path, value in (
        ("operator", "PRODUCER"),
        ("evaluator.maintained_by", "PRODUCER"),
        ("evaluator.imports_producer_runtime", True),
        ("evaluator.imports_reference_evaluator", True),
        ("evaluator.kind", "REFERENCE"),
        ("host", "PRODUCER_CONTROLLED"),
    ):
        with pytest.raises(jsonschema.ValidationError):
            result_schema.validate(_with(l4, path, value))
    l3 = _with(_external(valid_record, "L3_INDEPENDENT_RECOMPUTATION"), "host", "PRODUCER_CONTROLLED")
    result_schema.validate(l3)
    with pytest.raises(jsonschema.ValidationError):
        result_schema.validate(_with(l3, "evaluator.imports_producer_runtime", True))


def test_a_self_test_cannot_be_operated_externally_and_a_reproduction_cannot_be_a_second_implementation(
    result_schema: Draft202012Validator, valid_record: dict[str, Any]
) -> None:
    with pytest.raises(jsonschema.ValidationError):
        result_schema.validate(_with(valid_record, "operator", "EXTERNAL"))
    l1 = _with(_with(valid_record, "independence_level", "L1_REPRODUCTION"), "operator", "EXTERNAL")
    result_schema.validate(_with(l1, "evaluator.kind", "REFERENCE"))
    with pytest.raises(jsonschema.ValidationError):
        result_schema.validate(_with(l1, "evaluator.kind", "SECOND_IMPLEMENTATION"))
    l2 = _with(valid_record, "independence_level", "L2_SECOND_IMPLEMENTATION")
    with pytest.raises(jsonschema.ValidationError):
        result_schema.validate(_with(l2, "evaluator.kind", "REFERENCE"))


# ── The publication gate and the generated matrix ──────────────────────────


def test_publication_gate_passes_on_the_committed_surface() -> None:
    assert _module("interop_package").check(ROOT) == []


def test_publication_gate_refuses_a_result_over_other_bytes_and_a_claim_without_ceiling(tmp_path: Path) -> None:
    import shutil

    module = _module("interop_package")
    root = tmp_path / "repo"
    shutil.copytree(INTEROP, root / "artifacts" / "interop")
    shutil.copytree(ROOT / "artifacts" / "runtime_surface", root / "artifacts" / "runtime_surface")
    assert module.check(root) == []
    (run,) = sorted((root / "artifacts" / "interop" / "runs").glob("exact-call-binding-v1-exact_call_binding-author-runtime-L0.json"))
    record = _load(run)
    record["fixture"]["digest"] = "sha256:" + "0" * 64
    run.write_text(json.dumps(record), encoding="utf-8")
    packet_path = root / "artifacts/interop/effect-evidence-v1/claim-packet.json"
    packet = _load(packet_path)
    packet["claims"][0]["claim_ceiling"] = ""
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    problems = module.check(root)
    assert any("fixture digest does not match" in p for p in problems)
    assert any("has no claim_ceiling" in p for p in problems)


def test_matrix_is_generated_from_the_records_and_derives_every_status(manifest: dict[str, Any]) -> None:
    module = _module("build_interop_matrix")
    assert MATRIX.read_text(encoding="utf-8") == module.render()
    text = MATRIX.read_text(encoding="utf-8")
    assert "Generated by `scripts/build_interop_matrix.py`" in text
    assert "External lifecycle records" in text
    assert "NOT_INDEPENDENT" in text
    assert "37232420650" in text
    for edge in manifest["edges"]:
        assert f"| {edge['id']} |" in text
    records = module.load_records()
    for edge in manifest["edges"]:
        derived = module.derive(edge, records)
        if edge["declared"] == "PRIOR_RECORD":
            assert derived["status"] == "PRIOR_RECORD"
        elif derived["records"] == 0:
            assert derived["status"] == edge["declared"]
        else:
            assert derived["status"].endswith(("AUTHOR_RUN", "REPRODUCED", "SECOND_IMPLEMENTATION", "INDEPENDENTLY_ESTABLISHED", "CONTRADICTED", "NOT_ESTABLISHED"))
        if edge.get("experimental"):
            assert derived["status"].startswith("EXPERIMENTAL")


def test_one_contradicted_record_wins_and_independence_is_not_rounded_up(records: list[dict[str, Any]]) -> None:
    module = _module("build_interop_matrix")
    edge = {"id": "X", "producer": "REMORA", "consumer": "any", "artifact": "a", "property": "p", "contract": records[0]["contract_id"], "declared": "SPECIFIED"}
    mine = [r for r in records if r["contract_id"] == edge["contract"]]
    assert module.derive(edge, mine)["status"] == "AUTHOR_RUN"
    l2 = _with(_with(copy.deepcopy(mine[0]), "independence_level", "L2_SECOND_IMPLEMENTATION"), "evaluator.kind", "SECOND_IMPLEMENTATION")
    assert module.derive(edge, mine + [l2])["status"] == "SECOND_IMPLEMENTATION"
    contradicted = _with(copy.deepcopy(mine[0]), "status", "CONTRADICTED")
    assert module.derive(edge, mine + [l2, contradicted])["status"] == "CONTRADICTED"
    assert module.derive(edge, [])["status"] == "SPECIFIED"
