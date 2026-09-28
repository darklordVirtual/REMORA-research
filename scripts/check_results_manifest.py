#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Every committed result says how it can be reproduced (quality program Q1.1).

``docs/assurance/results_manifest_v1.yaml`` gives each tracked
``results/**/*.json`` one reproduction class. The class is a measured fact,
taken from running the generator offline in a clean worktree, not a wish:

``regenerable``  the generator ran offline and reproduced the file, apart from
                 declared volatile fields (timestamps, commit). Needs
                 ``generator`` and ``verified_by``.
``drifted``      the generator ran offline and produced different numbers.
                 Needs ``generator``, ``drift`` (what differs) and
                 ``tracking``. The committed file is not current evidence.
``live``         needs API keys or network. Needs ``generator``.
``unverified``   a generator exists but did not run offline as-is (missing
                 arguments, data or dependency). Needs ``generator`` and
                 ``reason``.
``frozen``       history; never regenerated. Needs ``reason``.
``sidecar``      a provenance sidecar. Needs ``of``: the result it describes.

The gate fails on a tracked result without an entry, an entry without a
tracked file, an unknown class, a missing required field, a sidecar whose
result is not in the manifest, or a sidecar whose ``artifact_sha256`` does not
match its result under the LF hash protocol of
``docs/assurance/artifact_manifest_v1.md``. It also prints the class counts, so the
share of results that are current evidence is visible on every run.

    python scripts/check_results_manifest.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path("docs/assurance/results_manifest_v1.yaml")

REQUIRED: dict[str, tuple[str, ...]] = {
    "regenerable": ("generator", "verified_by"),
    "drifted": ("generator", "drift", "tracking"),
    "live": ("generator",),
    "unverified": ("generator", "reason"),
    "frozen": ("reason",),
    "sidecar": ("of",),
}


def _tracked_results(root: Path) -> set[str]:
    out = subprocess.run(["git", "ls-files", "--", "results"], cwd=root,
                         capture_output=True, text=True, check=True).stdout.split()
    return {p for p in out if p.endswith(".json")}


def _sha256_lf(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _sidecar_hash_error(root: Path, path: str, of: str) -> str | None:
    """A recorded artifact hash must be the result's LF hash.

    Sidecars written before the writer normalised line endings hold a hash
    over CRLF bytes; nothing compared the field to the file, so the defect
    stood unnoticed until an external review ran ``sha256sum``. Older schemas
    record no hash at all, and absence is not a mismatch.
    """
    try:
        recorded = json.loads((root / path).read_text(encoding="utf-8")).get("artifact_sha256")
    except (OSError, ValueError, AttributeError):
        return f"{path}: sidecar is not a readable JSON object"
    if not recorded or not (root / of).is_file():
        return None
    if recorded != _sha256_lf(root / of):
        return f"{path}: artifact_sha256 does not match {of}"
    return None


def check(root: Path) -> tuple[list[str], Counter]:
    data = yaml.safe_load((root / MANIFEST).read_text(encoding="utf-8")) or {}
    entries = data.get("results") or []
    errors: list[str] = []
    seen: dict[str, dict] = {}
    for entry in entries:
        path = entry.get("path")
        if not path:
            errors.append(f"entry without path: {entry}")
            continue
        if path in seen:
            errors.append(f"{path}: listed twice")
        seen[path] = entry
        cls = entry.get("class")
        if cls not in REQUIRED:
            errors.append(f"{path}: unknown class {cls!r}")
            continue
        for field in REQUIRED[cls]:
            if not entry.get(field):
                errors.append(f"{path}: class {cls} needs {field!r}")
    tracked = _tracked_results(root)
    for path in sorted(tracked - set(seen)):
        errors.append(f"{path}: committed result with no manifest entry")
    for path in sorted(set(seen) - tracked):
        errors.append(f"{path}: manifest entry for a file that is not tracked")
    for path, entry in seen.items():
        if entry.get("class") == "sidecar" and entry.get("of") not in seen:
            errors.append(f"{path}: sidecar of {entry.get('of')!r}, which is not in the manifest")
        elif entry.get("class") == "sidecar":
            error = _sidecar_hash_error(root, path, entry["of"])
            if error:
                errors.append(error)
    counts = Counter(e.get("class") for e in seen.values())
    return errors, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="results reproduction manifest gate")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    errors, counts = check(args.root)
    summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    if errors:
        print("[FAIL] results manifest:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"[PASS] every committed result has a reproduction class ({summary}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
