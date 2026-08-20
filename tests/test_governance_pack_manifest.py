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


CRLF = bytes([13, 10])
LF = bytes([10])


def _sha256(path: Path) -> str:
    """LF-normalized digest, matching the pack hash protocol.

    The builder hashes CRLF-normalized bytes so a pack built on Windows
    and one built on Linux record identical hashes. Reading raw bytes
    here made this test pass on Linux and fail on Windows for the same,
    correct pack.
    """
    normalized = path.read_bytes().replace(CRLF, LF)
    return hashlib.sha256(normalized).hexdigest()


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
    """Bundle integrity: every shipped byte matches what the manifest records.

    ``packaged_sha256`` rather than ``file_sha256``: the builder rewrites
    links to documents the pack does not ship into permalinks pinned to the
    build commit, so the packaged markdown deliberately differs from the
    repository source. ``file_sha256`` still records the source hash, so
    provenance is not lost — see ``file_sha256_note`` in the manifest.
    """
    m = _manifest()
    recorded_hashes = m.get("packaged_sha256") or m["file_sha256"]
    mismatches = []
    for rel, recorded in recorded_hashes.items():
        f = PACK / rel
        if not f.exists():
            mismatches.append(f"{rel}: missing from pack")
        elif _sha256(f) != recorded:
            mismatches.append(f"{rel}: sha256 differs from manifest")
    assert not mismatches, f"pack integrity failures: {mismatches}"


def test_source_provenance_hashes_are_still_recorded() -> None:
    """Rewriting links must not cost the pack its link back to the source."""
    m = _manifest()
    assert set(m["file_sha256"]) == set(m["packaged_sha256"])
    assert "file_sha256_note" in m


def test_pack_readme_has_no_stale_task_level_wilson_bound() -> None:
    """The copied README must carry the canonical cluster-level 5.2% bound, not
    the withdrawn task-level 0.55%."""
    readme = (PACK / "README.md").read_text(encoding="utf-8")
    assert "0.55 %" not in readme and "0.55%" not in readme
