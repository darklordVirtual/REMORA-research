#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Reviewer-safe claim synchronization checks across key narrative docs.

This validator enforces two guardrails:
1. High-risk phrases (e.g. "0% unsafe") must be benchmark-qualified.
2. Core docs must describe REMORA as a governance overlay, not agent replacement.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILES = (
    "README.md",
    "paper/remora_paper.md",
    "paper/claim_ledger.md",
    "docs/claim_register.md",
)

#: A claim that nothing unsafe happened, in the shapes people actually write
#: it. Before 2026-09-03 this was two regexes for "0% unsafe" and "zero
#: unsafe", so "no unsafe action was ever executed", "0/500 unsafe
#: executions" and "zero of 500 calls were unsafe" all passed the gate
#: unqualified. The quantifier and the word "unsafe" must sit in the same
#: sentence, which is what makes the pattern a claim rather than a
#: coincidence of nearby words.
RISKY_PATTERNS = [
    re.compile(
        r"\b(?:no|zero|none|0(?:\s*%|/\d+)?)\b[^.!?]{0,40}\bunsafe\b",
        re.IGNORECASE,
    ),
]
#: "simulat" covers simulation/simulated/simulator: a result labelled
#: "Simulated" in the same table row is scoped exactly as intended.
QUALIFIERS = ("benchmark", "dry-run", "simulat", "synthetic", "replay")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _check_file(path: Path, root: Path | None = None) -> list[str]:
    errors: list[str] = []
    try:
        display = (path.relative_to(root or ROOT)).as_posix()
    except ValueError:
        display = str(path)

    if not path.exists():
        errors.append(f"missing file: {display}")
        return errors

    text = path.read_text(encoding="utf-8")
    lower = text.lower()

    if "governance overlay" not in lower:
        errors.append(f"{display}: missing phrase 'governance overlay'")

    # The qualifier must be in the SAME sentence as the claim. A
    # three-line window let an unrelated mention of "benchmark" two lines
    # above excuse an unqualified claim.
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        for sentence in _SENTENCE_SPLIT.split(raw_line):
            if not any(p.search(sentence) for p in RISKY_PATTERNS):
                continue
            if not any(q in sentence.lower() for q in QUALIFIERS):
                line_no = text.count("\n", 0, offset) + 1
                errors.append(
                    f"{display}:{line_no}: risky claim missing benchmark qualifier"
                )
                break
        offset += len(raw_line)
    return errors


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="claim synchronization gate")
    parser.add_argument(
        "--root", type=Path, default=ROOT,
        help="check this tree instead of the repository root",
    )
    parser.add_argument(
        "--files", nargs="+", default=list(DEFAULT_FILES),
        help="paths to check, relative to --root",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    all_errors: list[str] = []
    for rel in args.files:
        all_errors.extend(_check_file(root / rel, root))

    if all_errors:
        print("Claim sync check failed:")
        for err in all_errors:
            print(f" - {err}")
        return 1

    print("Claim sync check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
