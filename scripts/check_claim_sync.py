#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Reviewer-safe claim synchronization checks across key narrative docs.

This validator enforces two guardrails:
1. High-risk phrases (e.g. "0% unsafe") must be benchmark-qualified.
2. Core docs must describe REMORA as a governance overlay, not agent replacement.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_FILES = [
    ROOT / "README.md",
    ROOT / "paper" / "whitepaper.md",
    ROOT / "paper" / "claim_ledger.md",
    ROOT / "docs" / "claim_register.md",
]

RISKY_PATTERNS = [
    re.compile(r"0\s*%\s*unsafe", re.IGNORECASE),
    re.compile(r"zero\s*unsafe", re.IGNORECASE),
]
QUALIFIERS = ("benchmark", "dry-run", "simulation", "synthetic", "replay")


def _check_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        display = str(path.relative_to(ROOT))
    except ValueError:
        display = str(path)

    if not path.exists():
        errors.append(f"missing file: {display}")
        return errors

    text = path.read_text(encoding="utf-8")
    lower = text.lower()

    if "governance overlay" not in lower:
        errors.append(f"{display}: missing phrase 'governance overlay'")

    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        if any(p.search(line) for p in RISKY_PATTERNS):
            window = " ".join(lines[max(0, idx - 2): min(len(lines), idx + 1)]).lower()
            if not any(q in window for q in QUALIFIERS):
                errors.append(
                    f"{display}:{idx}: risky claim missing benchmark qualifier"
                )
    return errors


def run() -> int:
    all_errors: list[str] = []
    for path in TARGET_FILES:
        all_errors.extend(_check_file(path))

    if all_errors:
        print("Claim sync check failed:")
        for err in all_errors:
            print(f" - {err}")
        return 1

    print("Claim sync check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
