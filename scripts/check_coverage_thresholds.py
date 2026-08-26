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
#:
#: Issue #280 targets remora/policy, remora/enforcement and remora/execution
#: at >=95 and remora/governance at >=90. Floors are raised only to levels
#: the suite measurably holds (2026-08-26 run, after the edge-contract round
#: of #280: policy 95.45, execution 96.25 locally, governance 89.80,
#: enforcement 86.72): policy reaches its target and execution now exceeds it
#: locally; the remaining gap to 95 for enforcement is the Postgres adapter
#: code this job deliberately does not execute (see the note below), which a
#: floor here cannot honestly declare covered.
THRESHOLDS: dict[str, float] = {
    "remora/policy": 95.0,
    "remora/execution": 93.0,  # CI-held 93.29 after the dispatch worker
    # (#82) grew service.py; locally higher, but CI skips the
    # optional-extra suites and the floor is pinned at the level EVERY
    # environment holds. Covering the worker's remaining branches raises
    # this again; lowering it further needs a stated reason like this one.
    "remora/governance": 89.5,
    # Still the lowest floor in the trusted computing base, and the reason is
    # now stated rather than left to be guessed at: see FILE_THRESHOLDS and
    # the "what this run does not measure" note below.
    "remora/enforcement": 85.5,  # 85.88 measured 2026-08-26 after the
    # terminal projector (#416): the new Postgres projector variants join
    # the adapter mass the real-service job covers, growing the
    # deliberately-unmeasured share of outbox.py
    "servers/api.py": 84.5,
    "servers/execution_api.py": 93.0,
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
    "remora/enforcement/gate.py": 77.5,  # 77.92 measured; thin, adapters dominate
    "remora/enforcement/outbox.py": 73.0,  # 73.49 after #416: the projector's
    # Postgres variants (mark_projected/unprojected_terminal) are covered by
    # the real-service contract job, not this run; adapters dominate
    # Fully exercised in-process; these are ordinary floors.
    "remora/enforcement/lease.py": 97.5,  # 97.85 after the event-contract round
    "remora/enforcement/token.py": 97.5,  # 98.05
    "remora/enforcement/result_envelope.py": 99.0,  # 100.00: env parsing now
    # pinned. 99.0 and not higher: the gate's own meta-test holds the
    # invariant that no floor exceeds 99, so a synthetic all-at-99 report
    # passes (tests/test_coverage_thresholds_gate.py).
    # ADR-B. Same shape as gate.py: the Postgres and D1 backend branches are
    # not reachable in this run, and the in-process logic around them is.
    "remora/enforcement/nonce_store.py": 80.5,  # 80.67
    # ADR-A. The uncovered remainder is the import-error path for the optional
    # 'cryptography' extra, which is exercised by monkeypatch rather than by
    # actually uninstalling the package mid-run.
    "remora/enforcement/lease_signing.py": 98.0,
}

#: Global floor over everything measured, including branches.
GLOBAL_THRESHOLD = 80.5


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
