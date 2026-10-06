#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Check declared contract relationships; never propagate claim status."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from remora.interop.evidence_io import EvidenceError, decode_json, digest_bytes


def validate(index: dict[str, Any], graph: dict[str, Any], root: Path = ROOT) -> None:
    from jsonschema import Draft202012Validator, ValidationError

    schema = decode_json((root / "schemas/contract-dependencies-v1.schema.json").read_text())
    try:
        Draft202012Validator(schema).validate(graph)
    except ValidationError as exc:
        raise EvidenceError(f"contract graph schema: {exc.message}") from exc
    if (graph.get("schema_version") != "remora-contract-dependencies-v1"
            or graph.get("confers_authority") is not False or graph.get("status_inheritance") is not False):
        raise EvidenceError("contract graph must not confer authority or inherit status")
    known = {item["id"] for item in index["contracts"]}
    for item in index.get("optional_contracts", []):
        if item["id"] in known or item["lifecycle"] != "DRAFT" or item["implementation_status"] != "NOT_IMPLEMENTED":
            raise EvidenceError("optional contract duplicates an existing ID or upgrades implementation")
        definition_bytes = (root / item["definition"]).read_bytes()
        if digest_bytes(definition_bytes) != item["definition_digest"]:
            raise EvidenceError("optional contract definition digest mismatch")
        definition = decode_json(definition_bytes.decode())
        if (definition["contract_id"] != item["id"] or definition["lifecycle"] != "DRAFT"
                or definition["implementation_status"] != "NOT_IMPLEMENTED"
                or definition["source_revision"] != item["source_revision"] or not definition["claims"]
                or any(claim["remora_status"] != "NOT_ESTABLISHED" for claim in definition["claims"])):
            raise EvidenceError("optional contract cannot upgrade REMORA claims")
        if item["record_schema"] != definition["record_schema"]:
            raise EvidenceError("optional contract schema path mismatch")
        schema_bytes = (root / item["record_schema"]).read_bytes()
        if digest_bytes(schema_bytes) != item["record_schema_digest"]:
            raise EvidenceError("optional contract schema digest mismatch")
        Draft202012Validator.check_schema(decode_json(schema_bytes.decode()))
        known.add(item["id"])
    nodes = {item["contract_id"]: item for item in graph["contracts"]}
    if len(nodes) != len(graph["contracts"]) or set(nodes) != known:
        raise EvidenceError("contract graph must cover indexed IDs exactly once")
    properties = set(graph["properties"])
    for item in nodes.values():
        if not set(item["depends_on"]) <= known:
            raise EvidenceError("contract dependency names an unknown contract")
        if not set(item["strengthens"] + item["does_not_establish"]) <= properties:
            raise EvidenceError("contract relationship names an unknown property")
        if set(item["strengthens"]) & set(item["does_not_establish"]):
            raise EvidenceError("contract both strengthens and disclaims the same property")
    active: set[str] = set()
    complete: set[str] = set()

    def visit(name: str) -> None:
        if name in active:
            raise EvidenceError("contract dependency cycle")
        if name in complete:
            return
        active.add(name)
        for dependency in nodes[name]["depends_on"]:
            visit(dependency)
        active.remove(name)
        complete.add(name)

    for name in nodes:
        visit(name)


def main() -> int:
    try:
        index = decode_json((ROOT / "artifacts/interop/index.json").read_text())
        graph = decode_json((ROOT / index["contract_dependencies"]).read_text())
        validate(index, graph)
    except (EvidenceError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"contract graph invalid: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"relationships": "VALID", "status_inheritance": False, "confers_authority": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
