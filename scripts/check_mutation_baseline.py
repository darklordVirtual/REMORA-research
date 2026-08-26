#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Fail on NEW mutation survivors against the committed baseline.

The scheduled mutation job (.github/workflows/mutation.yml, issue #280) runs
the scoped sweep from ``[tool.mutmut]`` and hands the ``mutmut results``
output to this script. The contract:

* a surviving mutant NOT in ``docs/assurance/mutation_baseline_v1.txt`` is a
  regression in test strength — the job FAILS and names it;
* a baseline entry that no longer survives is progress — reported as an
  advisory ratchet hint, never a failure, so improving tests cannot break
  the job;
* baseline entries whose whole function id-set vanished from the results are
  reported separately: mutant ids embed function names, so a rename moves
  every id at once. That is baseline maintenance, not a test regression, and
  the message says which command regenerates it.

The baseline is a plain sorted list of surviving mutant ids. Regenerate with::

    mutmut results | python scripts/check_mutation_baseline.py --update -

which is deliberately explicit: the ratchet only means something if lowering
it is a visible act in a reviewed diff.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs" / "assurance" / "mutation_baseline_v1.txt"

_LINE = re.compile(r"^\s*(\S+__mutmut_\d+): (.+?)\s*$")


def parse_results(text: str) -> dict[str, str]:
    """mutant id -> status, from ``mutmut results`` output."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _function_of(mutant_id: str) -> str:
    return mutant_id.rsplit("__mutmut_", 1)[0]


def main(argv: list[str]) -> int:
    update = "--update" in argv
    args = [a for a in argv[1:] if a != "--update"]
    if not args:
        print("usage: check_mutation_baseline.py [--update] <results-file|->",
              file=sys.stderr)
        return 2
    text = (sys.stdin.read() if args[0] == "-"
            else Path(args[0]).read_text(encoding="utf-8"))
    results = parse_results(text)
    if not results:
        print("[FAIL] no mutants parsed from the results input — an empty "
              "sweep must not pass as a clean one", file=sys.stderr)
        return 1
    survivors = {mid for mid, status in results.items() if status == "survived"}

    if update:
        BASELINE.write_text(
            "\n".join(sorted(survivors)) + "\n", encoding="utf-8", newline="\n")
        print(f"[OK] baseline updated: {len(survivors)} survivor(s) recorded")
        return 0

    if not BASELINE.exists():
        print(f"[FAIL] baseline missing: {BASELINE}", file=sys.stderr)
        return 1
    baseline = {ln.strip() for ln in
                BASELINE.read_text(encoding="utf-8").splitlines() if ln.strip()}

    new = sorted(survivors - baseline)
    fixed = sorted(baseline - survivors)
    result_functions = {_function_of(mid) for mid in results}
    renamed = sorted(mid for mid in fixed
                     if _function_of(mid) not in result_functions)
    killed = [mid for mid in fixed if mid not in renamed]

    if killed:
        print(f"[INFO] {len(killed)} baseline survivor(s) no longer survive — "
              f"ratchet down by regenerating the baseline in a reviewed diff "
              f"(mutmut results | python scripts/check_mutation_baseline.py "
              f"--update -)")
    if renamed:
        print(f"[INFO] {len(renamed)} baseline entr(y/ies) reference functions "
              f"absent from this sweep (rename or removal) — baseline "
              f"maintenance, not a regression")
    if new:
        print(f"[FAIL] {len(new)} NEW mutation survivor(s) — test strength "
              f"regressed for these mutants:", file=sys.stderr)
        for mid in new[:40]:
            print(f"  - {mid}", file=sys.stderr)
        if len(new) > 40:
            print(f"  … and {len(new) - 40} more", file=sys.stderr)
        return 1
    print(f"[PASS] mutation baseline holds: {len(survivors)} survivor(s), "
          f"none new (baseline {len(baseline)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
