#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Generate the bounded Federation-facing summary from the boundary register."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

# Run as `python scripts/<name>.py` in jobs without an installed package
# (documentation-governance): put the repository root on sys.path first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_remora_boundaries import (  # noqa: E402
    REGISTER,
    ROOT,
    validate_boundary_register,
)

OUT = ROOT / "artifacts/interop/remora-boundary-summary-v1.json"


def derive(data: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Project the register into a bounded, non-authorizing discovery document."""
    validate_boundary_register(data, root=root)
    register_path = root / REGISTER.relative_to(ROOT)

    def statuses(dimensions: dict[str, dict[str, Any]]) -> dict[str, str]:
        return {name: value["status"] for name, value in dimensions.items()}

    boundaries = []
    for section_name, category in (
        ("internal_trust_boundaries", "INTERNAL_TRUST_BOUNDARY"),
        ("external_interfaces", "EXTERNAL_INTERFACE"),
    ):
        for item in data[section_name]:
            boundaries.append(
                {
                    "id": item["id"],
                    "category": category,
                    "maturity": item["maturity"],
                    "supporting_capabilities": item["supporting_capabilities"],
                    "claim_ceiling_ref": item["claim_ceiling_ref"],
                }
            )

    federation_edges = []
    for item in data["federation_edges"]:
        federation_edges.append(
            {
                "edge": item["id"],
                "contract_id": item["contract_id"],
                "package_digest": item["package_digest"],
                "producer_role": item["producer_role"],
                "consumer_role": item["consumer_role"],
                "maturity": item["maturity"],
                "claim_ceiling_ref": item["claim_ceiling_ref"],
                "negative_case_ids": item["negative_case_ids"],
                "pinned_artifacts": item["pinned_artifacts"],
                "status_dimensions": statuses(item["status_dimensions"]),
            }
        )

    return {
        "schema_version": "remora-boundary-summary-v1",
        "producer": {
            "project": "REMORA",
            "repository": "darklordVirtual/REMORA-research",
            "register": "docs/interop/remora-boundaries-v1.yaml",
            "register_sha256": hashlib.sha256(register_path.read_bytes()).hexdigest(),
            "audited_revision": data["provenance"]["audited_revision"],
            "freshness": "CURRENT",
        },
        "evidence_index": "artifacts/interop/index.json",
        "global_claim_ceiling": {
            "automatic_authority": False,
            "endorsement": False,
            "production_established": False,
            "federation_adoption_implied": False,
            "runtime_capability_surface_completeness": "NOT_ESTABLISHED",
        },
        "internal_trust_boundaries": [
            boundary
            for boundary in boundaries
            if boundary["category"] == "INTERNAL_TRUST_BOUNDARY"
        ],
        "external_interfaces": [
            boundary
            for boundary in boundaries
            if boundary["category"] == "EXTERNAL_INTERFACE"
        ],
        "federation_edges": federation_edges,
        "claim_ceilings": data["claim_ceilings"],
        "role_mappings": data["role_mappings"],
        "observation_roles": data["observation_roles"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    register_path = root / REGISTER.relative_to(ROOT)
    output_path = root / OUT.relative_to(ROOT)
    try:
        data = yaml.safe_load(register_path.read_text(encoding="utf-8"))
        summary = derive(data, root=root)
    except (OSError, json.JSONDecodeError, yaml.YAMLError, ValueError, KeyError) as exc:
        print(f"[FAIL] cannot build boundary summary: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        current = output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
        if current != rendered:
            print(
                f"[FAIL] {output_path.relative_to(root)} is stale; "
                "run python scripts/build_remora_boundary_summary.py --write"
            )
            return 1
        print(f"[PASS] {output_path.relative_to(root)} matches the boundary register")
        return 0
    output_path.write_text(rendered, encoding="utf-8")
    print(f"[WRITE] {output_path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
