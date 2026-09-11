#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
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

Scope (changed 2026-09-03). Until then the scan was a fixed twelve-path list
and a missing path was skipped in silence, so a document added after the list
was written was never scanned at all: the gate could not see a new overclaim.
The reader-facing Markdown surface is now globbed instead. Archived and
superseded documents are excluded because the repository preserves their text
verbatim by policy (see NEGATIVE_RESULTS.md and documentation_governance_v1):
rewording them to satisfy this gate would destroy the record the policy exists
to keep, so they are excluded here rather than silently edited later.

Text is NFKC-normalised and unicode hyphens (U+2010 through U+2015) are mapped
to a plain hyphen before matching, because "production‑ready" reads to a
human exactly as "production-ready" reads and must not evade an ASCII pattern.

Run as part of `make audit`.  Exits 0 on success, 1 if any forbidden pattern
is found outside an allowed context.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The verdict must survive a cp1252 console: a UnicodeEncodeError raised while
# printing findings used to hide the result of a check that had already run.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover - exotic streams
        pass


# ---------------------------------------------------------------------------
# Files to scan
# ---------------------------------------------------------------------------

#: Named single files outside the globbed Markdown surface. A missing one is
#: still skipped (the frontend is optional in some checkouts), but nothing in
#: this list is load-bearing for coverage any more: the globs below are.
EXTRA_FILES = (
    "CHANGELOG.md",
    "enterprise/executive-brief.md",
    "enterprise/sector-use-cases.md",
    "enterprise/production-readiness.md",
    "frontend/src/routes/index.tsx",
    "frontend/src/content/whitepaper.ts",
    "frontend/src/features/control-room/components/DecisionPanel.tsx",
    "frontend/src/features/control-room/components/ApprovalModal.tsx",
)

#: Reader-facing Markdown. Globbed so a document added tomorrow is scanned.
SCAN_GLOBS = (
    "README.md",
    "ARCHITECTURE.md",
    "NEGATIVE_RESULTS.md",
    "docs/**/*.md",
    "paper/*.md",
)

#: Text preserved verbatim by policy. See the module docstring: rewording a
#: superseded document to satisfy this gate would destroy the record.
EXCLUDE_PREFIXES = (
    "docs/archive/",
    "docs/researchpapers/",
    "attic/",
)


def scan_paths(root: Path) -> list[Path]:
    seen: dict[str, Path] = {}
    for pattern in SCAN_GLOBS:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel.startswith(EXCLUDE_PREFIXES):
                continue
            seen.setdefault(rel, path)
    for rel in EXTRA_FILES:
        path = root / rel
        if path.is_file():
            seen.setdefault(rel, path)
    return [seen[rel] for rel in sorted(seen)]

# ---------------------------------------------------------------------------
# Forbidden patterns and their human-readable labels
# ---------------------------------------------------------------------------
# Each entry: (regex, label, negation_lookbehind_words)
# If any word in negation_lookbehind is found between the start of the match's
# own sentence and the match, the match is considered negated and is skipped.
# The window used to be a flat 60 characters, which meant a "not" in the
# PREVIOUS sentence exonerated the claim in this one.
#
# Several patterns allow up to two interposed words: "guarantees complete
# safety" and "immutable, append-only audit" are the same claims as
# "guarantees safety" and "immutable audit", and were passing.

#: Up to two interposed words (or a comma) between two halves of a claim.
_GAP = r"[\s,]+(?:[\w-]+[\s,]+){0,2}"

FORBIDDEN: list[tuple[str, str, list[str]]] = [
    (
        r"\bproduction[- ](?:safe|ready|grade|proven)\b",
        "unqualified 'production safe/ready/grade/proven'",
        [
            "not ", "does not", "never ", "without", "pending",
            "target:", "what is needed", "requires external replication",
            "avoid wording", "forbidden",
        ],
    ),
    (
        r"\bguarantees?" + _GAP + r"safety\b",
        "unqualified 'guarantees safety'",
        ["not ", "does not", "never ", "no system"],
    ),
    (
        r"\bexternally\s+validated\b",
        "'externally validated' (not yet achieved)",
        [
            "not ", "has not", "never ", "require", "pending",
            "should be", "what is needed", "how to cite",
        ],
    ),
    (
        r"\bpeer[- ]reviewed\s+theorem\b",
        "'peer-reviewed theorem'",
        ["not ", "unpublished", "pending"],
    ),
    (
        r"\b(?:certifies?|certif(?:ied|ication))\s+(?:safety|correctness|alignment)\b",
        "unqualified 'certifies safety/correctness/alignment'",
        [
            "not ", "does not", "never ", "cannot",
            "avoid wording", "forbidden", "what is needed",
        ],
    ),
    (
        r"\b100\s*%\s+(?:safe|accurate|correct|reliable)\b",
        "absolute 100% claim",
        [],
    ),
    (
        r"\bzero\s+(?:false[\s-]positives?|false[\s-]negatives?"
        r"|hallucinations?|errors?)\b",
        "absolute zero false positives/negatives/hallucinations claim",
        ["not ", "nearly", "approaching", "target of", "goal of"],
    ),
    (
        r"\bimmutable" + _GAP + r"audit\b",
        "immutable audit wording",
        ["not ", "isn't", "is not", "without"],
    ),
]


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f"[OK]   {msg}")


