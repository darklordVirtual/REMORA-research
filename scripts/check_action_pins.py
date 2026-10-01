#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Require every external GitHub Action to be pinned to a full commit SHA.

Invariant: ``uses: owner/repo[/path]@<40-hex-sha>``. Floating tags
(``@v4``) and branches (``@main``) are mutable references and are refused.
Local actions (``uses: ./...``) and Docker references (``docker://``) are
exempt. Exit 1 on any violation.

The check parses the workflow rather than reading it line by line. Until
2026-09-03 it matched ``^\\s*-?\\s*uses:``, which meant flow-style
(``- {uses: actions/cache@v4}``) and quoted (``"uses": ...``) spellings
were invisible: an unpinned action written either way passed the gate.
YAML is the language GitHub reads the file in, so it is the language this
gate reads it in too. Reusable workflow calls (``jobs.<id>.uses``) are
covered for the same reason.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Iterator

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _iter_uses(document: Any) -> Iterator[str]:
    """Yield every ``uses:`` value in a parsed workflow.

    The walk is structural rather than positional, so it covers a step's
    ``uses`` under ``jobs.<id>.steps[]``, a reusable workflow call at
    ``jobs.<id>.uses``, and any other position a future schema puts one in.
    Missing a reference is the failure mode that matters here: an unpinned
    action the gate never sees is an unpinned action that ships.
    """
    if isinstance(document, dict):
        for key, value in document.items():
            if key == "uses" and isinstance(value, str):
                yield value
            else:
                yield from _iter_uses(value)
    elif isinstance(document, list):
        for item in document:
            yield from _iter_uses(item)


def find_violations(workflow_dir: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(workflow_dir.glob("*.y*ml")):
        rel = path.relative_to(workflow_dir).as_posix()
        text = path.read_text(encoding="utf-8")
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            violations.append(f"{rel}: unparseable workflow ({exc.__class__.__name__})")
            continue
        for ref in _iter_uses(document):
            if ref.startswith(("./", "docker://")):
                continue
            _, _, version = ref.partition("@")
            if not SHA_RE.match(version):
                violations.append(f"{rel}:{_lineno(text, ref)}: {ref}")
    return violations


def _lineno(text: str, ref: str) -> int:
    """Best-effort source line for a reference, for a readable message."""
    for i, line in enumerate(text.splitlines(), 1):
        if ref in line:
            return i
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GitHub Action pinning gate")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="check this tree's .github/workflows instead of the repository's",
    )
    args = parser.parse_args(argv)
    workflows = (
        (args.root.resolve() / ".github" / "workflows")
        if args.root is not None
        else WORKFLOWS
    )

    violations = find_violations(workflows)
    for v in violations:
        print(f"[FAIL] unpinned action {v}")
    if violations:
        print(f"[FAIL] {len(violations)} action reference(s) not pinned to a full commit SHA")
        return 1
    print("[OK] all external GitHub Actions are SHA-pinned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
