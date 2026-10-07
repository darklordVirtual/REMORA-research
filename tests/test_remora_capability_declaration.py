"""Structural and evidence-boundary tests for the capability declaration."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.check_remora_capabilities import (
    DECLARATION,
    DeclarationValidationError,
    validate_declaration,
)

pytestmark = pytest.mark.docgate
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def declaration() -> dict[str, Any]:
    return yaml.safe_load(DECLARATION.read_text(encoding="utf-8"))


def test_committed_declaration_validates_and_pins_fixture_bytes(
    declaration: dict[str, Any],
) -> None:
    validate_declaration(declaration, root=ROOT)
    assert all(
        cap["maturity"]["externally_reproduced"] is False
        and cap["maturity"]["production_established"] is False
        for cap in declaration["workflow_capabilities"]
    )
    assert all(
        cap["runtime_reproduction_status"] == "NOT_READY"
        for cap in declaration["self_service_capabilities"]
    )


def test_duplicate_workflow_ids_are_rejected(declaration: dict[str, Any]) -> None:
    declaration["workflow_capabilities"].append(
        copy.deepcopy(declaration["workflow_capabilities"][0])
    )
    with pytest.raises(DeclarationValidationError, match="IDs must be unique"):
        validate_declaration(declaration, root=ROOT)


def test_capability_without_evidence_references_is_rejected(
    declaration: dict[str, Any],
) -> None:
    capability = declaration["workflow_capabilities"][0]
    capability["evidence"] = {
        "capability_ids": [],
        "claim_ids": [],
        "implementation": [],
        "tests": [],
        "external_runs": [],
        "operator_records": [],
        "production": [],
    }
    with pytest.raises(DeclarationValidationError, match="evidence references are required"):
        validate_declaration(declaration, root=ROOT)


def test_self_service_without_procedure_and_claim_ceiling_is_rejected(
    declaration: dict[str, Any],
) -> None:
    capability = declaration["self_service_capabilities"][0]
    capability["procedure"]["reference"] = ""
    capability["claim_ceiling"] = ""
    with pytest.raises(DeclarationValidationError):
        validate_declaration(declaration, root=ROOT)


def test_manual_procedure_without_assistance_is_rejected(
    declaration: dict[str, Any],
) -> None:
    capability = declaration["self_service_capabilities"][0]
    capability["procedure"]["mode"] = "manual"
    capability["procedure"]["executable"] = False
    with pytest.raises(DeclarationValidationError, match="manual procedure"):
        validate_declaration(declaration, root=ROOT)


def test_external_reproduction_requires_run_record(
    declaration: dict[str, Any],
) -> None:
    capability = declaration["workflow_capabilities"][0]
    capability["maturity"].update(
        level="EXTERNALLY_REPRODUCED",
        reproducible=True,
        externally_reproduced=True,
    )
    with pytest.raises(DeclarationValidationError, match="external run evidence"):
        validate_declaration(declaration, root=ROOT)


def test_production_maturity_requires_production_and_operator_evidence(
    declaration: dict[str, Any],
) -> None:
    capability = declaration["workflow_capabilities"][0]
    capability["maturity"].update(
        level="OPERATOR_OBSERVED",
        reproducible=True,
        externally_reproduced=True,
        operator_observed=True,
        production_established=True,
    )
    with pytest.raises(DeclarationValidationError, match="production evidence"):
        validate_declaration(declaration, root=ROOT)


def test_production_evidence_rejects_non_field_evidence_class(
    declaration: dict[str, Any],
) -> None:
    declaration["workflow_capabilities"][0]["evidence"]["production"] = [
        {"class": "internal_benchmark", "reference": "results/example.json"}
    ]
    with pytest.raises(DeclarationValidationError, match="is not one of"):
        validate_declaration(declaration, root=ROOT)


def test_self_service_reference_must_resolve_to_workflow_capability(
    declaration: dict[str, Any],
) -> None:
    declaration["self_service_capabilities"][0]["capability_ref"] = "missing_workflow_capability"
    with pytest.raises(DeclarationValidationError, match="nonexistent workflow capability"):
        validate_declaration(declaration, root=ROOT)


def test_fixture_replay_cannot_claim_runtime_reproduction(
    declaration: dict[str, Any],
) -> None:
    declaration["self_service_capabilities"][0]["runtime_reproduction_status"] = "READY"
    with pytest.raises(DeclarationValidationError, match="fixture-only scope"):
        validate_declaration(declaration, root=ROOT)


def test_authority_and_executor_cannot_both_hold_effect_credentials(
    declaration: dict[str, Any],
) -> None:
    trust_boundary = declaration["workflow_capabilities"][0]["trust_boundary"]
    trust_boundary["remora_authority_process_holds_execution_credentials"] = True
    with pytest.raises(DeclarationValidationError, match="custody must remain separate"):
        validate_declaration(declaration, root=ROOT)


def test_maturity_flags_cannot_exceed_declared_level(
    declaration: dict[str, Any],
) -> None:
    declaration["workflow_capabilities"][0]["maturity"]["level"] = "IMPLEMENTED"
    with pytest.raises(DeclarationValidationError, match="conflicts with flags"):
        validate_declaration(declaration, root=ROOT)


def test_runtime_procedure_is_bounded_and_discoverable(declaration: dict[str, Any]) -> None:
    procedure, = declaration["runtime_self_service_procedures"]
    assert procedure["scope"] == "pinned_runtime_primitive_fixtures"
    assert procedure["independence"] == "NOT_CLASSIFIED"
    assert procedure["advances_lifecycle"] is False
    assert set(procedure["capability_refs"]) <= {
        cap["id"] for cap in declaration["workflow_capabilities"]
    }
    validate_declaration(declaration, root=ROOT)


@pytest.mark.parametrize("change", ["capability", "fixture", "evidence", "independence", "scope"])
def test_runtime_procedure_cannot_inflate_evidence(declaration: dict[str, Any], change: str) -> None:
    procedure = declaration["runtime_self_service_procedures"][0]
    if change == "capability":
        procedure["capability_refs"] = ["missing_capability"]
    elif change == "fixture":
        procedure["frozen_fixture_contracts"] = ["exact-call-binding-v1.1"]
    elif change == "evidence":
        procedure["runner"] = "scripts/missing_runner.py"
    elif change == "independence":
        procedure["independence"] = "INDEPENDENT"
    else:
        procedure["scope"] = "production"
    with pytest.raises(DeclarationValidationError):
        validate_declaration(declaration, root=ROOT)


def test_index_cannot_discover_an_undeclared_runtime_procedure(declaration: dict[str, Any]) -> None:
    declaration.pop("runtime_self_service_procedures")
    with pytest.raises(DeclarationValidationError, match="index entry"):
        validate_declaration(declaration, root=ROOT)


@pytest.mark.parametrize("field", ["capability_refs", "frozen_fixture_contracts", "tests"])
def test_runtime_procedure_requires_nonempty_evidence(declaration: dict[str, Any], field: str) -> None:
    declaration["runtime_self_service_procedures"][0][field] = []
    with pytest.raises(DeclarationValidationError):
        validate_declaration(declaration, root=ROOT)


@pytest.mark.parametrize("field", ["admission", "signature_confers_authority", "tool"])
def test_operator_statement_discovery_cannot_grant_authority(declaration: dict[str, Any], field: str) -> None:
    statement = declaration["runtime_self_service_procedures"][0]["operator_statement"]
    statement[field] = True if field == "signature_confers_authority" else "ESTABLISHED"
    with pytest.raises(DeclarationValidationError):
        validate_declaration(declaration, root=ROOT)


@pytest.mark.parametrize("field", ["decision", "reruns_runtime", "operator_registry"])
def test_external_admission_discovery_preserves_review_only(declaration: dict[str, Any], field: str) -> None:
    admission = declaration["runtime_self_service_procedures"][0]["external_admission"]
    admission[field] = True if field == "reruns_runtime" else "ADMITTED"
    with pytest.raises(DeclarationValidationError):
        validate_declaration(declaration, root=ROOT)
