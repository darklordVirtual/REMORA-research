# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts" / "interop" / "runtime-surface-e7-v0.1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_e7_manifest_pins_package_bytes() -> None:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    expected = {entry["path"]: entry["sha256"] for entry in manifest["package_files"]}
    for relpath, digest in expected.items():
        assert _sha256(ROOT / relpath) == digest


def test_e7_reference_verifier_matches_all_expected_results() -> None:
    result = subprocess.run(
        [sys.executable, str(PACKAGE / "reference_verifier.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["failures"] == []
    assert len(payload["results"]) == 5
