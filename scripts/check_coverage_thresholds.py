#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Per-package coverage floors for the trusted computing base.

A single global threshold lets a well-covered research module pay for a
thinly-covered enforcement module. Until 2026-08-20 the gate was one global
number at 75% against an actual 83%, which meant roughly 2,100 covered
statements could be deleted without the gate noticing — and the two files
that actually *enforce* (``enforcement/gate.py`` and ``enforcement/outbox.py``)
were the least covered in the package.

This script reads the ``coverage json`` report and applies a floor per
package. Floors are set just under the measured value: tight enough that a
regression fails, loose enough that ordinary refactoring does not.

Usage::

    pytest -q --cov --cov-branch --cov-report=json:coverage.json
    python scripts/check_coverage_thresholds.py coverage.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

#: package prefix → minimum percent of (statements + branches) covered.
#: Raise a floor when the real number rises; never lower one to make a
#: failing build pass — cover the code instead.
THRESHOLDS: dict[str, float] = {
    "remora/policy": 92.0,
    "remora/execution": 90.0,
    "remora/governance": 88.0,
    # Still the lowest floor in the trusted computing base, and the reason is
    # now stated rather than left to be guessed at: see FILE_THRESHOLDS and
    # the "what this run does not measure" note below.
    "remora/enforcement": 83.0,
    "servers/api.py": 84.0,
    "servers/execution_api.py": 90.0,
}

#: What this run does not measure, stated so the package number is not
#: misread. ``remora/enforcement`` sits below its neighbours almost entirely
#: because two files carry a Postgres adapter that this job never executes:
#: ``PostgresExecutionOutbox`` (outbox.py) and the psycopg branch of the
#: one-time jti consumption (gate.py). Those paths are exercised against a
#: real Postgres service in the dedicated contract job
#: (.github/workflows — "Postgres tenant-chain contract (real service)"),
#: which runs without coverage instrumentation. So the package percentage is
#: "covered by the deterministic suite", not "the fraction of the enforcement
#: path that is tested at all", and the gap between them is not dead code.
#:
#: Per-file floors make that visible: a regression in the in-process code of
#: gate.py or outbox.py fails here even though the package average would
#: absorb it, and nobody has to infer which files the package number is being
#: dragged down by.
FILE_THRESHOLDS: dict[str, float] = {
    # Postgres adapter branches excluded from this run (see above).
    "remora/enforcement/gate.py": 75.0,
    "remora/enforcement/outbox.py": 73.0,
    # Fully exercised in-process; these are ordinary floors.
    "remora/enforcement/lease.py": 93.0,
    "remora/enforcement/token.py": 94.0,
    "remora/enforcement/result_envelope.py": 86.0,
    # ADR-B. Same shape as gate.py: the Postgres and D1 backend branches are
    # not reachable in this run, and the in-process logic around them is.
    "remora/enforcement/nonce_store.py": 75.0,
    # ADR-A. The uncovered remainder is the import-error path for the optional
    # 'cryptography' extra, which is exercised by monkeypatch rather than by
    # actually uninstalling the package mid-run.
    "remora/enforcement/lease_signing.py": 75.0,
}

#: Global floor over everything measured, including branches.
GLOBAL_THRESHOLD = 79.0


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def package_coverage(report: dict) -> dict[str, tuple[int, int]]:
    """covered, total per configured package prefix."""
    totals: dict[str, tuple[int, int]] = {}
    for prefix in THRESHOLDS:
        covered = total = 0
        for raw_path, entry in report["files"].items():
            path = _norm(raw_path)
            if not (path == prefix or path.startswith(prefix.rstrip("/") + "/")):
                continue
            summary = entry["summary"]
            covered += summary["covered_lines"] + summary.get("covered_branches", 0)
            total += summary["num_statements"] + summary.get("num_branches", 0)
        totals[prefix] = (covered, total)
    return totals


def file_coverage(report: dict) -> dict[str, tuple[int, int]]:
    """covered, total per configured file path."""
    totals: dict[str, tuple[int, int]] = {}
    for raw_path, entry in report["files"].items():
        path = _norm(raw_path)
        if path not in FILE_THRESHOLDS:
            continue
        summary = entry["summary"]
        totals[path] = (
            summary["covered_lines"] + summary.get("covered_branches", 0),
            summary["num_statements"] + summary.get("num_branches", 0),
        )
    return totals


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "coverage.json")
    if not path.exists():
        print(f"ERROR: {path} not found — run pytest with "
              f"--cov-report=json:{path} first", file=sys.stderr)
        return 2

    report = json.loads(path.read_text(encoding="utf-8"))
    failures: list[str] = []

    overall = report["totals"]["percent_covered"]
    status = "OK " if overall >= GLOBAL_THRESHOLD else "FAIL"
    print(f"[{status}] {'TOTAL':<28} {overall:6.2f}% (floor {GLOBAL_THRESHOLD}%)")
    if overall < GLOBAL_THRESHOLD:
        failures.append(f"TOTAL {overall:.2f}% < {GLOBAL_THRESHOLD}%")

    for prefix, (covered, total) in sorted(package_coverage(report).items()):
        floor = THRESHOLDS[prefix]
        if total == 0:
            failures.append(f"{prefix}: nothing measured — is it in the source list?")
            print(f"[FAIL] {prefix:<28} not measured")
            continue
        pct = 100.0 * covered / total
        status = "OK " if pct >= floor else "FAIL"
        print(f"[{status}] {prefix:<28} {pct:6.2f}% (floor {floor}%)")
        if pct < floor:
            failures.append(f"{prefix} {pct:.2f}% < {floor}%")

    measured_files = file_coverage(report)
    for path in sorted(FILE_THRESHOLDS):
        floor = FILE_THRESHOLDS[path]
        if path not in measured_files or measured_files[path][1] == 0:
            failures.append(f"{path}: nothing measured — is it in the source list?")
            print(f"[FAIL] {path:<28} not measured")
            continue
        covered, total = measured_files[path]
        pct = 100.0 * covered / total
        status = "OK " if pct >= floor else "FAIL"
        print(f"[{status}] {path:<28} {pct:6.2f}% (floor {floor}%)")
        if pct < floor:
            failures.append(f"{path} {pct:.2f}% < {floor}%")

    print("\nNote: the Postgres adapters in gate.py and outbox.py are not "
          "executed by this run; they are contract-tested against a real "
          "Postgres service in a separate job.")

    if failures:
        print("\n[FAIL] coverage floors not met:", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        print("\nCover the code; do not lower the floor.", file=sys.stderr)
        return 1

    print("\n[PASS] every package meets its coverage floor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