#: U+2010 HYPHEN through U+2015 HORIZONTAL BAR (U+2011 is the non-breaking
#: hyphen that a word processor inserts and that read as plain text to a human
#: while evading every ASCII pattern here).
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―"})

_BLANK_LINE = re.compile(r"\n[ \t]*\n")
_LIST_OR_TABLE = re.compile(r"^\s*(?:[-*+]|\d+\.|\|)")


def _block_start(text: str, pos: int) -> int:
    """Index just after the last blank line before ``pos`` (0 if none)."""
    last = None
    for m in _BLANK_LINE.finditer(text, 0, pos):
        last = m
    return last.end() if last else 0


def normalize(text: str) -> str:
    """NFKC plus unicode-hyphen folding, so a look-alike cannot evade.

    Both steps preserve newlines and are character-for-character for the
    substitutions that matter here, so reported line numbers still refer to
    the file on disk.
    """
    return unicodedata.normalize("NFKC", text).translate(_DASHES)


def negation_window(text: str, start: int) -> str:
    """Text that can negate the match: its own sentence, bounded.

    The window used to be a flat 60 characters, so a "not" in the previous
    sentence exonerated the claim in this one. It is now bounded by the
    sentence terminator, and never reaches past the enclosing block.

    A list item or table row is the exception, and deliberately so: this
    repository's honest documents are full of "This document does NOT
    claim:" followed by a bulleted list, and the bullet's subject is its
    lead-in. Such an item therefore also sees the block that introduces it.
    """
    block = _block_start(text, start)
    body = text[block:start]
    if _LIST_OR_TABLE.match(body.lstrip("\n")):
        lead = _block_start(text, max(block - 1, 0))
        return _flatten(text[lead:start])
    bound = max(text.rfind(ch, block, start) for ch in ".!?")
    return _flatten(text[max(bound + 1, block) : start])


def _flatten(window: str) -> str:
    """Lowercase, drop Markdown emphasis, collapse whitespace.

    ``is **not** enough`` and a line-wrapped ``not\\n  externally`` are the
    same negation as ``is not enough``; matching on the raw text made the
    negation invisible whenever an author bolded or wrapped it.
    """
    return re.sub(r"\s+", " ", re.sub(r"[*_`]+", "", window)).lower()


def is_quotation(text: str, match: re.Match[str]) -> bool:
    """True if the match sits inside a code span or a quoted phrase.

    A gate that reads prose has to distinguish a claim from the naming of
    one. ``docs/10-contributing.md`` lists ``production-grade`` as banned
    vocabulary and ``docs/claim_register.md`` lists "peer-reviewed theorem"
    among the wordings to avoid; flagging those would be the gate misreading
    its own rulebook. The exemption is narrow: the match must be wholly
    inside one pair of backticks or one pair of double quotes on its own
    line, which is not how a claim is written.
    """
    line_start = text.rfind("\n", 0, match.start()) + 1
    line_end = text.find("\n", match.end())
    line = text[line_start : line_end if line_end != -1 else len(text)]
    if line.lstrip().startswith(">"):
        return True  # a blockquote is quoted material or a citation template
    # Backticks bind to the line: a code span never wraps.
    if line.count("`", 0, match.start() - line_start) % 2 == 1:
        return True
    # Quotation marks may wrap, so they are matched within the block.
    block_start = _block_start(text, match.start())
    block_end = text.find("\n\n", match.end())
    block = text[block_start : block_end if block_end != -1 else len(text)]
    rel_start = match.start() - block_start
    rel_end = match.end() - block_start
    for opener, closer in (('"', '"'), ("“", "”"), ("«", "»")):
        if block.rfind(opener, 0, rel_start) == -1:
            continue
        if block.find(closer, rel_end) != -1:
            return True
    return False


def scan_file(path: Path, root: Path | None = None) -> list[str]:
    """Return list of overclaim violations found in file."""
    root = root or ROOT
    text = normalize(path.read_text(encoding="utf-8", errors="replace"))
    violations: list[str] = []
    for pattern, label, negations in FORBIDDEN:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            window = negation_window(text, m.start())
            if any(neg in window for neg in negations):
                continue  # negated context - allowed
            if is_quotation(text, m):
                continue  # a mention of the wording, not a use of it
            line_no = text[: m.start()].count("\n") + 1
            try:
                display = path.relative_to(root).as_posix()
            except ValueError:
                display = path.as_posix()
            violations.append(
                f"  {display}:{line_no}: {label}\n"
                f"    found: '{m.group(0)}'"
            )
    return violations


def main(argv: list[str] | None = None) -> None:
    global ROOT
    parser = argparse.ArgumentParser(description="overclaim language gate")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="scan this tree instead of the repository root",
    )
    args = parser.parse_args(argv)
    if args.root is not None:
        ROOT = args.root.resolve()

    all_violations: list[str] = []

    for path in scan_paths(ROOT):
        v = scan_file(path, ROOT)
        if v:
            all_violations.extend(v)
        else:
            ok(f"No overclaims: {path.relative_to(ROOT).as_posix()}")

    if all_violations:
        print(f"\n[FAIL] {len(all_violations)} overclaim(s) detected:\n")
        for line in all_violations:
            print(line)
        print(
            "\nFix: qualify the claim with the appropriate evidence level.\n"
            "See docs/claim_register.md for citation discipline guidance."
        )
        raise SystemExit(1)

    print("\n[PASS] No forbidden overclaim patterns found.")


if __name__ == "__main__":
    main()
