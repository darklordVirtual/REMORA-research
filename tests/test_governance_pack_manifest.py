# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Reviewer pack integrity (P0-1).

The committed governance benchmark pack must carry provenance (commit SHA,
lockfile hashes) and a per-file SHA-256 manifest, and every packaged file must
match its recorded hash. This guards against the pre-fix state where the pack
had no hashes, no commit SHA, and stale copied files.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "artifacts" / "governance-benchmark-pack"
MANIFEST = PACK / "manifest.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_has_provenance_fields() -> None:
    m = _manifest()
    # A committed pack necessarily records the commit BEFORE the one that
    # contains it (a commit cannot embed its own SHA), so head-equality is
    # enforced in CI (.github/workflows/attestation.yml), not here. But the
    # SHA must always be a real commit hash, never absent.
    assert re.fullmatch(r"[0-9a-f]{40}", m.get("commit_sha") or ""), (
        "manifest.json must record the full 40-hex commit_sha of the build"
    )
    assert "worktree_clean" in m
    assert isinstance(m.get("lockfile_sha256"), dict) and m["lockfile_sha256"]
    assert isinstance(m.get("file_sha256"), dict)
    assert m["file_count"] == len(m["copied_files"]) == len(m["file_sha256"])


def test_every_packaged_file_matches_its_recorded_hash() -> None:
    m = _manifest()
    mismatches = []
    for rel, recorded in m["file_sha256"].items():
        f = PACK / rel
        if not f.exists():
            mismatches.append(f"{rel}: missing from pack")
        elif _sha256(f) != recorded:
            mismatches.append(f"{rel}: sha256 differs from manifest")
    assert not mismatches, f"pack integrity failures: {mismatches}"


def test_pack_readme_has_no_stale_task_level_wilson_bound() -> None:
    """The copied README must carry the canonical cluster-level 5.2% bound, not
    the withdrawn task-level 0.55%."""
    readme = (PACK / "README.md").read_text(encoding="utf-8")
    assert "0.55 %" not in readme and "0.55%" not in readme
