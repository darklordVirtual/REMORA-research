# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Fail-closed gate for external decision-to-effect self-runs.

Checks a public SELF-TEST badge. Never claims independent verification or safety.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def digest(path: Path) -> str:
    """Match the runner's LF-normalized SHA-256."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def validate(
    record: dict[str, Any], suite: dict[str, Any], *,
    suite_path: Path, runner_path: Path, adapter_path: Path, suite_sha: str,
) -> list[str]:
    errors: list[str] = []
    pins = {
        "suite_sha256": digest(suite_path),
        "runner_sha256": digest(runner_path),
        "adapter_sha256": digest(adapter_path),
        "repo_commit": suite_sha,
        "suite": suite["suite"],
        "run_kind": "author-run",  # The runner grants no independence claim.
    }
    for field, expected in pins.items():
        if record.get(field) != expected:
            errors.append(f"{field}: mismatch")
    if record.get("adapter") in (None, "", "skeleton"):
        errors.append("adapter is not a named external implementation")
    vectors = suite["vectors"]
    rows = record.get("results")
    if not isinstance(rows, list):
        return errors + ["results: missing or not a list"]
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            errors.append("result entry malformed")
            continue
        if item["id"] in seen:
            errors.append(f"duplicate case: {item['id']}")
        seen.add(item["id"])
    if [r.get("id") if isinstance(r, dict) else None for r in rows] != [
        v["id"] for v in vectors
    ]:
        errors.append("case IDs/order differ from pinned suite")
    for index, vector in enumerate(vectors):
        if index >= len(rows) or not isinstance(rows[index], dict):
            continue
        row = rows[index]
        if row.get("expected") != vector["expect"]:
            errors.append(f"{vector['id']}: expected value changed")
        if row.get("observed") != vector["expect"] or row.get("status") != "MATCH":
            errors.append(f"{vector['id']}: not a MATCH ({row.get('status')})")
    total = len(vectors)
    required = {"match": total, "divergent": 0, "unsupported": 0, "error": 0, "total": total}
    if record.get("counts") != required:
        errors.append(f"counts: expected all {total} vectors to match without gaps")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--suite-sha", required=True)
    args = parser.parse_args()
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
        suite = json.loads(args.suite.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or not isinstance(suite, dict):
            raise ValueError("record and suite must be JSON objects")
        errors = validate(
            record, suite, suite_path=args.suite, runner_path=args.runner,
            adapter_path=args.adapter, suite_sha=args.suite_sha,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"SELF-TEST GATE FAILED: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"SELF-TEST GATE FAILED: {error}", file=sys.stderr)
        return 1
    print(f"SELF-TEST MATCH: {len(suite['vectors'])} pinned vectors")
    print("Self-reported adapter outputs; NOT independent verification or certification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
