# Author: Stian Skogbrott
# License: Apache-2.0
"""Check all internal markdown links in README.md exist on disk."""
import re
from pathlib import Path

ROOT = Path(".")
readme = (ROOT / "README.md").read_text(encoding="utf-8")

# Match [text](path) - skip http/https/anchor-only
pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
broken = []
ok = []
skip = []

for m in pattern.finditer(readme):
    label, target = m.group(1), m.group(2)
    # Skip external URLs and pure anchors
    if target.startswith("http") or target.startswith("#"):
        skip.append(target)
        continue
    # Strip inline anchors like path.md#section
    path_part = target.split("#")[0]
    if not path_part:
        skip.append(target)
        continue
    p = ROOT / path_part
    if p.exists():
        ok.append(path_part)
    else:
        broken.append((label, path_part))

print(f"OK:      {len(ok)}")
print(f"Skipped: {len(skip)} (external/anchor)")
print()
if broken:
    print("BROKEN LINKS:")
    for label, path in broken:
        print(f"  [{label}]({path})")
else:
    print("No broken internal links.")
