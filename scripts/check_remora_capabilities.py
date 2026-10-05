#!/usr/bin/env python3
"""Validate the machine-readable REMORA capability declaration."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = ROOT / "docs/interop/remora-capabilities-v1.yaml"
SCHEMA = ROOT / "docs/interop/remora-capabilities-v1.schema.json"
MATURITY_ORDER = {
    "DECLARED": 0,
    "IMPLEMENTED": 1,
    "TESTED": 2,
    "REPRODUCIBLE": 3,
    "EXTERNALLY_REPRODUCED": 4,
    "OPERATOR_OBSERVED": 5,
}
CAPABILITY_ID = re.compile(r"^CAP-(?:\d{3}|META)$")
CLAIM_ID = re.compile(r"^CLAIM-\d{3}$")


class DeclarationValidationError(ValueError):
    """The declaration failed schema or cross-reference validation."""


def _relative_file_exists(root: Path, value: str) -> bool:
    path = value.split("#", maxsplit=1)[0]
    return bool(path) and (root / path).exists()


def _highest_maturity(maturity: dict[str, Any]) -> str:
    if maturity["operator_observed"]:
        return "OPERATOR_OBSERVED"
    if maturity["externally_reproduced"]:
        return "EXTERNALLY_REPRODUCED"
    if maturity["reproducible"]:
        return "REPRODUCIBLE"
    if maturity["tested"]:
        return "TESTED"
    if maturity["implemented"]:
        return "IMPLEMENTED"
    return "DECLARED"


def validate_declaration(data: Any, root: Path = ROOT) -> None:
    """Raise with all detected problems; otherwise return normally."""
    schema = json.loads((root / SCHEMA.relative_to(ROOT)).read_text(encoding="utf-8"))
    errors = [
        f"schema: {error.message}"
        for error in Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(data)
    ]
    if errors:
        raise DeclarationValidationError("\n".join(errors))

    workflow = data["workflow_capabilities"]
    self_service = data["self_service_capabilities"]
    capability_register = yaml.safe_load(
        (root / "docs/assurance/capability_register_v1.yaml").read_text(encoding="utf-8")
    )
    claim_register = yaml.safe_load(
        (root / "docs/assurance/claim_register_v1.yaml").read_text(encoding="utf-8")
    )
    known_capability_ids = {item["id"] for item in capability_register["capabilities"]}
    known_claim_ids = {item["id"] for item in claim_register["claims"]}
    interop_index_path = root / "artifacts/interop/index.json"
    interop_index = (
        json.loads(interop_index_path.read_text(encoding="utf-8"))
        if interop_index_path.is_file()
        else {"contracts": []}
    )
    workflow_ids = [cap["id"] for cap in workflow]
    self_service_ids = [cap["id"] for cap in self_service]
    if len(workflow_ids) != len(set(workflow_ids)):
        errors.append("workflow capability IDs must be unique")
    if len(self_service_ids) != len(set(self_service_ids)):
        errors.append("self-service capability IDs must be unique")
    workflow_by_id = {cap["id"]: cap for cap in workflow}

    for cap in workflow:
        evidence = cap["evidence"]
        trust_boundary = cap["trust_boundary"]
        if (
            trust_boundary["remora_executor_holds_execution_credentials"]
            and trust_boundary["remora_authority_process_holds_execution_credentials"]
        ):
            errors.append(
                f"{cap['id']}: authority and executor credential custody must remain separate"
            )
        if not any(
            evidence[key]
            for key in ("capability_ids", "claim_ids", "implementation", "tests")
        ):
            errors.append(f"{cap['id']}: capability evidence references are required")
        for capability_id in evidence["capability_ids"]:
            if not CAPABILITY_ID.fullmatch(capability_id):
                errors.append(f"{cap['id']}: malformed capability ID {capability_id!r}")
            elif capability_id not in known_capability_ids:
                errors.append(f"{cap['id']}: unknown capability register ID {capability_id}")
        for claim_id in evidence["claim_ids"]:
            if not CLAIM_ID.fullmatch(claim_id):
                errors.append(f"{cap['id']}: malformed claim ID {claim_id!r}")
            elif claim_id not in known_claim_ids:
                errors.append(f"{cap['id']}: unknown claim register ID {claim_id}")
        for key in ("implementation", "tests", "external_runs", "operator_records"):
            for ref in evidence[key]:
                if not _relative_file_exists(root, ref):
                    errors.append(f"{cap['id']}: evidence reference does not exist: {ref}")
        for item in evidence["production"]:
            if not _relative_file_exists(root, item["reference"]):
                errors.append(
                    f"{cap['id']}: production evidence reference does not exist: {item['reference']}"
                )

        maturity = cap["maturity"]
        if maturity["tested"] and not maturity["implemented"]:
            errors.append(f"{cap['id']}: tested requires implemented")
        if maturity["reproducible"] and not maturity["tested"]:
            errors.append(f"{cap['id']}: reproducible requires tested")
        if maturity["externally_reproduced"]:
            if not maturity["reproducible"] or not evidence["external_runs"]:
                errors.append(
                    f"{cap['id']}: external reproduction requires reproducible maturity and external run evidence"
                )
        if maturity["operator_observed"] and not evidence["operator_records"]:
            errors.append(f"{cap['id']}: operator-observed maturity requires operator record evidence")
        if maturity["production_established"]:
            if not evidence["production"]:
                errors.append(f"{cap['id']}: production maturity requires production evidence")
            if not maturity["externally_reproduced"] or not maturity["operator_observed"]:
                errors.append(
                    f"{cap['id']}: production maturity requires external reproduction and operator observation"
                )
        expected_level = _highest_maturity(maturity)
        if maturity["level"] != expected_level:
            errors.append(
                f"{cap['id']}: maturity level {maturity['level']} conflicts with flags; expected {expected_level}"
            )

    for cap in self_service:
        if cap["capability_ref"] not in workflow_by_id:
            errors.append(
                f"{cap['id']}: references nonexistent workflow capability {cap['capability_ref']}"
            )
        if cap["availability"] == "self_service":
            if not cap["claim_ceiling"].strip():
                errors.append(f"{cap['id']}: self-service capability requires a claim ceiling")
            if not cap["procedure"]["reference"].strip():
                errors.append(f"{cap['id']}: self-service capability requires a procedure reference")
            if cap["procedure"]["mode"] == "manual" and not cap["operator_assistance_required"]:
                errors.append(
                    f"{cap['id']}: a manual procedure cannot set operator_assistance_required to false"
                )
            if not cap["procedure"]["executable"] and not cap["operator_assistance_required"]:
                errors.append(
                    f"{cap['id']}: a non-executable procedure cannot set operator_assistance_required to false"
                )
            workflow_capability = workflow_by_id.get(cap["capability_ref"])
            if cap["scope"] == "frozen_fixture_contract_only":
                if cap["runtime_reproduction_status"] != "NOT_READY":
                    errors.append(
                        f"{cap['id']}: fixture-only scope cannot claim runtime reproduction readiness"
                    )
            elif (
                cap["runtime_reproduction_status"] == "READY"
                and (
                    workflow_capability is None
                    or not workflow_capability["maturity"]["reproducible"]
                )
            ):
                errors.append(
                    f"{cap['id']}: runtime reproduction readiness requires reproducible workflow maturity"
                )
            for ref in [cap["procedure"]["reference"], cap["frozen_target"]["manifest"]]:
                if not _relative_file_exists(root, ref):
                    errors.append(f"{cap['id']}: procedure or manifest reference does not exist: {ref}")
            target = cap["frozen_target"]
            manifest_path = root / target["manifest"]
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("package_digest") != target["package_digest"]:
                    errors.append(f"{cap['id']}: package digest does not match manifest")
                if manifest.get("source_revision") != target["source_revision"]:
                    errors.append(f"{cap['id']}: source revision does not match manifest")
                contracts = [
                    contract
                    for contract in interop_index["contracts"]
                    if contract.get("manifest") == target["manifest"]
                ]
                if len(contracts) != 1:
                    errors.append(f"{cap['id']}: manifest must identify one interop index contract")
                elif (
                    contracts[0].get("freeze_record", {}).get("revision")
                    != target["frozen_at_revision"]
                ):
                    errors.append(f"{cap['id']}: frozen revision does not match interop index")
            for artifact in target["artifacts"]:
                path = root / artifact["path"]
                if not path.is_file():
                    errors.append(f"{cap['id']}: frozen artifact does not exist: {artifact['path']}")
                elif hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                    errors.append(f"{cap['id']}: frozen artifact digest mismatch: {artifact['path']}")

    audit_ids = [item["id"] for item in data["capability_audit"]["investigated"]]
    if len(audit_ids) != len(set(audit_ids)):
        errors.append("investigated candidate IDs must be unique")
    declared_audit_ids = {
        item["id"]
        for item in data["capability_audit"]["investigated"]
        if item["disposition"] == "DECLARED"
    }
    if declared_audit_ids != set(workflow_ids):
        errors.append("DECLARED audit candidates must match workflow capability IDs exactly")

    gap_refs = [gap["capability_ref"] for gap in data["self_service_gaps"]]
    if len(gap_refs) != len(set(gap_refs)):
        errors.append("self-service gap capability references must be unique")
    for gap in data["self_service_gaps"]:
        if gap["capability_ref"] not in workflow_by_id:
            errors.append(
                f"self-service gap references nonexistent workflow capability {gap['capability_ref']}"
            )

    for source in data["provenance"]["source_of_truth"]:
        if not _relative_file_exists(root, source):
            errors.append(f"provenance source does not exist: {source}")
    for item in data["capability_audit"]["investigated"]:
        for evidence_ref in item["evidence"]:
            if CAPABILITY_ID.fullmatch(evidence_ref):
                if evidence_ref not in known_capability_ids:
                    errors.append(f"{item['id']}: unknown capability register ID {evidence_ref}")
            elif CLAIM_ID.fullmatch(evidence_ref):
                if evidence_ref not in known_claim_ids:
                    errors.append(f"{item['id']}: unknown claim register ID {evidence_ref}")
            elif not _relative_file_exists(root, evidence_ref):
                errors.append(f"{item['id']}: audit evidence reference does not exist: {evidence_ref}")

    if errors:
        raise DeclarationValidationError("\n".join(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        data = yaml.safe_load((root / DECLARATION.relative_to(ROOT)).read_text(encoding="utf-8"))
        validate_declaration(data, root=root)
    except (OSError, json.JSONDecodeError, yaml.YAMLError, DeclarationValidationError) as exc:
        print(f"REMORA capability declaration invalid: {exc}", file=sys.stderr)
        return 1
    print("REMORA capability declaration is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
