#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Fail CI when the repository drifts away from the BUSL-1.1 licensing model.

Two checks:
1. The required licensing files exist and carry their load-bearing text.
2. No active file re-acquires an Apache license HEADER (the exact header
   forms). Narrative mentions of the Apache license (third-party notices,
   historical explanations, archived documents) are allowed; active license
   metadata is not.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Files/dirs where Apache header-form strings may legitimately appear.
ALLOWED_APACHE_PARTS = {"archive", "LICENSES", "node_modules", ".git", ".venv",
                        "dist", "build"}
ALLOWED_APACHE_FILES = {"THIRD_PARTY_NOTICES.md", "check_license_policy.py",
                        "migrate_license_headers.py"}

TEXT_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".sh", ".rego",
    ".tex", ".md", ".yaml", ".yml", ".toml", ".cff", ".txt",
}

STALE_HEADERS = (
    "SPDX-License-Identifier: Apache-2.0",
    "License: Apache-2.0",
    "License :: OSI Approved :: Apache Software License",
)

REQUIRED = {
    "LICENSE": "Business Source License 1.1",
    "LICENSING.md": "REMORA Commercial License",
    "COMMERCIAL_LICENSE.md": "not itself a commercial software",
    "TRADEMARKS.md": "Trademark Policy",
    "THIRD_PARTY_NOTICES.md": "Third-Party Notices",
    "COPYRIGHT.md": "Stian Skogbrott",
    "NOTICE": "Business Source License 1.1",
    "pyproject.toml": 'license = "BUSL-1.1"',
    "CITATION.cff": "license: BUSL-1.1",
}


def main() -> int:
    errors: list[str] = []

    for relative, expected in REQUIRED.items():
        path = ROOT / relative
        if not path.exists():
            errors.append(f"missing required licensing file: {relative}")
            continue
        if expected not in path.read_text(encoding="utf-8"):
            errors.append(f"{relative}: missing expected text {expected!r}")

    licensor_files = ["LICENSE", "NOTICE", "COPYRIGHT.md"]
    for relative in licensor_files:
        path = ROOT / relative
        if path.exists() and "Stian Skogbrott" not in path.read_text(encoding="utf-8"):
            errors.append(f"{relative}: Licensor 'Stian Skogbrott' missing")

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in ALLOWED_APACHE_PARTS for part in relative.parts):
            continue
        if relative.name in ALLOWED_APACHE_FILES:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"LICENSE", "NOTICE"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for stale in STALE_HEADERS:
            if stale in content:
                errors.append(f"{relative.as_posix()}: stale Apache metadata ({stale!r})")

    if errors:
        print("License policy check failed:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("License policy check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
