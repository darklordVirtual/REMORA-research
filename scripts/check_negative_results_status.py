#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""NEGATIVE_RESULTS.md status gate: the summary must match the sections.

Until 2026-07-31 the document read as a list of 35 open problems. It was not.
Sections kept the status they were written with, so §21 still said "active
highest-priority gap" after §§22-35 resolved it, §22 still said "next: resolver
availability layer" after §23 built one, and §32 still presented 50%
wrong-argument acceptance as the standing residual risk after §35 took it to 0%.
A reader could not tell a falsified hypothesis from a live bug.

The fix is a status marker under every section heading and three grouped tables
that must agree with those markers. This gate enforces the agreement, so the
summary cannot drift away from the sections again:

1. Every numbered section carries exactly one valid marker.
2. Every section cited in a summary group has that group's status.
3. Every section cited in the backlog block is `open` — the backlog is the
   `open` set, not a hand-maintained parallel list.
4. The declared counts in the prose match the actual counts.

Statuses:
  open        a real remaining gap, in the backlog
  accepted    measured and published, and NOT to be "fixed" — a falsified
              hypothesis, or a dataset that cannot answer the question
  superseded  a later section documents the resolution

Exit codes: 0 = consistent, 1 = drift (listed on stderr).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "NEGATIVE_RESULTS.md"

VALID = ("open", "accepted", "superseded")
HEADING_RE = re.compile(r"^(#{2,3}) (?:§)?(\d{1,2})[.\s]")
MARKER_RE = re.compile(r"^<!--\s*finding-status:\s*(\w+)\s*-->\s*$")
SECTION_REF_RE = re.compile(r"§(\d{1,2})")
#: Only the first cell of a table row identifies the finding. Later cells say
#: what resolved it, and those references must not be read as claims about the
#: cited section's own status.
FIRST_CELL_RE = re.compile(r"^\|([^|]*)\|")
#: In the backlog, only the parenthetical directly after a bold theme title
#: names that theme's sections; prose may cite anything for context.
THEME_SECTIONS_RE = re.compile(r"\*\*[^*]+\*\* \(([^)]*§[^)]*)\)")
COUNT_RE = re.compile(
    r"\*\*(\d+) `open`\*\*, \*\*(\d+) `accepted`\*\*, \*\*(\d+) `superseded`\*\*"
)
GROUP_HEADINGS = {
    "### Open — the current backlog": "open",
    "### Accepted negative results — do not \"fix\" these": "accepted",
    "### Superseded — resolved by a later section, kept for the causal chain": "superseded",
}


def parse_sections(lines: list[str]) -> tuple[dict[int, str], list[str]]:
    """Map section number -> declared status, collecting structural errors."""
    statuses: dict[int, str] = {}
    errors: list[str] = []
    for idx, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if not m:
            continue
        number = int(m.group(2))
        if number in statuses:
            continue  # a repeated number is the register's problem, not ours
        nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
        marker = MARKER_RE.match(nxt.strip())
        if not marker:
            errors.append(
                f"NEGATIVE_RESULTS.md:{idx + 1}: section {number} has no "
                f"<!-- finding-status: ... --> marker directly under its heading"
            )
            continue
        value = marker.group(1)
        if value not in VALID:
            errors.append(
                f"NEGATIVE_RESULTS.md:{idx + 2}: section {number} declares "
                f"status {value!r}, expected one of {VALID}"
            )
            continue
        statuses[number] = value
    return statuses, errors


def _block(text: str, start: str, end: str) -> str:
    try:
        return text[text.index(start) + len(start) : text.index(end)]
    except ValueError:
        return ""


def check_summary_groups(text: str, statuses: dict[int, str]) -> list[str]:
    errors: list[str] = []
    headings = list(GROUP_HEADINGS)
    for i, heading in enumerate(headings):
        if heading not in text:
            errors.append(f"summary table: missing group heading {heading!r}")
            continue
        start = text.index(heading) + len(heading)
        rest = [h for h in headings[i + 1 :] if h in text]
        end = text.index(rest[0]) if rest else len(text)
        expected = GROUP_HEADINGS[heading]
        cells = [
            m.group(1)
            for line in text[start:end].splitlines()
            for m in [FIRST_CELL_RE.match(line.strip())]
            if m
        ]
        refs = {int(n) for cell in cells for n in SECTION_REF_RE.findall(cell)}
        for number in sorted(refs):
            actual = statuses.get(number)
            if actual is None:
                errors.append(
                    f"summary table ({expected}): cites §{number}, which has no "
                    f"status marker"
                )
            elif actual != expected:
                errors.append(
                    f"summary table: §{number} is listed under {expected!r} but "
                    f"the section declares {actual!r} — one of them is stale"
                )
    return errors


def check_backlog(text: str, statuses: dict[int, str]) -> list[str]:
    block = _block(text, "<!-- backlog-start -->", "<!-- backlog-end -->")
    if not block:
        return ["backlog: <!-- backlog-start --> / <!-- backlog-end --> block missing"]
    errors: list[str] = []
    cited = {
        int(n)
        for group in THEME_SECTIONS_RE.findall(block)
        for n in SECTION_REF_RE.findall(group)
    }
    for number in sorted(cited):
        if statuses.get(number) != "open":
            errors.append(
                f"backlog: cites §{number}, which is "
                f"{statuses.get(number, 'unmarked')!r}, not 'open' — the backlog "
                f"is the open set, not a parallel list"
            )
    for number, status in sorted(statuses.items()):
        if status == "open" and number not in cited:
            errors.append(
                f"backlog: §{number} is marked 'open' but no backlog theme "
                f"cites it — either add it or re-status the section"
            )
    return errors


def check_counts(text: str, statuses: dict[int, str]) -> list[str]:
    m = COUNT_RE.search(text)
    if not m:
        return ["counts: the declared open/accepted/superseded totals are missing"]
    declared = {
        "open": int(m.group(1)),
        "accepted": int(m.group(2)),
        "superseded": int(m.group(3)),
    }
    errors: list[str] = []
    for status, n in declared.items():
        actual = sum(1 for v in statuses.values() if v == status)
        if n != actual:
            errors.append(
                f"counts: prose declares {n} {status!r} sections, markers say {actual}"
            )
    return errors


def run() -> int:
    if not DOC.exists():
        print(f"[FAIL] missing {DOC}", file=sys.stderr)
        return 1
    text = DOC.read_text(encoding="utf-8")
    lines = text.splitlines()

    statuses, errors = parse_sections(lines)
    errors += check_summary_groups(text, statuses)
    errors += check_backlog(text, statuses)
    errors += check_counts(text, statuses)

    if errors:
        print("NEGATIVE_RESULTS.md status gate FAILED:", file=sys.stderr)
        for e in errors:
            print(f" - {e}", file=sys.stderr)
        return 1

    tally = {s: sum(1 for v in statuses.values() if v == s) for s in VALID}
    print(
        f"[OK] NEGATIVE_RESULTS.md status gate passed: {len(statuses)} sections "
        f"({tally['open']} open, {tally['accepted']} accepted, "
        f"{tally['superseded']} superseded)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(run())
