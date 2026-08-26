#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Structural prose-style scanner with a shrink-only baseline.

Counts, per tracked Markdown file, the structural tells that a 2026-08-26
survey found to be this repository's actual prose problem (vocabulary tells
such as "delve" or "leverage" measured at zero; em dashes at ~5 per 1000
words):

``emdash``        an em dash on a prose line (code fences, tables and
                  headings are skipped; a table cell is layout, not prose)
``arrow``         a unicode arrow inside a prose sentence. Pipeline notation
                  (``A -> B -> C`` lines, tables, code) is kept; arrows are
                  counted only when they sit between words in a sentence.
``bold_bullet``   a list item that opens with a bolded label and a colon
``not_but``       "not X, but Y" / "not just X, it's Y" contrasts
``filler``        "it is worth noting", "it should be noted", "in order to",
                  "importantly", "notably" as sentence openers
``ing_tail``      a sentence ending in a superficial participle tail:
                  ", ensuring/highlighting/showcasing/underscoring ..."
``copula_dodge``  "serves as" / "stands as"

The baseline (``docs/assurance/prose_style_baseline.json``) records the
count per tell per file. A file may only get better: any count above its
baseline fails, counts below it are reported so the baseline can be
lowered with ``--update-baseline``. Files absent from the baseline start at
zero. Historical and archived documents are excluded because their text is
preserved verbatim by policy.

Usage::

    python scripts/check_prose_style.py            # gate against baseline
    python scripts/check_prose_style.py --report   # totals only, no gate
    python scripts/check_prose_style.py --update-baseline
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs" / "assurance" / "prose_style_baseline.json"

#: Text preserved verbatim by policy (history, third-party, superseded).
EXCLUDE_PREFIXES = (
    "attic/",
    "docs/archive/",
    "docs/researchpapers/",
    "frontend/node_modules/",
    "node_modules/",
    ".github/",
    ".claude/",  # skills quote the patterns they ban
    "artifacts/governance-benchmark-pack/",  # frozen copy of NEGATIVE_RESULTS
)

TELLS = (
    "emdash",
    "arrow",
    "bold_bullet",
    "not_but",
    "filler",
    "ing_tail",
    "copula_dodge",
)

_RE = {
    "emdash": re.compile("—"),
    # arrow between two word characters with spaces: prose, not notation
    "arrow": re.compile(r"[A-Za-z]\w*\s+[→⇒]\s+\w*[A-Za-z]"),
    "bold_bullet": re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\*\*[^*]*?(?::\*\*|\*\*\s*:)"),
    "not_but": re.compile(
        r"\bnot (?:just|only|merely|simply) [^.;:]{1,80}?[,;]\s*(?:but|it'?s|it is)\b",
        re.IGNORECASE,
    ),
    "filler": re.compile(
        r"(?:\bit (?:is|'s) worth noting\b|\bit should be noted\b|\bin order to\b"
        r"|(?:^|[.!?]\s+)(?:Importantly|Notably|Crucially),)",
        re.IGNORECASE,
    ),
    "ing_tail": re.compile(
        r",\s+(?:ensuring|highlighting|showcasing|underscoring|fostering|reflecting)\b[^.]*\.",
        re.IGNORECASE,
    ),
    "copula_dodge": re.compile(r"\b(?:serves|stands) as\b", re.IGNORECASE),
}

_FENCE = re.compile(r"^\s*(```|~~~)")
_TABLE = re.compile(r"^\s*\|")
_HEADING = re.compile(r"^\s*#{1,6}\s")
_PIPELINE = re.compile(r"^\s*(?:[`*_]*[\w./()-]+[`*_]*\s*[→⇒]\s*){2,}")


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md", "**/*.md"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split("\n")
    files = []
    for rel in sorted(set(p.strip() for p in out if p.strip())):
        if rel.startswith(EXCLUDE_PREFIXES):
            continue
        files.append(ROOT / rel)
    return files


def prose_lines(text: str):
    """Yield (lineno, line) for lines that are prose, not code/table/heading."""
    in_fence = False
    for i, line in enumerate(text.split("\n"), 1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or _TABLE.match(line) or _HEADING.match(line):
            continue
        yield i, line


def scan_text(text: str) -> Counter:
    counts: Counter = Counter()
    for _, line in prose_lines(text):
        for tell, rx in _RE.items():
            if tell == "arrow" and _PIPELINE.match(line):
                continue
            n = len(rx.findall(line))
            if n:
                counts[tell] += n
    return counts


def scan_repo() -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for path in tracked_markdown():
        counts = scan_text(path.read_text(encoding="utf-8", errors="replace"))
        if counts:
            result[path.relative_to(ROOT).as_posix()] = {
                t: counts[t] for t in TELLS if counts[t]
            }
    return result


def load_baseline() -> dict[str, dict[str, int]]:
    if not BASELINE.exists():
        return {}
    return json.loads(BASELINE.read_text(encoding="utf-8")).get("files", {})


def compare(current: dict[str, dict[str, int]],
            baseline: dict[str, dict[str, int]]) -> tuple[list[str], list[str]]:
    """Return (regressions, improvements) as printable lines."""
    regressions, improvements = [], []
    for f in sorted(set(current) | set(baseline)):
        cur, base = current.get(f, {}), baseline.get(f, {})
        for t in TELLS:
            c, b = cur.get(t, 0), base.get(t, 0)
            if c > b:
                regressions.append(f"{f}: {t} {b} -> {c}")
            elif c < b:
                improvements.append(f"{f}: {t} {b} -> {c}")
    return regressions, improvements


def totals(data: dict[str, dict[str, int]]) -> Counter:
    tot: Counter = Counter()
    for counts in data.values():
        tot.update(counts)
    return tot


def main(argv: list[str]) -> int:
    current = scan_repo()
    tot = totals(current)
    print("prose-style tells (tracked Markdown, prose lines only):")
    for t in TELLS:
        print(f"  {t:<13} {tot[t]:5d}")

    if "--report" in argv:
        worst = sorted(current.items(), key=lambda kv: -sum(kv[1].values()))[:15]
        print("\nworst files:")
        for f, c in worst:
            print(f"  {sum(c.values()):4d}  {f}")
        return 0

    if "--update-baseline" in argv:
        BASELINE.write_text(
            json.dumps({"_note": "shrink-only; regenerate with "
                        "scripts/check_prose_style.py --update-baseline "
                        "only after a prose pass that lowered counts",
                        "files": current}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\nbaseline written: {BASELINE.relative_to(ROOT).as_posix()}")
        return 0

    regressions, improvements = compare(current, load_baseline())
    for line in improvements:
        print(f"[BETTER] {line}")
    for line in regressions:
        print(f"[FAIL] {line}")
    if improvements and not regressions:
        print("\nbaseline can be lowered: run with --update-baseline")
    if regressions:
        print(f"\n[FAIL] {len(regressions)} prose-style regression(s) above baseline",
              file=sys.stderr)
        return 1
    print("\n[OK] no prose-style regressions above baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
