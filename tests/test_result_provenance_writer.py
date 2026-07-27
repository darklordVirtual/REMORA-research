# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the result-provenance sidecar writer (research audit remedy).

Every future result artifact gets a .provenance.json sidecar binding it to
the exact code, environment and inputs that produced it.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from result_provenance import build_provenance, write_sidecar  # noqa: E402


def test_build_provenance_core_fields(tmp_path: Path) -> None:
    inp = tmp_path / "tasks.json"
    inp.write_text('{"tasks": []}', encoding="utf-8")

    prov = build_provenance(
        script="scripts/example.py",
        inputs={"tasks": inp},
        random_seeds=[42],
        command="python scripts/example.py",
    )
    assert prov["schema"] == "result_provenance_v2"
    assert len(prov["git_commit"]) == 40
    assert isinstance(prov["worktree_clean"], bool)
    assert prov["python_version"].startswith(f"{sys.version_info[0]}.")
    assert len(prov["dependency_lock_sha256"]) == 64
    expected = hashlib.sha256(
        inp.read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()
    assert prov["input_sha256"]["tasks"] == expected
    assert prov["random_seeds"] == [42]
    assert prov["command"] == "python scripts/example.py"
    assert "generated_at" in prov


def test_write_sidecar_places_file_next_to_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "some_result.json"
    artifact.write_text("{}", encoding="utf-8")
    sidecar = write_sidecar(
        artifact,
        script="scripts/example.py",
        inputs={},
        random_seeds=None,
        command="cmd",
    )
    assert sidecar == tmp_path / "some_result.provenance.json"
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["artifact_sha256"] == hashlib.sha256(b"{}").hexdigest()
    assert data["schema"] == "result_provenance_v2"
