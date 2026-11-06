#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Fail when a mutation sweep did not measure, and say why by name.

The scheduled sweep of 2026-11-02 failed in its stats phase: one selected test
module read a fixture directory the sandbox had not copied, pytest stopped at
collection, no mutant ran, and the red job sat unread for two days
(docs/assurance/mutation_testing_v1.md). ``mutmut run`` exits non-zero in that
case, which is necessary and not sufficient: nothing said what was missing,
and nothing distinguished "measured nothing" from "found new survivors".

This reads the sweep's own log (``mutmut run 2>&1 | tee mutation-run.log``)
and the sandbox it left behind, and fails with the collecting module named
when the stats or clean phase did not finish, when no mutant was executed, or
when the stats file is absent. A sweep that ran to the end passes whatever its
survivors say; the baseline gate judges those.

    python scripts/check_mutation_sweep_measured.py mutation-run.log [--sandbox mutants]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

COLLECT = re.compile(r"ERROR (?:collecting|at setup of) (\S+)")
PROGRESS = re.compile(r"(\d+)/(\d+)\s+\U0001F389\s+(\d+)")


def problems(log: str, sandbox: Path) -> list[str]:
    """Why the sweep measured nothing; empty when it ran to the end."""
    text = log.replace("\r", "\n")
    out: list[str] = []
    for module in dict.fromkeys(COLLECT.findall(text)):
        out.append(f"the sandbox could not collect {module}: add what it reads to "
                   "[tool.mutmut] also_copy, or deselect the test by node id")
    if "failed to collect stats" in text:
        out.append("the stats phase failed, so no mutant ran")
    if "Failed to run clean test" in text:
        out.append("the clean-test phase failed, so no mutant ran")
    if not (sandbox / "mutmut-stats.json").is_file():
        out.append(f"{sandbox / 'mutmut-stats.json'} is missing: the stats phase did not finish")
    executed = [int(m.group(1)) for m in PROGRESS.finditer(text)]
    if not executed or executed[-1] == 0:
        out.append("no mutant was executed")
    return list(dict.fromkeys(out))


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    sandbox = Path("mutants")
    if "--sandbox" in argv:
        sandbox = Path(argv[argv.index("--sandbox") + 1])
    path = Path(argv[0])
    log = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    if not log:
        print(f"[FAIL] no sweep log at {path}: the sweep did not run", file=sys.stderr)
        return 1
    found = problems(log, sandbox)
    if found:
        print("[FAIL] the mutation sweep did not measure:", file=sys.stderr)
        for item in found:
            print(f"  - {item}", file=sys.stderr)
        return 1
    executed = [int(m.group(1)) for m in PROGRESS.finditer(log.replace("\r", "\n"))]
    print(f"[OK] the sweep executed {executed[-1]} mutants and finished its phases")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
