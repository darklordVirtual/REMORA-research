#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Verify that every artifact path referenced in docs/claim_register.md exists.

The claim register is the human-readable companion to the YAML claim ledger.
It contains rows like:

    `results/selective_trust_curve_results.json`, `tests/test_selective_trust_curve.py`

This script parses those backtick-quoted paths and confirms that every one that
looks like a file reference resolves to an existing path under the repo root.

Missing artifacts are a sign of:
- Benchmark was run somewhere else and results were not committed.
- A test or result file was renamed without updating the register.
- A claim was added speculatively without producing the backing artifact.

Run as part of `make audit`.  Exits 0 on success, 1 on the first missing file.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAIM_REGISTER = ROOT / "docs" / "claim_register.md"
CLAIM_LEDGER_YAML = ROOT / "docs" / "thermodynamics" / "claim_ledger.yaml"

# Patterns for file-like references (relative path with extension)
_FILE_PATTERN = re.compile(
    r"`([a-zA-Z0-9_\-./]+\.(?:json|yaml|yml|md|py|txt|csv|html|nt|sql))`"
)

# Directories that must exist as roots (sanity check)
_REQUIRED_DIRS = [
    "results",
    "tests",
    "artifacts",
    "docs",
    "remora",
]


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    raise SystemExit(1)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def ok(msg: str) -> None:
    print(f"[OK]   {msg}")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def extract_file_refs(text: str) -> list[str]:
    """Return all backtick-quoted file paths from markdown text."""
    return _FILE_PATTERN.findall(text)


def main() -> None:
    if not CLAIM_REGISTER.exists():
        fail(f"Claim register not found: {CLAIM_REGISTER}")

    # -- Required directory structure ------------------------------------------
    for d in _REQUIRED_DIRS:
        p = ROOT / d
        if not p.is_dir():
            fail(f"Required directory missing: {d}/")
    ok("Required directory structure present")

    # -- Artifact paths in claim_register.md ----------------------------------
    register_text = read(CLAIM_REGISTER)
    refs = extract_file_refs(register_text)

    missing: list[str] = []
    found = 0
    for ref in refs:
        path = ROOT / ref
        if path.exists():
            found += 1
        else:
            missing.append(ref)

    if missing:
        print(f"\n[FAIL] {len(missing)} artifact(s) referenced in claim_register.md are missing:")
        for m in missing:
            print(f"       {m}")
        print(
            "\nFix: run the relevant experiment/benchmark to regenerate the missing artifact,\n"
            "or remove the reference from docs/claim_register.md if the artifact is obsolete."
        )
        raise SystemExit(1)

    ok(f"All {found} artifact reference(s) in claim_register.md exist")

    # -- Claim ledger YAML (basic presence check) ------------------------------
    if CLAIM_LEDGER_YAML.exists():
        ok(f"Claim ledger YAML present: {CLAIM_LEDGER_YAML.relative_to(ROOT)}")
    else:
        warn(f"Claim ledger YAML not found: {CLAIM_LEDGER_YAML.relative_to(ROOT)}")

    print("\n[PASS] All artifact existence checks passed.")


if __name__ == "__main__":
    main()
