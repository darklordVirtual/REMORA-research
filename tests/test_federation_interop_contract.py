# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Machine-enforced Federation producer contract for ``artifacts/interop``.

The package under ``artifacts/interop`` is what another project consumes when
it verifies a REMORA claim (#709, aeoess/agent-governance-vocabulary#177 and
#179). These tests pin the contract as a whole:

* the index, the manifest, the claim packet and the verifier request agree on
  paths, digests, claim ids and result vocabularies;
* package identity is content-addressed (``package_digest`` over the manifest's
  file lines) and no package file carries a Git revision that could not have
  contained it;
* every published JSON Schema is a valid Draft 2020-12 schema, accepts a
  representative valid instance and rejects representative invalid ones;
* the lifecycle state recorded in the index never exceeds what the records
  under it support, and a second implementation never counts as independence;
* the E7 claim ceiling, the explicit non-claims and the repository-wide
  ``runtime_capability_surface_completeness = NOT_ESTABLISHED`` are preserved;
* the foreign-evidence formats stay opaque and cannot reach the authority path
  without an explicitly reviewed integration listed in
  ``artifacts/interop/authority_integrations.json``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
INTEROP = ROOT / "artifacts" / "interop"
INDEX = INTEROP / "index.json"
SCHEMAS = INTEROP / "schemas"
E7 = INTEROP / "runtime-surface-e7-v0.1"
AUTHORITY_ALLOWLIST = INTEROP / "authority_integrations.json"

LIFECYCLE = ["DRAFT", "FROZEN", "EXTERNAL_RUN_PENDING", "REPRODUCED", "EXTERNALLY_VERIFIED"]
RESULT_VOCABULARY = ["ESTABLISHED", "CONTRADICTED", "NOT_ESTABLISHED"]
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_digest(manifest: dict[str, Any]) -> str:
    lines = "".join(
        f"{e['path']} {e['sha256']}\n"
        for e in sorted(manifest["package_files"], key=lambda e: e["path"])
    )
    return "sha256:" + hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _case_claim_id(case: dict[str, Any], fixtures: dict[str, Any]) -> str:
    """The surface cases inherit the fixture-level claim; the effect-path case
    names its own claim under ``expected``."""
    return case.get("claim_id") or case["expected"].get("claim_id") or fixtures["claim_id"]


@pytest.fixture(scope="module")
def index() -> dict[str, Any]:
    return _load(INDEX)


@pytest.fixture(scope="module")
def e7(index: dict[str, Any]) -> dict[str, Any]:
    (contract,) = [c for c in index["contracts"] if c["id"] == "runtime-surface-e7-v0.1"]
    return contract


@pytest.fixture(scope="module")
def schemas(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {name: _load(ROOT / rel) for name, rel in index["schemas"].items()}


def _validator(schemas: dict[str, dict[str, Any]], name: str) -> Draft202012Validator:
    return Draft202012Validator(schemas[name])


# ── Index and referenced paths ──────────────────────────────────────────────


def test_index_is_structurally_valid(index: dict[str, Any]) -> None:
    assert index["schema_version"] == "remora-interop-index-v1"
    assert index["producer"] == {"repository": "darklordVirtual/REMORA-research"}
    assert "published_revision" not in index["producer"], "a self-pin inside the index is the bug #709 fixes"
    assert index["lifecycle_model"]["states"] == LIFECYCLE
    for state in LIFECYCLE:
        assert state in index["lifecycle_model"]["rules"]
    assert index["semantics"]["external_evidence_is_authority"] is False
    assert index["semantics"]["transitive_credit"] is False
    assert index["semantics"]["native_claims_preserved"] is True
    assert index["semantics"]["second_implementation_is_independent"] is False
    assert index["contracts"], "at least one contract"
    for contract in index["contracts"]:
        for key in ("id", "edge", "lifecycle", "external_verification", "source_revision", "manifest",
                    "package_digest", "claim_packet", "verifier_request", "freeze_record",
                    "pin_confirmed_to", "external_runs"):
            assert key in contract, f"{contract.get('id')} lacks {key}"
        assert contract["lifecycle"] in LIFECYCLE
        assert SHA40.match(contract["source_revision"])


def test_every_referenced_path_exists(index: dict[str, Any]) -> None:
    missing = []
    for contract in index["contracts"]:
        for key in ("manifest", "claim_packet", "verifier_request", "fixtures", "reference_verifier"):
            if key in contract and not (ROOT / contract[key]).is_file():
                missing.append(contract[key])
    for rel in index["schemas"].values():
        if not (ROOT / rel).is_file():
            missing.append(rel)
    assert missing == []


def test_five_schemas_are_published(index: dict[str, Any]) -> None:
    assert set(index["schemas"]) == {
        "claim_packet", "external_evidence_ref", "consumed_artifact", "action_lineage", "external_run_record",
    }
    on_disk = {p.name for p in SCHEMAS.glob("*.schema.json")}
    assert on_disk == {Path(rel).name for rel in index["schemas"].values()}


# ── Package identity: content-addressed, no self-pin, no hash cycle ─────────


def test_manifest_digests_match_committed_bytes(e7: dict[str, Any]) -> None:
    manifest = _load(ROOT / e7["manifest"])
    assert manifest["package_files"], "manifest must list the package files"
    for entry in manifest["package_files"]:
        assert _sha256(ROOT / entry["path"]) == entry["sha256"], entry["path"]
    for entry in manifest["source_artifacts"]:
        assert _sha256(ROOT / entry["path"]) == entry["sha256"], entry["path"]


def test_manifest_covers_every_externally_consumed_file(e7: dict[str, Any]) -> None:
    manifest = _load(ROOT / e7["manifest"])
    listed = {e["path"] for e in manifest["package_files"]}
    for key in ("claim_packet", "verifier_request", "fixtures", "reference_verifier"):
        assert e7[key] in listed, f"{key} is consumed externally and must be pinned by the manifest"
    assert str(Path(e7["manifest"]).parent / "README.md") in listed
    assert e7["manifest"] not in listed, "a manifest must never hash itself"
    assert "artifacts/interop/index.json" not in listed, "the index is the record outside the package"


def test_package_digest_is_derived_from_manifest_lines(e7: dict[str, Any]) -> None:
    manifest = _load(ROOT / e7["manifest"])
    digest = _package_digest(manifest)
    assert manifest["package_digest"] == digest
    assert e7["package_digest"] == digest
    assert "package_digest_rule" in manifest


def test_no_package_file_carries_a_publication_self_pin(e7: dict[str, Any]) -> None:
    """Source provenance is a revision that predates the package; nothing in the
    package may name a revision as the one that published it."""
    manifest = _load(ROOT / e7["manifest"])
    source = manifest["source_revision"]
    assert SHA40.match(source)
    for entry in manifest["package_files"]:
        text = (ROOT / entry["path"]).read_text(encoding="utf-8")
        for sha in set(re.findall(r"\b[0-9a-f]{40}\b", text)):
            assert sha == source, f"{entry['path']} names revision {sha}; only source_revision may appear"
        for forbidden in ("published_revision", "producer_revision"):
            assert forbidden not in text, f"{entry['path']} embeds {forbidden}"
    claim_packet = _load(ROOT / e7["claim_packet"])
    verifier_request = _load(ROOT / e7["verifier_request"])
    assert claim_packet["source_revision"] == source
    assert verifier_request["producer"]["source_revision"] == source
    assert e7["source_revision"] == source


def test_claim_packet_and_verifier_request_pin_the_same_bytes(e7: dict[str, Any]) -> None:
    claim_packet = _load(ROOT / e7["claim_packet"])
    verifier_request = _load(ROOT / e7["verifier_request"])
    refs = {r["path"]: r["sha256"] for r in claim_packet["artifact_refs"]}
    assert refs[e7["fixtures"]] == _sha256(ROOT / e7["fixtures"])
    assert refs[e7["reference_verifier"]] == _sha256(ROOT / e7["reference_verifier"])
    inputs = verifier_request["inputs"]
    assert inputs["fixtures"]["path"] == e7["fixtures"]
    assert inputs["fixtures"]["sha256"] == _sha256(ROOT / e7["fixtures"])
    assert inputs["claim_packet"]["path"] == e7["claim_packet"]
    assert inputs["claim_packet"]["sha256"] == _sha256(ROOT / e7["claim_packet"])
    assert verifier_request["contract_id"] == claim_packet["contract_id"] == e7["id"]
    assert claim_packet["package_identity"]["manifest"] == e7["manifest"]
    assert verifier_request["package_identity"]["manifest"] == e7["manifest"]


# ── Claim ids, vocabularies, ceiling and non-claims ────────────────────────


def test_claim_ids_and_result_vocabularies_agree_across_package_files(e7: dict[str, Any]) -> None:
    claim_packet = _load(ROOT / e7["claim_packet"])
    verifier_request = _load(ROOT / e7["verifier_request"])
    fixtures = _load(ROOT / e7["fixtures"])
    claim_ids = {c["claim_id"] for c in claim_packet["claims"]}
    for claim in claim_packet["claims"]:
        assert claim["result_vocabulary"] == RESULT_VOCABULARY
    assert verifier_request["expected_result_vocabulary"] == RESULT_VOCABULARY
    assert fixtures["result_vocabulary"] == RESULT_VOCABULARY
    assert fixtures["claim_id"] in claim_ids
    case_claims = {_case_claim_id(case, fixtures) for case in fixtures["cases"]}
    assert case_claims <= claim_ids, case_claims - claim_ids
    for case in fixtures["cases"]:
        assert case["expected"]["claim_result"] in RESULT_VOCABULARY


def test_e7_claim_ceiling_and_non_claims_are_preserved(e7: dict[str, Any]) -> None:
    claim_packet = _load(ROOT / e7["claim_packet"])
    fixtures = _load(ROOT / e7["fixtures"])
    verifier_request = _load(ROOT / e7["verifier_request"])
    non_claims = set(claim_packet["explicit_non_claims"])
    for required in (
        "runtime_capability_surface_completeness for an external host",
        "absence of host credentials or capabilities outside the observed process",
        "absence of unobserved alternative execution paths",
        "execution occurrence",
        "production enforcement",
        "causation of an observed effect",
        "Federation endorsement",
        "a second implementation is by itself an independent verification record",
    ):
        assert required in non_claims, required
    (surface,) = [c for c in claim_packet["claims"] if c["claim_id"] == fixtures["claim_id"]]
    assert fixtures["claim_ceiling"].startswith(surface["claim_ceiling"].rstrip("."))
    assert "runtime_capability_surface_completeness" in fixtures["claim_ceiling"]
    assert any("does not appoint a verifier" in n for n in verifier_request["non_claims"])
    assert any("does not establish Federation membership" in n for n in verifier_request["non_claims"])
    assert any("second implementation" in n for n in verifier_request["non_claims"])


def test_global_surface_completeness_remains_not_established(e7: dict[str, Any]) -> None:
    manifest = _load(ROOT / e7["manifest"])
    assert manifest["global_property"] == {
        "id": "runtime_capability_surface_completeness",
        "status": "NOT_ESTABLISHED",
    }
    readme = (E7 / "README.md").read_text(encoding="utf-8")
    assert "runtime_capability_surface_completeness = NOT_ESTABLISHED" in readme


# ── Schemas: valid, accept good instances, reject bad ones ──────────────────


def test_every_published_schema_is_valid_draft_2020_12(schemas: dict[str, dict[str, Any]]) -> None:
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema", name


def test_claim_packet_validates_against_its_schema(e7: dict[str, Any], schemas: dict[str, dict[str, Any]]) -> None:
    _validator(schemas, "claim_packet").validate(_load(ROOT / e7["claim_packet"]))


VALID_EVIDENCE_REF: dict[str, Any] = {
    "schema_version": "remora-external-evidence-ref-v1",
    "producer": "example-project",
    "artifact_ref": "example/report.json",
    "artifact_digest": "sha256:" + "a" * 64,
    "native_claim": "payment_within_limit",
    "native_result": "COMPLIANT",
    "subject_class": "payment_authorization",
    "verification": {
        "verifier": "example-verifier",
        "implementation_diversity": "SECOND_IMPLEMENTATION",
        "operator": "EXTERNAL",
        "independence": "INDEPENDENT",
    },
    "claim_ceiling": "Establishes only the producer's native claim under its own rules.",
    "admission_state": "UNADMITTED",
}

VALID_CONSUMED: dict[str, Any] = {
    "schema_version": "remora-consumed-artifact-v1",
    "artifact_ref": "example/fixtures.json",
    "producer": "example-project",
    "role": "fixture input",
    "digest": "sha256:" + "b" * 64,
    "claim_ceiling": (
        "This record establishes only that the named artifact was referenced in the named role. "
        "It does not establish causal importance, economic value, payment entitlement, endorsement "
        "or that an external effect occurred."
    ),
}

VALID_LINEAGE: dict[str, Any] = {
    "schema_version": "remora-action-lineage-v1",
    "action_ref": "action-1",
    "proposal_ref": "proposal-1",
    "authority_refs": ["authority-1"],
    "policy_decision_ref": "decision-1",
    "execution_lease_ref": None,
    "dispatch_ref": None,
    "receipt_refs": [],
    "effect_refs": [],
    "verification_refs": [],
    "consumed_artifacts": [
        {"producer": "example-project", "artifact_ref": "example/x.json", "role": "context", "digest": "sha256:" + "c" * 64}
    ],
    "claim_ceiling": (
        "This record establishes reference linkage only. It does not make one referenced artifact inherit "
        "the authority, authenticity, execution, effect or verification claim of another."
    ),
}


def _valid_run_record(e7: dict[str, Any]) -> dict[str, Any]:
    fixtures = _load(ROOT / e7["fixtures"])
    return {
        "schema_version": "remora-external-run-record-v1",
        "contract_id": e7["id"],
        "package_digest": e7["package_digest"],
        "consumed_revision": "d" * 40,
        "verifier": {
            "project": "example-reader",
            "repository": "example/example-reader",
            "implementation_revision": "e" * 40,
            "maintained_by": "EXTERNAL",
        },
        "imports": {"remora_runtime": False, "reference_verifier": False},
        "command": "python read_e7.py fixtures.json",
        "environment": "Python 3.12, Linux x86_64",
        "input_digests": [{"path": e7["fixtures"], "sha256": _sha256(ROOT / e7["fixtures"])}],
        "implementation_diversity": "SECOND_IMPLEMENTATION",
        "operator": "EXTERNAL",
        "independence": "INDEPENDENT",
        "results": [
            {"claim_id": _case_claim_id(case, fixtures), "case_id": case["id"],
             "result": case["expected"]["claim_result"]}
            for case in fixtures["cases"]
        ],
        "claim_ceiling_repeated": True,
        "non_claims_repeated": True,
        "run_ref": "https://example.invalid/report",
        "published_at": None,
    }


def test_representative_valid_instances_validate(e7: dict[str, Any], schemas: dict[str, dict[str, Any]]) -> None:
    _validator(schemas, "external_evidence_ref").validate(VALID_EVIDENCE_REF)
    _validator(schemas, "consumed_artifact").validate(VALID_CONSUMED)
    _validator(schemas, "action_lineage").validate(VALID_LINEAGE)
    _validator(schemas, "external_run_record").validate(_valid_run_record(e7))


def _without(d: dict[str, Any], key: str) -> dict[str, Any]:
    out = copy.deepcopy(d)
    out.pop(key)
    return out


def _with(d: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    out = copy.deepcopy(d)
    node = out
    *parents, last = path.split(".")
    for p in parents:
        node = node[p]
    node[last] = value
    return out


@pytest.mark.parametrize(
    ("schema_name", "instance"),
    [
        ("external_evidence_ref", _without(VALID_EVIDENCE_REF, "admission_state")),
        ("external_evidence_ref", _with(VALID_EVIDENCE_REF, "admission_state", "ACCEPT")),
        ("external_evidence_ref", _with(VALID_EVIDENCE_REF, "artifact_digest", "md5:abc")),
        ("external_evidence_ref", _with(VALID_EVIDENCE_REF, "verification.independence", "INDEPENDENT_IMPLEMENTATION")),
        ("external_evidence_ref", _with(VALID_EVIDENCE_REF, "authority", "ACCEPT")),
        ("consumed_artifact", _with(VALID_CONSUMED, "claim_ceiling", "This artifact caused the effect.")),
        ("consumed_artifact", _without(VALID_CONSUMED, "digest")),
        ("action_lineage", _with(VALID_LINEAGE, "claim_ceiling", "References inherit each other's claims.")),
        ("action_lineage", _with(VALID_LINEAGE, "consumed_artifacts", [{"producer": "x", "artifact_ref": "y", "role": "z"}])),
    ],
)
def test_representative_invalid_instances_fail(schema_name: str, instance: dict[str, Any], schemas: dict[str, dict[str, Any]]) -> None:
    with pytest.raises(jsonschema.ValidationError):
        _validator(schemas, schema_name).validate(instance)


# ── Independence is a separate fact from implementation diversity ───────────


@pytest.mark.parametrize(
    "mutation",
    [
        {"implementation_diversity": "REPRODUCTION"},
        {"implementation_diversity": "AUTHOR_IMPLEMENTATION"},
        {"operator": "AUTHOR"},
        {"verifier.maintained_by": "REMORA"},
        {"imports.remora_runtime": True},
        {"imports.reference_verifier": True},
        {"claim_ceiling_repeated": False},
        {"non_claims_repeated": False},
    ],
)
def test_independent_requires_the_whole_independence_contract(
    e7: dict[str, Any], schemas: dict[str, dict[str, Any]], mutation: dict[str, Any]
) -> None:
    record = _valid_run_record(e7)
    for path, value in mutation.items():
        record = _with(record, path, value)
    with pytest.raises(jsonschema.ValidationError):
        _validator(schemas, "external_run_record").validate(record)


def test_second_implementation_without_independence_is_a_valid_but_not_independent_record(
    e7: dict[str, Any], schemas: dict[str, dict[str, Any]]
) -> None:
    record = _with(_valid_run_record(e7), "independence", "NOT_INDEPENDENT")
    record = _with(record, "imports.reference_verifier", True)
    _validator(schemas, "external_run_record").validate(record)
    assert record["implementation_diversity"] == "SECOND_IMPLEMENTATION"
    assert record["independence"] == "NOT_INDEPENDENT"


def test_an_author_run_or_reproduction_can_never_be_independent(
    e7: dict[str, Any], schemas: dict[str, dict[str, Any]]
) -> None:
    for diversity in ("AUTHOR_IMPLEMENTATION", "REPRODUCTION"):
        record = _with(_valid_run_record(e7), "implementation_diversity", diversity)
        with pytest.raises(jsonschema.ValidationError):
            _validator(schemas, "external_run_record").validate(record)
        record = _with(record, "independence", "NOT_INDEPENDENT")
        _validator(schemas, "external_run_record").validate(record)


def test_evidence_ref_independent_requires_second_implementation_and_external_operator(
    schemas: dict[str, dict[str, Any]],
) -> None:
    validator = _validator(schemas, "external_evidence_ref")
    for path, value in (
        ("verification.implementation_diversity", "REPRODUCTION"),
        ("verification.operator", "AUTHOR"),
    ):
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(_with(VALID_EVIDENCE_REF, path, value))
    reproduction = _with(VALID_EVIDENCE_REF, "verification.implementation_diversity", "REPRODUCTION")
    validator.validate(_with(reproduction, "verification.independence", "NOT_INDEPENDENT"))


# ── Lifecycle: a state never exceeds its records ────────────────────────────


def _lifecycle_floor(contract: dict[str, Any], schemas: dict[str, dict[str, Any]]) -> str:
    """The strongest state the records under a contract support."""
    freeze = contract["freeze_record"]
    if freeze is None:
        return "DRAFT"
    assert SHA40.match(freeze["revision"]), "freeze_record.revision must be a full Git sha"
    assert freeze["package_digest"] == contract["package_digest"]
    runs = contract["external_runs"]
    validator = _validator(schemas, "external_run_record")
    for run in runs:
        validator.validate(run)
        assert run["package_digest"] == contract["package_digest"], "a run over other bytes does not count"
        assert run["contract_id"] == contract["id"]
    claim_ids = {c["claim_id"] for c in _load(ROOT / contract["claim_packet"])["claims"]}
    if any(
        r["independence"] == "INDEPENDENT" and claim_ids <= {x["claim_id"] for x in r["results"]}
        for r in runs
    ):
        return "EXTERNALLY_VERIFIED"
    if any(r["implementation_diversity"] in ("REPRODUCTION", "SECOND_IMPLEMENTATION") for r in runs):
        return "REPRODUCED"
    if contract["pin_confirmed_to"]:
        return "EXTERNAL_RUN_PENDING"
    return "FROZEN"


def test_lifecycle_state_never_exceeds_its_records(index: dict[str, Any], schemas: dict[str, dict[str, Any]]) -> None:
    for contract in index["contracts"]:
        floor = _lifecycle_floor(contract, schemas)
        assert LIFECYCLE.index(contract["lifecycle"]) <= LIFECYCLE.index(floor), (
            f"{contract['id']} claims {contract['lifecycle']} but its records support at most {floor}"
        )
        expected_ev = {
            "DRAFT": "PENDING", "FROZEN": "PENDING", "EXTERNAL_RUN_PENDING": "PENDING",
            "REPRODUCED": "REPRODUCED", "EXTERNALLY_VERIFIED": "INDEPENDENT",
        }[contract["lifecycle"]]
        assert contract["external_verification"] == expected_ev


def test_lifecycle_is_stated_once_and_repeated_consistently(e7: dict[str, Any]) -> None:
    manifest = _load(ROOT / e7["manifest"])
    assert manifest["lifecycle"] == e7["lifecycle"]
    assert "status" not in manifest, "the old free-text status field contradicted the index"
    readme = (E7 / "README.md").read_text(encoding="utf-8")
    assert "Lifecycle: recorded in the contract entry" in readme
    assert "Lifecycle: **`" not in readme, "a state label in a package file would change its bytes on freeze"
    assert "Status: **proposal**" not in readme
    for pin in e7["pin_confirmed_to"]:
        assert {"verifier", "where", "confirmed_at"} <= set(pin)


def test_a_second_implementation_cannot_advance_a_contract_to_externally_verified(
    e7: dict[str, Any], schemas: dict[str, dict[str, Any]]
) -> None:
    contract = copy.deepcopy(e7)
    contract["freeze_record"] = {"revision": "f" * 40, "package_digest": e7["package_digest"]}
    run = _with(_valid_run_record(e7), "independence", "NOT_INDEPENDENT")
    contract["external_runs"] = [run]
    assert _lifecycle_floor(contract, schemas) == "REPRODUCED"
    contract["external_runs"] = [_valid_run_record(e7)]
    assert _lifecycle_floor(contract, schemas) == "EXTERNALLY_VERIFIED"


def test_an_author_run_does_not_advance_the_lifecycle(e7: dict[str, Any], schemas: dict[str, dict[str, Any]]) -> None:
    contract = copy.deepcopy(e7)
    contract["freeze_record"] = {"revision": "f" * 40, "package_digest": e7["package_digest"]}
    run = _with(_valid_run_record(e7), "implementation_diversity", "AUTHOR_IMPLEMENTATION")
    run = _with(run, "operator", "AUTHOR")
    run = _with(run, "independence", "NOT_INDEPENDENT")
    run = _with(run, "verifier.maintained_by", "REMORA")
    contract["external_runs"] = [run]
    assert _lifecycle_floor(contract, schemas) == "FROZEN"


def test_a_run_over_different_bytes_does_not_count(e7: dict[str, Any], schemas: dict[str, dict[str, Any]]) -> None:
    contract = copy.deepcopy(e7)
    contract["freeze_record"] = {"revision": "f" * 40, "package_digest": e7["package_digest"]}
    contract["external_runs"] = [_with(_valid_run_record(e7), "package_digest", "sha256:" + "0" * 64)]
    with pytest.raises(AssertionError):
        _lifecycle_floor(contract, schemas)


# ── Foreign evidence is opaque and cannot create REMORA authority ───────────


def test_foreign_evidence_formats_carry_no_authority_field(schemas: dict[str, dict[str, Any]]) -> None:
    gate_words = {"accept", "verify", "abstain", "escalate", "grant", "lease", "authority", "authorize", "authorise"}
    for name in ("external_evidence_ref", "consumed_artifact", "action_lineage", "external_run_record"):
        schema = schemas[name]
        assert schema["additionalProperties"] is False, name
        for prop in schema["properties"]:
            assert prop.lower() not in gate_words, f"{name} exposes a gate-shaped field {prop!r}"
    admission = schemas["external_evidence_ref"]["properties"]["admission_state"]["enum"]
    assert set(admission) == {"UNADMITTED", "ADMITTED_AS_CONTEXT", "REJECTED", "NOT_EVALUATED"}
    assert not (set(admission) & {"ACCEPT", "VERIFY", "ABSTAIN", "ESCALATE"})


AUTHORITY_PATH = ("remora/policy", "remora/enforcement", "remora/execution", "remora/governance", "remora/toolcall", "servers")


def test_federation_formats_are_not_wired_into_the_authority_path() -> None:
    """Regression guard: the Federation evidence formats may reach the policy,
    enforcement, execution, governance, toolcall or server code only through
    an integration listed in ``authority_integrations.json`` with its review.
    Unrelated ``remora.interop`` code (APS profiles) is outside the guard."""
    allow = _load(AUTHORITY_ALLOWLIST)
    tokens = allow["guarded_tokens"]
    reviewed = {entry["module"]: entry for entry in allow["reviewed_integrations"]}
    for entry in reviewed.values():
        for key in ("module", "review", "capability"):
            assert entry.get(key), f"a reviewed integration needs {key}"
    offenders: list[str] = []
    for base in AUTHORITY_PATH:
        for path in sorted((ROOT / base).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            hits = [t for t in tokens if t in text]
            if hits and rel not in reviewed:
                offenders.append(f"{rel}: {hits}")
    assert offenders == [], (
        "Federation evidence formats reached the authority path without a reviewed integration:\n"
        + "\n".join(offenders)
    )


def _interop_package_module() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("interop_package", ROOT / "scripts" / "interop_package.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_interop_package_check_passes_on_the_committed_package() -> None:
    module = _interop_package_module()
    assert module.check(ROOT) == []
    manifest = _load(ROOT / "artifacts/interop/runtime-surface-e7-v0.1/manifest.json")
    assert module.package_digest(manifest["package_files"]) == manifest["package_digest"]


def test_interop_package_refuses_to_freeze_against_a_revision_without_the_bytes() -> None:
    module = _interop_package_module()
    with pytest.raises(module.PackageError):
        module.revision_carries_package("runtime-surface-e7-v0.1", "0" * 40, ROOT)


def test_lifecycle_transitions_leave_the_package_digest_unchanged(tmp_path: Path) -> None:
    """Freezing and pinning change the index and the manifest only. The
    package files carry no state label, so every transition that the producer
    can perform leaves the frozen bytes, and hence package_digest, untouched."""
    import shutil

    module = _interop_package_module()
    root = tmp_path / "repo"
    shutil.copytree(INTEROP, root / "artifacts" / "interop")
    for rel in ("artifacts/runtime_surface",):
        shutil.copytree(ROOT / rel, root / rel)
    index_path = root / "artifacts" / "interop" / "index.json"
    index = _load(index_path)
    (contract,) = [c for c in index["contracts"] if c["id"] == "runtime-surface-e7-v0.1"]
    manifest_path = root / contract["manifest"]
    before = {e["path"]: _sha256(root / e["path"]) for e in _load(manifest_path)["package_files"]}
    digest_before = contract["package_digest"]
    assert module.check(root) == []

    contract["freeze_record"] = {"revision": "f" * 40, "package_digest": digest_before, "recorded_at": "2026-10-02"}
    module._set_lifecycle(contract, "FROZEN", root)
    index["contracts"] = [contract]
    _dump = lambda p, d: p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")  # noqa: E731
    _dump(index_path, index)
    module.confirm_pin("runtime-surface-e7-v0.1", "Probity", "https://example.invalid/707", root)

    after_index = _load(index_path)
    (after,) = after_index["contracts"]
    assert after["lifecycle"] == "EXTERNAL_RUN_PENDING"
    assert _load(manifest_path)["lifecycle"] == "EXTERNAL_RUN_PENDING"
    assert {e["path"]: _sha256(root / e["path"]) for e in _load(manifest_path)["package_files"]} == before
    assert module.package_digest(_load(manifest_path)["package_files"]) == digest_before
    assert after["package_digest"] == digest_before
    assert module.check(root) == [], "the pinned package must still verify after the transitions"


def test_authority_path_does_not_import_a_federation_module() -> None:
    pattern = re.compile(r"^\s*(from|import)\s+remora\.interop\.(federation|external_evidence|lineage)\b", re.M)
    offenders = [
        path.relative_to(ROOT).as_posix()
        for base in AUTHORITY_PATH
        for path in sorted((ROOT / base).rglob("*.py"))
        if pattern.search(path.read_text(encoding="utf-8", errors="replace"))
    ]
    assert offenders == []
