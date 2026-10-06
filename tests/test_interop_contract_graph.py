# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Optional attestation is a draft interface; graph links never inherit claims."""
from __future__ import annotations

import copy
import json

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from remora.interop.evidence_io import EvidenceError
from scripts.interop_contract_graph import validate


@pytest.fixture
def documents(repo_root):
    index = json.loads((repo_root / "artifacts/interop/index.json").read_text())
    graph = json.loads((repo_root / index["contract_dependencies"]).read_text())
    return index, graph, repo_root


def test_optional_contracts_and_graph_are_bounded(documents):
    index, graph, root = documents
    validate(index, graph, root)
    assert index["optional_contracts"]
    assert graph["confers_authority"] is False
    assert graph["status_inheritance"] is False
    for entry in index["optional_contracts"]:
        definition = json.loads((root / entry["definition"]).read_text())
        assert definition["lifecycle"] == "DRAFT"
        assert definition["implementation_status"] == "NOT_IMPLEMENTED"
        assert all(claim["remora_status"] == "NOT_ESTABLISHED" for claim in definition["claims"])


@pytest.mark.parametrize("change", [
    "unknown", "cycle", "authority", "inheritance", "property", "duplicate",
    "digest", "schema_digest", "schema_path",
])
def test_graph_errors_never_become_status_propagation(documents, change):
    index, graph, root = documents
    if change == "unknown":
        graph["contracts"][0]["depends_on"] = ["missing-contract"]
    elif change == "cycle":
        graph["contracts"][0]["depends_on"] = [graph["contracts"][0]["contract_id"]]
    elif change == "authority":
        graph["confers_authority"] = True
    elif change == "inheritance":
        graph["status_inheritance"] = True
    elif change == "property":
        graph["contracts"][0]["strengthens"] = ["unknown-property"]
    elif change == "duplicate":
        graph["contracts"].append(copy.deepcopy(graph["contracts"][0]))
    elif change == "digest":
        index["optional_contracts"][0]["definition_digest"] = "sha256:" + "0" * 64
    elif change == "schema_digest":
        index["optional_contracts"][0]["record_schema_digest"] = "sha256:" + "0" * 64
    else:
        index["optional_contracts"][0]["record_schema"] = "schemas/runtime-self-service-v1.schema.json"
    with pytest.raises(EvidenceError):
        validate(index, graph, root)


def _candidate():
    digest = "sha256:" + "a" * 64
    return {
        "contract_id": "attested-execution-v1", "provider": "synthetic-fixture-provider",
        "verifier_profile": "synthetic-profile-not-a-hardware-verifier",
        "attestation_document_digest": digest,
        "workload_measurement": {"native_format": "fixture", "value": "fixture-measurement",
                                 "approved_workload_digest": digest},
        "challenge": {"nonce": "a" * 32, "issued_at": "2026-10-04T12:00:00+00:00", "maximum_age_seconds": 30},
        "appraisal": {"verifier_identity": "fixture:verifier", "at": "2026-10-04T12:00:01+00:00",
                      "verdict": "UNKNOWN", "challenge_nonce": "a" * 32, "evidence_digest": digest},
        "execution_binding": {"observation_digest": digest, "execution_context_digest": digest,
                              "runner_digest": digest},
        "claims": {"tee_execution": "NOT_ESTABLISHED", "workload_measurement": "NOT_ESTABLISHED",
                   "attestation_freshness": "NOT_ESTABLISHED", "application_correctness": "NOT_ESTABLISHED",
                   "runtime_surface_completeness": "NOT_ESTABLISHED", "effect_correctness": "NOT_ESTABLISHED"},
        "local_verification": "NOT_EVALUATED", "confers_authority": False,
    }


def test_candidate_schema_is_not_hardware_evidence(repo_root):
    schema = json.loads((repo_root / "schemas/attested-execution-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    candidate = _candidate()
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(candidate)
    assert candidate["local_verification"] == "NOT_EVALUATED"
    assert candidate["claims"]["tee_execution"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize("change", [
    "nonce_missing", "measurement_missing", "nonaffirming", "correctness", "local_upgrade", "unbounded_window",
])
def test_optional_claims_require_shape_and_preserve_nonclaims(repo_root, change):
    schema = json.loads((repo_root / "schemas/attested-execution-v1.schema.json").read_text())
    candidate = _candidate()
    if change == "nonce_missing":
        del candidate["challenge"]["nonce"]
    elif change == "measurement_missing":
        del candidate["workload_measurement"]
    elif change == "nonaffirming":
        candidate["claims"]["tee_execution"] = "ESTABLISHED"
    elif change == "correctness":
        candidate["claims"]["application_correctness"] = "ESTABLISHED"
    elif change == "local_upgrade":
        candidate["local_verification"] = "ESTABLISHED"
    else:
        candidate["challenge"]["maximum_age_seconds"] = 0
    with pytest.raises(ValidationError):
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(candidate)
