# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Check internal markdown links across README.md, docs/, and artifacts/.

Each link's target is resolved relative to the file that contains it (not the
repo root), so links in nested packs such as ``artifacts/*/README.md`` are
validated the way a reader following them from that file would experience them.

External URLs (http/https/mailto/tel/data) and pure ``#anchor`` links are
skipped. Inline ``#section`` anchors are stripped before the on-disk check.

Three link forms are checked, because a reader follows all three:

* inline ``[text](destination)``. The destination may not contain whitespace
  or parentheses, so line-wrapped or otherwise malformed ``](`` fragments are
  ignored here rather than reported as missing files. The destination-text
  group tolerates one level of nested brackets so image/badge links
  (``[![alt](img)](href)``) are matched on their outer destination.
* reference definitions ``[label]: destination``. Until 2026-09-03 these were
  never checked, so ``[r]: docs/missing.md`` was a dead link the gate could
  not see.
* autolinks ``<destination>``, for the same reason. Only path-shaped contents
  are treated as links, so HTML tags and ``<Type>`` in prose are left alone.

The scan root is anchored to this file's location rather than to the current
working directory, so the result does not depend on where the gate is run
from. ``--root`` points it at another tree.

Exits non-zero if any internal link points at a path that does not exist, so a
broken link fails ``make audit`` instead of passing silently.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Roots to scan. README.md is included explicitly (resolved relative to ROOT,
# preserving the original behaviour); docs/ and artifacts/ are scanned wholesale.
SCAN_DIRS = ["docs", "artifacts"]
# governance-benchmark-pack used to be excluded here, on the reasoning that it
# copies repo files verbatim so their root-relative links resolve at the
# canonical source rather than inside the bundle. That reasoning is why 31 dead
# links shipped to external reviewers unnoticed: the pack is the artifact those
# reviewers actually read, and inside it those links resolved to nothing. The
# builder now rewrites links to unshipped documents into permalinks pinned to
# the build commit, so the pack is self-consistent and is checked like anything
# else. Rebuild it (`make benchmark-package`) if this gate flags it.
#
# ``archive`` stays excluded and the reason is stated rather than assumed:
# archived documents are preserved verbatim by policy, so a link that rotted
# after the snapshot was taken cannot be repaired without editing text the
# policy keeps immutable. ``.git`` and ``node_modules`` are not documentation.
EXCLUDE_PARTS = {".git", "node_modules", "archive"}

# [text](href) with badge-aware text (one level of nested brackets) and a
# whitespace/paren-free destination.
LINK = re.compile(r"\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)\s]+)\)")
# [label]: destination  — a reference definition at the start of a line.
REF_DEF = re.compile(r"^[ \t]{0,3}\[([^\]]+)\]:[ \t]*(\S+)", re.MULTILINE)
# <destination> — an autolink whose contents look like a path, not markup.
# The extension list keeps `<remora.sdk>` and `<Mapping[str, int]>` in prose
# from being read as file references; a document link ends in one of these.
_DOC_EXT = (
    "md|txt|json|jsonl|yaml|yml|toml|csv|tsv|py|sh|tex|bib|html|svg|png|jpg"
    "|pdf|ts|tsx|ipynb|cfg|ini|lock"
)
AUTOLINK = re.compile(
    rf"<([A-Za-z0-9._~/-]+\.(?:{_DOC_EXT})(?:#[^>\s]*)?)>", re.IGNORECASE
)
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:", "#")


def markdown_files(root: Path):
    seen = set()
    readme = root / "README.md"
    if readme.exists():
        seen.add(readme.resolve())
        yield readme
    for base in SCAN_DIRS:
        for md in sorted((root / base).rglob("*.md")):
            if any(part in EXCLUDE_PARTS for part in md.parts):
                continue
            rp = md.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            yield md


def targets(text: str):
    """Yield (label, destination) for every checkable link form."""
    for m in LINK.finditer(text):
        yield m.group(1), m.group(2)
    for m in REF_DEF.finditer(text):
        yield m.group(1), m.group(2).strip("<>")
    for m in AUTOLINK.finditer(text):
        yield m.group(1), m.group(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="internal markdown link gate")
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="scan this tree instead of the repository root",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    ok = 0
    skip = 0
    broken: list[tuple[str, str, str]] = []

    for md in markdown_files(root):
        text = md.read_text(encoding="utf-8", errors="replace")
        for label, target in targets(text):
            if target.startswith(EXTERNAL_PREFIXES):
                skip += 1
                continue
            path_part = target.split("#")[0]
            if not path_part:
                skip += 1
                continue
            if (md.parent / path_part).exists():
                ok += 1
            else:
                broken.append((md.as_posix(), label, target))

    print(f"Files scanned: README.md + {'/, '.join(SCAN_DIRS)}/")
    print(f"OK:      {ok}")
    print(f"Skipped: {skip} (external/anchor)")
    print()
    if broken:
        print(f"BROKEN LINKS ({len(broken)}):")
        for f, label, target in broken:
            print(f"  {f}: [{label}]({target})")
        return 1
    print("No broken internal links.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
