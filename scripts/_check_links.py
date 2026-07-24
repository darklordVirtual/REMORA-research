# Author: Stian Skogbrott
# License: Apache-2.0
"""Check internal markdown links across README.md, docs/, and artifacts/.

Each link's target is resolved relative to the file that contains it (not the
repo root), so links in nested packs such as ``artifacts/*/README.md`` are
validated the way a reader following them from that file would experience them.

External URLs (http/https/mailto/tel/data) and pure ``#anchor`` links are
skipped. Inline ``#section`` anchors are stripped before the on-disk check.

The link pattern matches CommonMark inline destinations: the destination may
not contain whitespace or parentheses, so line-wrapped or otherwise malformed
``](`` fragments are ignored here rather than reported as missing files. The
destination-text group tolerates one level of nested brackets so image/badge
links (``[![alt](img)](href)``) are matched on their outer destination.

Exits non-zero if any internal link points at a path that does not exist, so a
broken link fails ``make audit`` instead of passing silently.
"""
import sys
from pathlib import Path
import re

ROOT = Path(".")

# Roots to scan. README.md is included explicitly (resolved relative to ROOT,
# preserving the original behaviour); docs/ and artifacts/ are scanned wholesale.
SCAN_DIRS = ["docs", "artifacts"]
EXCLUDE_PARTS = {".git", "node_modules"}

# [text](href) with badge-aware text (one level of nested brackets) and a
# whitespace/paren-free destination.
LINK = re.compile(r"\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)\s]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:", "#")


def markdown_files():
    seen = set()
    readme = ROOT / "README.md"
    if readme.exists():
        seen.add(readme.resolve())
        yield readme
    for base in SCAN_DIRS:
        for md in sorted((ROOT / base).rglob("*.md")):
            if any(part in EXCLUDE_PARTS for part in md.parts):
                continue
            rp = md.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            yield md


ok = 0
skip = 0
broken = []  # (file, label, target)

for md in markdown_files():
    text = md.read_text(encoding="utf-8", errors="replace")
    for m in LINK.finditer(text):
        label, target = m.group(1), m.group(2)
        if target.startswith(EXTERNAL_PREFIXES):
            skip += 1
            continue
        path_part = target.split("#")[0]
        if not path_part:
            skip += 1
            continue
        if (md.parent / path_part).resolve().exists():
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
    sys.exit(1)
print("No broken internal links.")
