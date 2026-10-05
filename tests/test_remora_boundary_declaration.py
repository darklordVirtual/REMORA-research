"""Fail-closed contracts for REMORA boundary discovery."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

import scripts.check_capability_freshness as capability_freshness
from scripts.build_remora_boundary_summary import OUT, derive
from scripts.check_remora_boundaries import (
    REGISTER,
    SCHEMA,
    BoundaryValidationError,
    _check_revision_and_implementation_freshness,
    validate_boundary_register,
)

pytestmark = pytest.mark.docgate
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def declaration() -> dict[str, Any]:
    return yaml.safe_load(REGISTER.read_text(encoding="utf-8"))


def _edge(data: dict[str, Any], edge_id: str) -> dict[str, Any]:
    return next(item for item in data["federation_edges"] if item["id"] == edge_id)


def test_committed_boundary_register_and_summary_validate(
    declaration: dict[str, Any],
) -> None:
    validate_boundary_register(declaration, root=ROOT)
    summary = json.loads(OUT.read_text(encoding="utf-8"))
    assert summary == derive(declaration, root=ROOT)
    assert (
        summary["global_claim_ceiling"]["runtime_capability_surface_completeness"]
        == "NOT_ESTABLISHED"
    )
    assert summary["global_claim_ceiling"]["production_established"] is False
    assert summary["global_claim_ceiling"]["federation_adoption_implied"] is False
    e7 = next(item for item in summary["federation_edges"] if item["edge"] == "E7")
    assert summary["producer"]["freshness"] == "CURRENT"
    assert len(e7["pinned_artifacts"]) == 8
    assert e7["claim_ceiling_ref"] == "cc-edge-e7"
    assert any(
        item["id"] == "cc-edge-e7"
        and item["applies_to"] == "FEDERATION_EDGE"
        and item["target_id"] == "E7"
        for item in summary["claim_ceilings"]
    )
    assert e7["status_dimensions"] == {
        "owner_confirmation": "NOT_CONFIRMED",
        "pinning": "PIN_CONFIRMED",
        "execution": "NOT_RUN",
        "independence": "NOT_ASSESSED",
        "claim_result": "NOT_ESTABLISHED",
        "production": "NOT_ESTABLISHED",
        "federation_adoption": "NOT_ADOPTED",
    }


def test_schema_is_a_valid_draft_2020_12_schema() -> None:
    jsonschema.Draft202012Validator.check_schema(
        json.loads(SCHEMA.read_text(encoding="utf-8"))
    )


def test_unknown_workflow_capability_reference_is_rejected(
    declaration: dict[str, Any],
) -> None:
    _edge(declaration, "E-ECB")["supporting_capabilities"] = ["missing_capability"]
    with pytest.raises(BoundaryValidationError, match="unknown workflow capability"):
        validate_boundary_register(declaration, root=ROOT)


def test_claim_ceiling_reference_must_resolve_to_its_boundary(
    declaration: dict[str, Any],
) -> None:
    declaration["external_interfaces"][0]["claim_ceiling_ref"] = "missing_ceiling"
    with pytest.raises(BoundaryValidationError, match="unknown claim ceiling"):
        validate_boundary_register(declaration, root=ROOT)


def test_stale_supporting_capability_is_rejected(
    declaration: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        capability_freshness,
        "classify",
        lambda capability, cwd: ("STALE", "source changed after audit"),
    )
    with pytest.raises(BoundaryValidationError, match="is STALE"):
        validate_boundary_register(declaration, root=ROOT)


def test_boundary_maturity_cannot_exceed_supporting_capability(
    declaration: dict[str, Any],
) -> None:
    _edge(declaration, "E7")["maturity"] = "OPERATOR_OBSERVED"
    with pytest.raises(BoundaryValidationError, match="exceeds supporting capability"):
        validate_boundary_register(declaration, root=ROOT)


def test_external_execution_status_requires_a_committed_run_record(
    declaration: dict[str, Any],
) -> None:
    dimensions = _edge(declaration, "E7")["status_dimensions"]
    dimensions["execution"] = {
        "status": "EXTERNAL_RUN_RECORDED",
        "evidence": ["https://example.invalid/run/1"],
    }
    with pytest.raises(BoundaryValidationError, match="execution status must be NOT_RUN"):
        validate_boundary_register(declaration, root=ROOT)


def test_independence_cannot_be_asserted_without_an_external_run(
    declaration: dict[str, Any],
) -> None:
    dimensions = _edge(declaration, "E7")["status_dimensions"]
    dimensions["independence"] = {
        "status": "INDEPENDENT",
        "evidence": ["https://example.invalid/run/1"],
    }
    with pytest.raises(BoundaryValidationError, match="independence status must be NOT_ASSESSED"):
        validate_boundary_register(declaration, root=ROOT)


def test_external_second_implementation_does_not_imply_independence(
    declaration: dict[str, Any],
) -> None:
    dimensions = _edge(declaration, "E-ECB")["status_dimensions"]
    dimensions["independence"]["status"] = "INDEPENDENT"
    with pytest.raises(BoundaryValidationError, match="independence status must be NOT_INDEPENDENT"):
        validate_boundary_register(declaration, root=ROOT)


def test_production_status_requires_evidence_and_stays_unestablished(
    declaration: dict[str, Any],
) -> None:
    dimensions = _edge(declaration, "E7")["status_dimensions"]
    dimensions["production"] = {
        "status": "ESTABLISHED",
        "evidence": ["artifacts/interop/runtime-surface-e7-v0.1/README.md"],
    }
    with pytest.raises(BoundaryValidationError, match="production status must be NOT_ESTABLISHED"):
        validate_boundary_register(declaration, root=ROOT)


def test_invalid_audit_revision_is_rejected(declaration: dict[str, Any]) -> None:
    declaration["provenance"]["audited_revision"] = "0" * 40
    with pytest.raises(BoundaryValidationError, match="not resolvable"):
        validate_boundary_register(declaration, root=ROOT)


def test_source_digest_mismatch_is_rejected(declaration: dict[str, Any]) -> None:
    declaration["provenance"]["source_pins"][0]["sha256"] = "0" * 64
    with pytest.raises(BoundaryValidationError, match="source digest mismatch"):
        validate_boundary_register(declaration, root=ROOT)


def test_e7_artifact_digest_mismatch_is_rejected(
    declaration: dict[str, Any],
) -> None:
    _edge(declaration, "E7")["pinned_artifacts"][0]["sha256"] = "0" * 64
    with pytest.raises(BoundaryValidationError, match="E7 pinned_artifacts"):
        validate_boundary_register(declaration, root=ROOT)


def test_contract_package_digest_mismatch_is_rejected(
    declaration: dict[str, Any],
) -> None:
    _edge(declaration, "E-ECB")["package_digest"] = "sha256:" + "0" * 64
    with pytest.raises(BoundaryValidationError, match="package digest differs"):
        validate_boundary_register(declaration, root=ROOT)


def test_global_surface_completeness_cannot_be_promoted(
    declaration: dict[str, Any],
) -> None:
    declaration["runtime_capability_surface_completeness"]["status"] = "ESTABLISHED"
    with pytest.raises(BoundaryValidationError, match="schema"):
        validate_boundary_register(declaration, root=ROOT)


def test_e7_alternative_path_negative_case_is_required(
    declaration: dict[str, Any],
) -> None:
    edge = _edge(declaration, "E7")
    edge["negative_case_ids"].remove("alternative_effect_path_observed")
    with pytest.raises(BoundaryValidationError, match="omits a required negative case"):
        validate_boundary_register(declaration, root=ROOT)


def test_internal_boundary_cannot_hide_known_bypass_paths(
    declaration: dict[str, Any],
) -> None:
    declaration["internal_trust_boundaries"][1]["bypass_paths"] = []
    with pytest.raises(BoundaryValidationError, match="schema"):
        validate_boundary_register(declaration, root=ROOT)


def test_pin_confirmation_does_not_imply_owner_confirmation(
    declaration: dict[str, Any],
) -> None:
    dimensions = _edge(declaration, "E7")["status_dimensions"]
    assert dimensions["pinning"]["status"] == "PIN_CONFIRMED"
    assert dimensions["owner_confirmation"]["status"] == "NOT_CONFIRMED"
    assert dimensions["execution"]["status"] == "NOT_RUN"
    assert dimensions["independence"]["status"] == "NOT_ASSESSED"


def test_implementation_changes_after_audit_fail_closed(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    source = tmp_path / "remora" / "enforcement" / "guard.py"
    source.parent.mkdir(parents=True)
    source.write_text("guard = True\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "audited source")
    audited = git("rev-parse", "HEAD")
    provenance = {
        "audited_revision": audited,
        "implementation_sources": ["remora/enforcement/guard.py"],
    }
    _check_revision_and_implementation_freshness(provenance, tmp_path, "HEAD")

    source.write_text("guard = False\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "changed source")
    with pytest.raises(BoundaryValidationError, match="changed since audit"):
        _check_revision_and_implementation_freshness(provenance, tmp_path, "HEAD")
