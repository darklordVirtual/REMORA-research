#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Validate the fail-closed REMORA boundary declaration."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from jsonschema import Draft202012Validator

# Run as `python scripts/<name>.py` in jobs without an installed package
# (documentation-governance): put the repository root on sys.path first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.interop_package import package_digest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs/interop/remora-boundaries-v1.yaml"
SCHEMA = ROOT / "docs/interop/remora-boundaries-v1.schema.json"
CAPABILITIES = "docs/interop/remora-capabilities-v1.yaml"
CAPABILITY_REGISTER = "docs/assurance/capability_register_v1.yaml"
INTEROP_INDEX = "artifacts/interop/index.json"
FEDERATION_MANIFEST = "artifacts/interop/FEDERATION.yaml"
RUNS_DIR = "artifacts/interop/runs"
MATURITY_ORDER = {
    "DECLARED": 0,
    "IMPLEMENTED": 1,
    "TESTED": 2,
    "REPRODUCIBLE": 3,
    "EXTERNALLY_REPRODUCED": 4,
    "OPERATOR_OBSERVED": 5,
}
EXPECTED_PIN_PATHS = {
    CAPABILITIES,
    CAPABILITY_REGISTER,
    INTEROP_INDEX,
    FEDERATION_MANIFEST,
    "artifacts/interop/runtime-surface-e7-v0.1/manifest.json",
}
E7_NEGATIVE_CASES = {
    "undeclared_tool_invocation_surface",
    "runtime_identity_changed",
    "observation_coverage_incomplete",
    "alternative_effect_path_observed",
}


class BoundaryValidationError(ValueError):
    """The boundary register failed schema, freshness or evidence validation."""


