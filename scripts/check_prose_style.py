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
``long_sentence`` a prose sentence longer than 35 words (paragraphs are
                  joined across wrapped lines; list items, tables, code and
                  headings are skipped). The 2026-08-27 survey found the
                  remaining readability cost in sentences that carry four
                  to six parenthetical register references each.
``meta_governance`` a sentence about how the document is to be read
                  (precedence, canonical/subordinate, "file presence does
                  not imply", "retained for history") rather than about the
                  system. One statement per topic belongs in
                  documentation_governance_v1; repeats elsewhere are noise.

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

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _baseline_ratchet import base_blob, is_gated_ci, skip_note  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BASELINE_REL = "docs/assurance/prose_style_baseline.json"
BASELINE = ROOT / BASELINE_REL

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
    "datasets/",  # corpus data, not documentation
    "data/",  # dataset attribution and holdout status files
    "results/",  # result reports are frozen artifacts
    "tests/",  # fixture attribution files
    "artifacts/credibility-pack/",  # frozen evidence pack
    "CHANGELOG.md",  # historical record
)

TELLS = (
    "emdash",
    "arrow",
    "bold_bullet",
    "not_but",
    "filler",
    "ing_tail",
    "copula_dodge",
    "long_sentence",
    "meta_governance",
)

#: Sentence-level tells are evaluated on joined paragraphs, not lines.
SENTENCE_TELLS = ("long_sentence", "meta_governance")
LONG_SENTENCE_WORDS = 35

_META = re.compile(
    r"(?:\bdoes not (?:imply|make|constitute)\b"
    r"|\bis not (?:part of the (?:enforcing|runtime)|a claim|evidence by itself)\b"
    r"|\bfile presence\b"
    r"|\b(?:takes|take|has|have) precedence\b|\bprecedence (?:order|rule)\b"
    r"|\b(?:is|are|remains?) (?:the )?(?:canonical|authoritative)\b"
    r"|\bcanonical (?:document|source|reference|record|description)\b"
    r"|\bsubordinate to\b"
    r"|\bretained (?:for|as) (?:reproducibility|history|research history|design history|the record)\b"
    r"|\bwhen the two (?:differ|disagree)\b"
    r"|\bnot (?:a description of|part of) (?:shipped|the enforcing)\b)",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z`\"'(\[])")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s")

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


REGISTER = ROOT / "docs" / "assurance" / "document_register_v1.yaml"


def historical_paths() -> set[str]:
    """Documents the register marks ``historical``: snapshot bodies are
    immutable by documentation_governance_v1, so they are never rewritten
    and are excluded from the scan rather than carried in the baseline."""
    if not REGISTER.exists():
        return set()
    paths: set[str] = set()
    current: str | None = None
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("path:"):
            current = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("status:") and current:
            if stripped.split(":", 1)[1].strip() == "historical":
                paths.add(current)
            current = None
    return paths


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md", "**/*.md"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split("\n")
    skip = historical_paths()
    files = []
    for rel in sorted(set(p.strip() for p in out if p.strip())):
        if rel.startswith(EXCLUDE_PREFIXES) or rel in skip:
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


def prose_paragraphs(text: str):
    """Yield paragraphs of running prose: consecutive non-empty prose lines
    joined with spaces. List items, checklists and blank lines end a
    paragraph and are not themselves yielded (a bullet is a label, not a
    sentence)."""
    buf: list[str] = []
    for _, line in prose_lines(text):
        stripped = line.strip()
        if not stripped or _LIST_ITEM.match(line):
            if buf:
                yield " ".join(buf)
                buf = []
            continue
        buf.append(stripped)
    if buf:
        yield " ".join(buf)


def sentences(paragraph: str):
    for s in _SENTENCE_SPLIT.split(paragraph):
        s = s.strip()
        if len(s.split()) > 2:
            yield s


def scan_text(text: str) -> Counter:
    counts: Counter = Counter()
    for _, line in prose_lines(text):
        for tell, rx in _RE.items():
            if tell == "arrow" and _PIPELINE.match(line):
                continue
            n = len(rx.findall(line))
            if n:
                counts[tell] += n
    for para in prose_paragraphs(text):
        for s in sentences(para):
            if len(s.split()) > LONG_SENTENCE_WORDS:
                counts["long_sentence"] += 1
            if _META.search(s):
                counts["meta_governance"] += 1
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


def load_base_baseline() -> dict[str, dict[str, int]] | None:
    """The baseline as it stands on origin/master, or None if unavailable.

    Reading the baseline from the working tree made this a ratchet a pull
    request could reset in the same commit: raise a count, regenerate the
    baseline, ship. The gate is measured against the base branch instead.
    """
    blob = base_blob(BASELINE_REL, ROOT)
    if blob is None:
        return None
    try:
        return json.loads(blob).get("files", {})
    except json.JSONDecodeError:
        return None


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
    parser = argparse.ArgumentParser(description="prose-style ratchet")
    parser.add_argument("--root", type=Path, default=None,
                        help="scan this tree instead of the repository root")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args(argv)

    global ROOT, BASELINE
    if args.root is not None:
        ROOT = args.root.resolve()
        BASELINE = ROOT / BASELINE_REL

    current = scan_repo()
    tot = totals(current)
    print("prose-style tells (tracked Markdown, prose lines only):")
    for t in TELLS:
        print(f"  {t:<13} {tot[t]:5d}")

    if args.report:
        worst = sorted(current.items(), key=lambda kv: -sum(kv[1].values()))[:15]
        print("\nworst files:")
        for f, c in worst:
            print(f"  {sum(c.values()):4d}  {f}")
        return 0

    if args.update_baseline:
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

    # The branch's own baseline is advisory; the gate is the base branch's.
    base = load_base_baseline()
    base_regressions: list[str] = []
    if base is None:
        print(skip_note(BASELINE_REL))
        if is_gated_ci():
            print("\n[FAIL] cannot read the base baseline in CI", file=sys.stderr)
            return 1
    else:
        base_regressions, _ = compare(current, base)
        for line in base_regressions:
            print(f"[FAIL] above origin/master baseline: {line}")

    if regressions or base_regressions:
        n = len(regressions) + len(base_regressions)
        print(f"\n[FAIL] {n} prose-style regression(s) above baseline",
              file=sys.stderr)
        return 1
    print("\n[OK] no prose-style regressions above baseline "
          "(working tree and origin/master)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
