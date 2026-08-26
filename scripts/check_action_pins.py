#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Require every external GitHub Action to be pinned to a full commit SHA.

Invariant: ``uses: owner/repo[/path]@<40-hex-sha>``. Floating tags
(``@v4``) and branches (``@main``) are mutable references and are refused.
Local actions (``uses: ./...``) and Docker references (``docker://``) are
exempt. Exit 1 on any violation.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
USES_RE = re.compile(r"^\s*-?\s*uses:\s*['\"]?([^'\"\s#]+)")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def find_violations(workflow_dir: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(workflow_dir.glob("*.y*ml")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = USES_RE.match(line)
            if not m:
                continue
            ref = m.group(1)
            if ref.startswith(("./", "docker://")):
                continue
            _, _, version = ref.partition("@")
            if not SHA_RE.match(version):
                violations.append(f"{path.relative_to(workflow_dir).as_posix()}:{lineno}: {ref}")
    return violations


def main() -> int:
    violations = find_violations(WORKFLOWS)
    for v in violations:
        print(f"[FAIL] unpinned action {v}")
    if violations:
        print(f"[FAIL] {len(violations)} action reference(s) not pinned to a full commit SHA")
        return 1
    print("[OK] all external GitHub Actions are SHA-pinned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