def _load_yaml(root: Path, rel: str) -> dict[str, Any]:
    value = yaml.safe_load((root / rel).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BoundaryValidationError(f"{rel}: expected a mapping")
    return value


def _load_json(root: Path, rel: str) -> dict[str, Any]:
    value = json.loads((root / rel).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BoundaryValidationError(f"{rel}: expected an object")
    return value


def _safe_path(root: Path, value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise BoundaryValidationError(f"unsafe repository path: {value!r}")
    resolved = (root / Path(*path.parts)).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise BoundaryValidationError(f"path escapes repository: {value!r}")
    return resolved


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _check_revision_and_implementation_freshness(
    provenance: dict[str, Any], root: Path, head_ref: str
) -> None:
    shallow = _git(root, "rev-parse", "--is-shallow-repository")
    if shallow.returncode != 0 or shallow.stdout.strip() == "true":
        raise BoundaryValidationError(
            "cannot establish boundary freshness from a shallow or invalid Git history"
        )

    revision = provenance["audited_revision"]
    exists = _git(root, "cat-file", "-e", f"{revision}^{{commit}}")
    if exists.returncode != 0:
        raise BoundaryValidationError(
            f"audited revision {revision[:12]} is not resolvable"
        )
    head = _git(root, "rev-parse", "--verify", f"{head_ref}^{{commit}}")
    if head.returncode != 0:
        raise BoundaryValidationError(f"freshness ref {head_ref!r} is not a commit")
    head_commit = head.stdout.strip()
    reachable = _git(root, "merge-base", "--is-ancestor", revision, head_commit)
    if reachable.returncode != 0:
        raise BoundaryValidationError(
            f"audited revision {revision[:12]} is not reachable from {head_ref}"
        )

    sources = provenance["implementation_sources"]
    for args, label in (
        (("diff", "--quiet", revision, head_commit, "--", *sources), "changed since audit"),
        (("diff", "--quiet", "HEAD", "--", *sources), "changed in the worktree"),
        (("diff", "--cached", "--quiet", "HEAD", "--", *sources), "staged in the worktree"),
    ):
        result = _git(root, *args)
        if result.returncode == 1:
            raise BoundaryValidationError(
                f"implementation source {label}; re-audit before advancing boundary status"
            )
        if result.returncode != 0:
            raise BoundaryValidationError(
                f"cannot verify implementation freshness ({label}): {result.stderr.strip()}"
            )


def _validate_source_pins(data: dict[str, Any], root: Path) -> None:
    pins = data["provenance"]["source_pins"]
    paths = [item["path"] for item in pins]
    if len(paths) != len(set(paths)):
        raise BoundaryValidationError("source pin paths must be unique")
    if set(paths) != EXPECTED_PIN_PATHS:
        raise BoundaryValidationError(
            "source pins must cover exactly the capability declaration, capability "
            "register, interop index, Federation manifest and E7 manifest"
        )
    for item in pins:
        path = _safe_path(root, item["path"])
        if not path.is_file():
            raise BoundaryValidationError(f"pinned source does not exist: {item['path']}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != item["sha256"]:
            raise BoundaryValidationError(
                f"source digest mismatch for {item['path']}: expected {item['sha256']}, got {actual}"
            )


def _validate_capabilities(
    data: dict[str, Any], root: Path
) -> None:
    from scripts.check_capability_freshness import classify, load_register
    from scripts.check_remora_capabilities import validate_declaration

    declaration = _load_yaml(root, CAPABILITIES)
    try:
        validate_declaration(declaration, root=root)
    except ValueError as exc:
        raise BoundaryValidationError(
            f"supporting capability declaration is invalid: {exc}"
        ) from exc
    capability_register = load_register(root / CAPABILITY_REGISTER)
    known_register_ids = {
        item["id"]: item for item in capability_register["capabilities"]
    }
    workflow_by_id = {
        item["id"]: item for item in declaration["workflow_capabilities"]
    }
    surface_property = next(
        (
            item
            for item in capability_register.get("unestablished_properties", [])
            if item["id"] == "runtime_capability_surface_completeness"
        ),
        None,
    )
    declared_surface = data["runtime_capability_surface_completeness"]
    if (
        surface_property is None
        or surface_property["status"] != "NOT_ESTABLISHED"
        or declared_surface["status"] != surface_property["status"]
        or declared_surface["evidence"] != surface_property["evidence"]
    ):
        raise BoundaryValidationError(
            "runtime_capability_surface_completeness must match the capability register"
        )
    if not _safe_path(root, declared_surface["evidence"]).is_file():
        raise BoundaryValidationError(
            "runtime_capability_surface_completeness evidence is missing"
        )
    references: set[str] = set()
    for section in (
        "internal_trust_boundaries",
        "external_interfaces",
        "federation_edges",
        "observation_roles",
    ):
        for item in data[section]:
            references.update(item["supporting_capabilities"])

    for reference in sorted(references):
        capability = workflow_by_id.get(reference)
        if capability is None:
            raise BoundaryValidationError(
                f"unknown workflow capability reference: {reference}"
            )
        if not capability["evidence"]["capability_ids"]:
            raise BoundaryValidationError(
                f"{reference}: supporting capability register references are required"
            )
        for capability_id in capability["evidence"]["capability_ids"]:
            register_capability = known_register_ids.get(capability_id)
            if register_capability is None:
                raise BoundaryValidationError(
                    f"{reference}: unknown capability register ID {capability_id}"
                )
            status, detail = classify(register_capability, cwd=root)
            if status != "BOUND":
                raise BoundaryValidationError(
                    f"{reference}: capability {capability_id} is {status}: {detail}"
                )

    for section in (
        "internal_trust_boundaries",
        "external_interfaces",
        "federation_edges",
        "observation_roles",
    ):
        for item in data[section]:
            ceiling = item["maturity"]
            for reference in item["supporting_capabilities"]:
                actual = workflow_by_id[reference]["maturity"]["level"]
                if MATURITY_ORDER[ceiling] > MATURITY_ORDER[actual]:
                    raise BoundaryValidationError(
                        f"{item['id']}: maturity {ceiling} exceeds supporting "
                        f"capability {reference} maturity {actual}"
                    )
def _validate_e7_artifacts(edge: dict[str, Any], root: Path) -> None:
    manifest = _load_json(
        root, "artifacts/interop/runtime-surface-e7-v0.1/manifest.json"
    )
    expected = {
        item["path"]: item["sha256"] for item in manifest["package_files"]
    }
    expected.update(
        {item["path"]: item["sha256"] for item in manifest["source_artifacts"]}
    )
    actual = {item["path"]: item["sha256"] for item in edge["pinned_artifacts"]}
    if actual != expected or len(edge["pinned_artifacts"]) != len(actual):
        raise BoundaryValidationError(
            "E7 pinned_artifacts must match the package and source artifact digests in its manifest"
        )
    for item in edge["pinned_artifacts"]:
        path = _safe_path(root, item["path"])
        if not path.is_file():
            raise BoundaryValidationError(f"E7 pinned artifact is missing: {item['path']}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise BoundaryValidationError(
                f"E7 artifact digest mismatch for {item['path']}"
            )

    fixtures = _load_json(
        root, "artifacts/interop/runtime-surface-e7-v0.1/fixtures.json"
    )
    case_ids = {case["id"] for case in fixtures["cases"]}
    if not E7_NEGATIVE_CASES.issubset(case_ids):
        raise BoundaryValidationError("E7 fixture set lost a required negative case")
    if not E7_NEGATIVE_CASES.issubset(set(edge["negative_case_ids"])):
        raise BoundaryValidationError("E7 boundary omits a required negative case")
    if not set(edge["negative_case_ids"]).issubset(case_ids):
        raise BoundaryValidationError("E7 boundary names an unknown fixture case")


def _expected_dimensions(contract: dict[str, Any], root: Path) -> dict[str, tuple[str, set[str]]]:
    confirmations = contract.get("pin_confirmed_to", [])
    external_runs = contract.get("external_runs", [])
    contract_id = contract["id"]
    run_paths = sorted(
        path.relative_to(root).as_posix()
        for path in (root / RUNS_DIR).glob("*.json")
        if _load_json(root, path.relative_to(root).as_posix()).get("contract_id")
        == contract_id
    )
    if external_runs:
        execution_status = "EXTERNAL_RUN_RECORDED"
        execution_refs = {item["run_ref"] for item in external_runs}
        independence_values = {item["independence"] for item in external_runs}
        independence_status = (
            "INDEPENDENT" if "INDEPENDENT" in independence_values else "NOT_INDEPENDENT"
        )
        independence_refs = {item["run_ref"] for item in external_runs}
    elif run_paths:
        execution_status = "AUTHOR_RUN"
        execution_refs = set(run_paths)
        independence_status = "NOT_ASSESSED"
        independence_refs = set()
    else:
        execution_status = "NOT_RUN"
        execution_refs = set()
        independence_status = "NOT_ASSESSED"
        independence_refs = set()

    return {
        "owner_confirmation": ("NOT_CONFIRMED", set()),
        "pinning": (
            "PIN_CONFIRMED" if confirmations else "UNPINNED",
            {item["where"] for item in confirmations},
        ),
        "execution": (execution_status, execution_refs),
        "independence": (independence_status, independence_refs),
        "claim_result": (
            "NOT_ESTABLISHED",
            {item["run_ref"] for item in external_runs}
            if external_runs
            else set(run_paths),
        ),
        "production": ("NOT_ESTABLISHED", set()),
        "federation_adoption": ("NOT_ADOPTED", set()),
    }


def _validate_federation_edges(data: dict[str, Any], root: Path) -> None:
    index = _load_json(root, INTEROP_INDEX)
    if index.get("boundary_summary") != "artifacts/interop/remora-boundary-summary-v1.json":
        raise BoundaryValidationError(
            "interop index must discover artifacts/interop/remora-boundary-summary-v1.json"
        )
    federation = _load_yaml(root, FEDERATION_MANIFEST)
    contracts = {item["id"]: item for item in index["contracts"]}
    declared_edges = {item["id"]: item for item in federation["edges"]}
    boundary_ids: set[str] = set()
    for edge in data["federation_edges"]:
        if edge["id"] in boundary_ids:
            raise BoundaryValidationError(f"duplicate boundary edge ID: {edge['id']}")
        boundary_ids.add(edge["id"])
        contract = contracts.get(edge["contract_id"])
        if contract is None:
            raise BoundaryValidationError(
                f"{edge['id']}: unknown interop contract {edge['contract_id']}"
            )
        if edge["package_digest"] != contract["package_digest"]:
            raise BoundaryValidationError(
                f"{edge['id']}: package digest differs from the interop index"
            )
        manifest = _load_json(root, contract["manifest"])
        if (
            manifest.get("package_digest") != edge["package_digest"]
            or package_digest(manifest["package_files"]) != edge["package_digest"]
        ):
            raise BoundaryValidationError(
                f"{edge['id']}: package digest does not match its manifest"
            )
        for artifact in manifest["package_files"]:
            path = _safe_path(root, artifact["path"])
            if not path.is_file():
                raise BoundaryValidationError(
                    f"{edge['id']}: package artifact is missing: {artifact['path']}"
                )
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != artifact["sha256"]:
                raise BoundaryValidationError(
                    f"{edge['id']}: package artifact digest mismatch: {artifact['path']}"
                )
        manifest_edge = declared_edges.get(edge["id"])
        if (
            manifest_edge is None
            or manifest_edge.get("contract") != edge["contract_id"]
            or contract["edge"] != edge["id"]
        ):
            raise BoundaryValidationError(
                f"{edge['id']}: contract does not match the Federation manifest and index"
            )
        if edge["id"] == "E7":
            _validate_e7_artifacts(edge, root)

        expected = _expected_dimensions(contract, root)
        dimensions = edge["status_dimensions"]
        for name, (status, evidence) in expected.items():
            dimension = dimensions[name]
            if dimension["status"] != status:
                raise BoundaryValidationError(
                    f"{edge['id']}: {name} status must be {status}, derived from records"
                )
            if set(dimension["evidence"]) != evidence:
                raise BoundaryValidationError(
                    f"{edge['id']}: {name} evidence does not match committed records"
                )
        if dimensions["independence"]["status"] == "INDEPENDENT":
            for run in contract["external_runs"]:
                if run["independence"] != "INDEPENDENT":
                    continue
                if (
                    run["implementation_diversity"] != "SECOND_IMPLEMENTATION"
                    or run["operator"] != "EXTERNAL"
                    or run["verifier"]["maintained_by"] != "EXTERNAL"
                    or run["imports"]["remora_runtime"]
                    or run["imports"]["reference_verifier"]
                ):
                    raise BoundaryValidationError(
                        f"{edge['id']}: independence conditions are not evidenced"
                    )
        if dimensions["claim_result"]["status"] != "NOT_ESTABLISHED":
            raise BoundaryValidationError(
                f"{edge['id']}: no aggregate boundary-level claim result is recorded"
            )
        if dimensions["production"]["status"] != "NOT_ESTABLISHED":
            raise BoundaryValidationError(
                f"{edge['id']}: no production evidence is registered"
            )
        if dimensions["federation_adoption"]["status"] != "NOT_ADOPTED":
            raise BoundaryValidationError(
                f"{edge['id']}: no Federation adoption evidence is registered"
            )
    if not {"E-ECB", "E-FA", "E-EE", "E7", "E8"}.issubset(boundary_ids):
        raise BoundaryValidationError("boundary register omits a declared execution edge")


def _validate_role_mappings(data: dict[str, Any]) -> None:
    mappings = {item["id"]: item for item in data["role_mappings"]}
    if len(mappings) != len(data["role_mappings"]):
        raise BoundaryValidationError("role mapping IDs must be unique")
    if set(mappings) != {
        "agv-186-187-boundary-roles",
        "agv-179-runtime-observation",
    }:
        raise BoundaryValidationError("AGV role mapping inventory is incomplete")
    control = mappings["agv-186-187-boundary-roles"]
    if (
        control["issue_numbers"] != [186, 187]
        or control["assessment"] != "CANDIDATE"
        or control["candidate_roles"]
        != ["exact_call_authorization", "tool_enforcement"]
        or control["partial_roles"] != ["pre_action_decision", "revocation"]
    ):
        raise BoundaryValidationError(
            "AGV #186/#187 mappings must keep exact-call authorization and tool enforcement as candidates, with pre-action decision and revocation partial"
        )
    observation = mappings["agv-179-runtime-observation"]
    if (
        observation["issue_numbers"] != [179]
        or observation["assessment"] != "PARTIAL"
        or observation["candidate_roles"]
        or observation["partial_roles"] != ["runtime_surface_observation"]
    ):
        raise BoundaryValidationError(
            "AGV #179 mapping must remain partial until the runtime observation is externally assessed"
        )


def _validate_claim_ceilings(data: dict[str, Any]) -> None:
    targets = {
        ("RUNTIME_PROPERTY", "runtime_capability_surface_completeness"): data[
            "runtime_capability_surface_completeness"
        ]["claim_ceiling_ref"]
    }
    for section, target_type in (
        ("internal_trust_boundaries", "INTERNAL_TRUST_BOUNDARY"),
        ("external_interfaces", "EXTERNAL_INTERFACE"),
        ("federation_edges", "FEDERATION_EDGE"),
        ("role_mappings", "ROLE_MAPPING"),
        ("observation_roles", "OBSERVATION_ROLE"),
    ):
        for item in data[section]:
            target = (target_type, item["id"])
            if target in targets:
                raise BoundaryValidationError(
                    f"duplicate boundary target: {target_type} {item['id']}"
                )
            targets[target] = item["claim_ceiling_ref"]

    ceilings_by_id: dict[str, dict[str, Any]] = {}
    ceilings_by_target: dict[tuple[str, str], dict[str, Any]] = {}
    for ceiling in data["claim_ceilings"]:
        if ceiling["id"] in ceilings_by_id:
            raise BoundaryValidationError(
                f"duplicate claim ceiling ID: {ceiling['id']}"
            )
        target = (ceiling["applies_to"], ceiling["target_id"])
        if target in ceilings_by_target:
            raise BoundaryValidationError(
                f"duplicate claim ceiling target: {target[0]} {target[1]}"
            )
        ceilings_by_id[ceiling["id"]] = ceiling
        ceilings_by_target[target] = ceiling

    if set(ceilings_by_target) != set(targets):
        raise BoundaryValidationError(
            "claim ceilings must cover each declared boundary, role and runtime property exactly once"
        )
    for target, reference in targets.items():
        ceiling = ceilings_by_id.get(reference)
        if ceiling is None:
            raise BoundaryValidationError(
                f"{target[0]} {target[1]} references unknown claim ceiling {reference}"
            )
        if (ceiling["applies_to"], ceiling["target_id"]) != target:
            raise BoundaryValidationError(
                f"claim ceiling {reference} is attached to the wrong boundary or role"
            )


def validate_boundary_register(data: Any, root: Path = ROOT) -> None:
    """Raise with all detected problems; otherwise the declaration is current."""
    schema = _load_json(root, SCHEMA.relative_to(ROOT).as_posix())
    errors = sorted(
        Draft202012Validator(schema).iter_errors(data),
        key=lambda error: (list(error.path), error.message),
    )
    if errors:
        raise BoundaryValidationError(
            "\n".join(
                f"schema: {error.message} at {'/'.join(map(str, error.path)) or '<root>'}"
                for error in errors
            )
        )
    _validate_claim_ceilings(data)
    _check_revision_and_implementation_freshness(data["provenance"], root, "HEAD")
    _validate_source_pins(data, root)
    _validate_capabilities(data, root)
    _validate_federation_edges(data, root)
    _validate_role_mappings(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        data = _load_yaml(root, REGISTER.relative_to(ROOT).as_posix())
        validate_boundary_register(data, root=root)
    except (
        OSError,
        json.JSONDecodeError,
        yaml.YAMLError,
        BoundaryValidationError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"REMORA boundary declaration invalid: {exc}", file=sys.stderr)
        return 1
    print("REMORA boundary declaration is current and within its evidence ceiling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
