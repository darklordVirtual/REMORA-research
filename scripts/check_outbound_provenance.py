#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Check outbound Federation contribution records without implying ownership.

The validator is deliberately offline. GitHub PR contents/status and target
licence notices must be checked by a human when adding or updating an entry.
A declared external licence never changes REMORA Core's separate licence.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = Path("provenance/OUTBOUND_CONTRIBUTIONS.yaml")
SCHEMA = Path("provenance/schemas/outbound-contributions-v1.schema.json")


def validate(data: object, schema: dict, root: Path) -> list[str]:
    """Validate schema and offline assertions; return deterministic errors."""
    errors = [
        f"schema: {err.message} at {'/'.join(map(str, err.path))}"
        for err in jsonschema.Draft202012Validator(schema).iter_errors(data)
    ]
    if errors:
        return sorted(errors)
    assert isinstance(data, dict)
    records = data["records"]
    seen_ids: set[str] = set()
    seen_prs: set[str] = set()
    for record in records:
        rid = record["id"]
        if rid in seen_ids:
            errors.append(f"{rid}: duplicate record id")
        seen_ids.add(rid)
        pr = record["pull_request"]
        if pr in seen_prs:
            errors.append(f"{rid}: duplicate pull request")
        seen_prs.add(pr)
        if not pr.startswith(f"https://github.com/{record['target_repo']}/pull/"):
            errors.append(f"{rid}: pull request does not match target_repo")
        try:
            if dt.date.fromisoformat(record["observed_at"]).isoformat() != record["observed_at"]:
                errors.append(f"{rid}: observed_at is not a canonical ISO date")
        except ValueError:
            errors.append(f"{rid}: observed_at is not a valid date")
        merged = record["status"] == "merged"
        if merged != ("merge_commit" in record):
            errors.append(f"{rid}: merge_commit must be present exactly when status is merged")
        for path in record["target_paths"]:
            if path.startswith("/") or "\\" in path or ".." in Path(path).parts or path.endswith("/"):
                errors.append(f"{rid}: unsafe target path {path!r}")
        for concept in record["concepts"]:
            if not (root / "provenance/concepts" / f"{concept}.yaml").is_file():
                errors.append(f"{rid}: unknown local concept {concept}")
        for source in record["research_sources"]:
            if source["kind"] == "internal_document":
                ref = source["reference"]
                if ref.startswith("/") or ".." in Path(ref).parts or not (root / ref).is_file():
                    errors.append(f"{rid}: missing or unsafe internal reference {ref!r}")
            elif not source["reference"].startswith("https://"):
                errors.append(f"{rid}: external source must have an https URL")
    return sorted(errors)


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate the committed ledger")
    _unused_args = parser.parse_args(argv)
    try:
        schema = json.loads((root / SCHEMA).read_text(encoding="utf-8"))
        data = yaml.safe_load((root / REGISTER).read_text(encoding="utf-8"))
        errors = validate(data, schema, root)
    except (OSError, ValueError, yaml.YAMLError, jsonschema.SchemaError) as exc:
        print(f"[FAIL] outbound provenance: {exc}")
        return 1
    if errors:
        for err in errors:
            print(f"[FAIL] outbound provenance: {err}")
        return 1
    print(f"[PASS] outbound provenance: {len(data['records'])} recorded external PR scopes (offline validation only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
