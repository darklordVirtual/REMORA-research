# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Content identity shared by package publication and runtime reproduction."""
from __future__ import annotations

import hashlib


def package_digest(package_files: list[dict[str, str]]) -> str:
    """SHA-256 over '<path> <sha256>\\n' lines sorted by path."""
    lines = "".join(
        f"{entry['path']} {entry['sha256']}\n"
        for entry in sorted(package_files, key=lambda entry: entry["path"])
    )
    return "sha256:" + hashlib.sha256(lines.encode("utf-8")).hexdigest()
