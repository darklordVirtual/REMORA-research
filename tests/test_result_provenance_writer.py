# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the result-provenance sidecar writer (research audit remedy).

Every future result artifact gets a .provenance.json sidecar binding it to
the exact code, environment and inputs that produced it. The v3 tests
monkeypatch the git-facing helpers — never assert on the real repo's live
worktree state (a Windows dev tree is often dirty; CI checkouts are clean).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import result_provenance  # noqa: E402
from result_provenance import (  # noqa: E402
    build_provenance,
    capture_pre_run_state,
    write_sidecar,
)

V3_FIELDS = (
    "pre_run_worktree_clean",
    "allowed_generated_outputs",
    "post_run_worktree_clean",
    "worktree_dirty_beyond_outputs",
)


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


# ---------------------------------------------------------------------------
# result_provenance_v3 (issue #32) — additive, opt-in
# ---------------------------------------------------------------------------

def test_v2_unchanged_without_new_params() -> None:
    prov = build_provenance(
        script="scripts/example.py",
        inputs={},
        random_seeds=None,
        command="python scripts/example.py",
    )
    assert prov["schema"] == "result_provenance_v2"
    for field in V3_FIELDS:
        assert field not in prov
    # v2 key order is part of the byte-compat contract for committed sidecars.
    assert list(prov)[:3] == ["schema", "git_commit", "worktree_clean"]


def test_v3_requires_both_params() -> None:
    with pytest.raises(ValueError, match="both"):
        build_provenance(script="s.py", pre_run_worktree_clean=True)
    with pytest.raises(ValueError, match="both"):
        build_provenance(script="s.py", allowed_generated_outputs=["a.json"])
    with pytest.raises(ValueError, match="both"):
        write_sidecar(
            Path("irrelevant.json"), script="s.py", pre_run_worktree_clean=False
        )


def test_v3_fields_emitted_and_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        result_provenance, "_worktree_dirty_paths", lambda: ["results/a.json"]
    )
    prov = build_provenance(
        script="scripts/example.py",
        pre_run_worktree_clean=True,
        # Mixed separators and types must normalize to sorted POSIX strings.
        allowed_generated_outputs={"results\\a.json", Path("results/a.json")},
    )
    assert prov["schema"] == "result_provenance_v3"
    assert prov["pre_run_worktree_clean"] is True
    assert prov["allowed_generated_outputs"] == ["results/a.json"]
    assert prov["post_run_worktree_clean"] is True
    assert prov["worktree_dirty_beyond_outputs"] == []
    # The raw v2 flag is retained in v3 for continuity.
    assert prov["worktree_clean"] is False
    # New fields sit directly after worktree_clean.
    keys = list(prov)
    assert keys[2:7] == ["worktree_clean", *V3_FIELDS]


def test_v3_dirty_beyond_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        result_provenance,
        "_worktree_dirty_paths",
        lambda: ["results/a.json", "scripts/hack.py"],
    )
    prov = build_provenance(
        script="scripts/example.py",
        pre_run_worktree_clean=False,
        allowed_generated_outputs=["results/a.json"],
    )
    assert prov["post_run_worktree_clean"] is False
    assert prov["worktree_dirty_beyond_outputs"] == ["scripts/hack.py"]
    # pre_run flag echoes the caller's captured value independently.
    assert prov["pre_run_worktree_clean"] is False


def test_worktree_dirty_paths_parses_porcelain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    porcelain = (
        # First line as the real _git() returns it: stdout.strip() has eaten
        # the leading status column (" M first.json" -> "M first.json").
        "M first.json\n"
        " M results/x.json\n"
        "?? new.json\n"
        "R  old.json -> new2.json\n"
        '?? "has space.json"'
    )
    monkeypatch.setattr(
        result_provenance, "_git", lambda *args: porcelain
    )
    assert result_provenance._worktree_dirty_paths() == [
        "first.json",
        "has space.json",
        "new.json",
        "new2.json",
        "old.json",
        "results/x.json",
    ]


def test_capture_pre_run_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        result_provenance, "_worktree_dirty_paths", lambda: ["results/x.json"]
    )
    state = capture_pre_run_state()
    assert state == {
        "pre_run_worktree_clean": False,
        "pre_run_dirty_paths": ["results/x.json"],
    }
    monkeypatch.setattr(result_provenance, "_worktree_dirty_paths", lambda: [])
    assert capture_pre_run_state() == {
        "pre_run_worktree_clean": True,
        "pre_run_dirty_paths": [],
    }


def test_write_sidecar_v3_passthrough(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(result_provenance, "_worktree_dirty_paths", lambda: [])
    artifact = tmp_path / "some_result.json"
    artifact.write_text("{}", encoding="utf-8")
    sidecar = write_sidecar(
        artifact,
        script="scripts/example.py",
        inputs={},
        random_seeds=None,
        command="cmd",
        pre_run_worktree_clean=True,
        allowed_generated_outputs=["results/some_result.json"],
    )
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["schema"] == "result_provenance_v3"
    assert data["pre_run_worktree_clean"] is True
    assert data["allowed_generated_outputs"] == ["results/some_result.json"]
    assert data["post_run_worktree_clean"] is True
    assert data["worktree_dirty_beyond_outputs"] == []
