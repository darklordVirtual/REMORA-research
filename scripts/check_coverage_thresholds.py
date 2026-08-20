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
    # Lower than its neighbours on purpose, and tracked: gate.py and
    # outbox.py are the least-covered files in the trusted computing base.
    # This floor is a ratchet to raise, not a standard to settle at.
    "remora/enforcement": 80.0,
    "servers/api.py": 84.0,
    "servers/execution_api.py": 90.0,
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
