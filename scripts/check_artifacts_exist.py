#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Verify that every artifact path claimed as evidence resolves to a real file.

Two sources are checked:

1. ``docs/claim_register.md`` (backtick-quoted paths in the prose table);
2. ``docs/assurance/remediation_register.yaml`` (the ``artifacts:`` list of each
   REM entry). Added 2026-09-03 after a documentation audit found REM-019, a P0
   release blocker, citing a script and a test file that have never existed in
   this repository. An evidence pointer nobody checks is how a register drifts
   from being evidence into being a story about evidence.

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

import yaml

ROOT = Path(__file__).resolve().parent.parent
CLAIM_REGISTER = ROOT / "docs" / "claim_register.md"
CLAIM_LEDGER_YAML = ROOT / "docs" / "thermodynamics" / "claim_ledger.yaml"
REMEDIATION_REGISTER = ROOT / "docs" / "assurance" / "remediation_register.yaml"

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


def remediation_artifact_refs() -> list[tuple[str, str]]:
    """Return ``(rem_id, path)`` for every artifact listed in the REM register.

    Entries that are plainly not repository paths (a bare URL, an endpoint) are
    skipped; everything that looks like a path is required to exist.
    """
    if not REMEDIATION_REGISTER.exists():
        return []
    data = yaml.safe_load(read(REMEDIATION_REGISTER)) or {}
    refs: list[tuple[str, str]] = []
    for entry in data.get("items", []) or []:
        if not isinstance(entry, dict):
            continue
        rem_id = str(entry.get("id", "<unknown>"))
        for ref in entry.get("artifacts") or []:
            if not isinstance(ref, str):
                continue
            ref = ref.strip()
            if not ref or "://" in ref:
                continue
            refs.append((rem_id, ref))
    return refs


def check_remediation_register() -> None:
    refs = remediation_artifact_refs()
    if not refs:
        warn(f"No remediation artifacts found in {REMEDIATION_REGISTER.name}")
        return
    missing = [(rem_id, ref) for rem_id, ref in refs if not (ROOT / ref).exists()]
    if missing:
        print(
            f"\n[FAIL] {len(missing)} artifact(s) cited in "
            f"remediation_register.yaml do not exist:"
        )
        for rem_id, ref in missing:
            print(f"       {rem_id}: {ref}")
        print(
            "\nFix: point the entry at evidence that is committed here, or "
            "say plainly in its notes that the evidence is imported and where "
            "it lives (the pattern CLAIM-002 uses). Do not cite a file this "
            "repository does not have."
        )
        raise SystemExit(1)
    ok(f"All {len(refs)} artifact reference(s) in remediation_register.yaml exist")


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

    # -- Artifact paths in remediation_register.yaml ---------------------------
    check_remediation_register()

    # -- Claim ledger YAML (basic presence check) ------------------------------
    if CLAIM_LEDGER_YAML.exists():
        ok(f"Claim ledger YAML present: {CLAIM_LEDGER_YAML.relative_to(ROOT)}")
    else:
        warn(f"Claim ledger YAML not found: {CLAIM_LEDGER_YAML.relative_to(ROOT)}")

    print("\n[PASS] All artifact existence checks passed.")


if __name__ == "__main__":
    main()
