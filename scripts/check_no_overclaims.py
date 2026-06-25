#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Scan documentation and code docstrings for forbidden overclaim language.

"World-class evidence" means knowing exactly what you have NOT proven.
This script enforces that REMORA's public-facing text (README, paper,
enterprise docs, CHANGELOG) does not contain language that overstates:
- external validation that has not happened
- production guarantees that have not been tested
- peer-review status that has not been achieved
- absolute safety claims

False positives that appear in clearly negated or conditional contexts can be
allowlisted below.  The goal is to catch unintentional overclaims, not to
prevent nuanced discussion.

Run as part of `make audit`.  Exits 0 on success, 1 if any forbidden pattern
is found outside an allowed context.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Files to scan
# ---------------------------------------------------------------------------

SCAN_FILES = [
    ROOT / "README.md",
    ROOT / "paper" / "whitepaper.md",
    ROOT / "CHANGELOG.md",
    ROOT / "enterprise" / "executive-brief.md",
    ROOT / "enterprise" / "sector-use-cases.md",
    ROOT / "enterprise" / "production-readiness.md",
    ROOT / "docs" / "plain_language_overview.md",
    ROOT / "docs" / "breakthrough_proof.md",
]

# ---------------------------------------------------------------------------
# Forbidden patterns and their human-readable labels
# ---------------------------------------------------------------------------
# Each entry: (regex, label, negation_lookbehind_words)
# If any word in negation_lookbehind is found in the 60 chars before the match,
# the match is considered negated and is skipped.

FORBIDDEN: list[tuple[str, str, list[str]]] = [
    (
        r"\bproduction[- ](?:safe|ready|grade|proven)\b",
        "unqualified 'production safe/ready/grade/proven'",
        ["not ", "does not", "never ", "without independent", "pending"],
    ),
    (
        r"\bguarantees?\s+safety\b",
        "unqualified 'guarantees safety'",
        ["not ", "does not", "never ", "no system"],
    ),
    (
        r"\bexternally\s+validated\b",
        "'externally validated' (not yet achieved)",
        ["not ", "has not", "never ", "requires", "pending"],
    ),
    (
        r"\bpeer[- ]reviewed\s+theorem\b",
        "'peer-reviewed theorem'",
        ["not ", "unpublished", "pending"],
    ),
    (
        r"\b(?:certifies?|certif(?:ied|ication))\s+(?:safety|correctness|alignment)\b",
        "unqualified 'certifies safety/correctness/alignment'",
        ["not ", "does not", "never ", "cannot"],
    ),
    (
        r"\b100\s*%\s+(?:safe|accurate|correct|reliable)\b",
        "absolute 100% claim",
        [],
    ),
    (
        r"\bzero\s+(?:false\s+positives?|false\s+negatives?|hallucinations?|errors?)\b",
        "absolute zero false positives/negatives/hallucinations claim",
        ["not ", "nearly", "approaching", "target of", "goal of"],
    ),
]


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f"[OK]   {msg}")


def scan_file(path: Path) -> list[str]:
    """Return list of overclaim violations found in file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    violations: list[str] = []
    for pattern, label, negations in FORBIDDEN:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            window = text[max(0, m.start() - 60) : m.start()].lower()
            if any(neg in window for neg in negations):
                continue  # negated context - allowed
            line_no = text[: m.start()].count("\n") + 1
            violations.append(
                f"  {path.relative_to(ROOT)}:{line_no}: {label}\n"
                f"    → found: '{m.group(0)}'"
            )
    return violations


def main() -> None:
    all_violations: list[str] = []

    for path in SCAN_FILES:
        if not path.exists():
            # Non-fatal - file may not exist in all configurations
            continue
        v = scan_file(path)
        if v:
            all_violations.extend(v)
        else:
            ok(f"No overclaims: {path.relative_to(ROOT)}")

    if all_violations:
        print(f"\n[FAIL] {len(all_violations)} overclaim(s) detected:\n")
        for v in all_violations:
            print(v)
        print(
            "\nFix: qualify the claim with the appropriate evidence level.\n"
            "See docs/claim_register.md for citation discipline guidance."
        )
        raise SystemExit(1)

    print("\n[PASS] No forbidden overclaim patterns found.")


if __name__ == "__main__":
    main()
