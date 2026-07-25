#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Replace REMORA's own Apache headers with BUSL-1.1 headers.

One-shot migration tool for the 2026-07-25 license change (Apache-2.0 ->
Business Source License 1.1). It intentionally changes only exact REMORA
header patterns; it does not touch third-party license text, historical
archive documents, or the license files themselves.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "LICENSES",
    "archive",  # historical documents may quote the old header verbatim
}

SKIP_FILES = {
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "LICENSING.md",
    "migrate_license_headers.py",
    "check_license_policy.py",
}

TEXT_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".sh",
    ".rego", ".tex", ".md", ".yaml", ".yml", ".toml", ".cff",
}

# Patterns are assembled at runtime so this file never contains the stale
# header literals itself (it must be idempotent and skippable by the policy
# checker without special-casing its own contents).
_OLD_LICENSE = "License: " + "Apache-2.0"
_OLD_SPDX = "SPDX-License-Identifier: " + "Apache-2.0"
_NEW_SPDX = "SPDX-License-Identifier: BUSL-1.1"

REPLACEMENTS = {
    f"# {_OLD_LICENSE}": f"# {_NEW_SPDX}",
    f"// {_OLD_LICENSE}": f"// {_NEW_SPDX}",
    f"% {_OLD_LICENSE}": f"% {_NEW_SPDX}",
    f"# {_OLD_SPDX}": f"# {_NEW_SPDX}",
    f"// {_OLD_SPDX}": f"// {_NEW_SPDX}",
    f"% {_OLD_SPDX}": f"% {_NEW_SPDX}",
}


def should_skip(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in SKIP_DIRS for part in relative.parts):
        return True
    if relative.name in SKIP_FILES:
        return True
    return path.suffix.lower() not in TEXT_SUFFIXES


def main() -> int:
    changed: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or should_skip(path):
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = original
        for old, new in REPLACEMENTS.items():
            updated = updated.replace(old, new)
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
            changed.append(path.relative_to(ROOT))
    print(f"Updated {len(changed)} files")
    for path in changed[:20]:
        print(f"  {path}")
    if len(changed) > 20:
        print(f"  ... and {len(changed) - 20} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
