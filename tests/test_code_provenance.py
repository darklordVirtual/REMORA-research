# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Current-file coverage must fail closed when the repository changes."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess

import pytest


@pytest.fixture
def gate(repo_root):
    path = repo_root / "scripts/check_code_provenance.py"
    assert path.is_file(), "the all-file provenance gate is missing"
    spec = importlib.util.spec_from_file_location("code_provenance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout.decode().strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Test Contributor")
    git(tmp_path, "config", "user.email", "contributor@example.invalid")
    (tmp_path / "app.py").write_bytes(b"print('first')\r\n")
    (tmp_path / "extensionless").write_bytes(b"#!/bin/sh\ntrue\n")
    (tmp_path / "asset.bin").write_bytes(b"\x00\xff\x80")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "initial source")
    return tmp_path


def write_register(gate, repo):
    path = repo / gate.REGISTER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(gate.render(gate.build(repo)), encoding="utf-8")
    git(repo, "add", ".")
    return path


def test_all_tracked_bytes_modes_and_extensionless_files_are_registered(gate, repo):
    record = gate.build(repo)
    assert set(record["files"]) == {"app.py", "extensionless", "asset.bin"}
    entry = record["files"]["app.py"]
    assert entry["sha256"] == hashlib.sha256(b"print('first')\r\n").hexdigest()
    assert entry["git_blob"] == git(repo, "rev-parse", "HEAD:app.py")
    assert entry["mode"] == "100644"
    assert entry["concepts"] == []  # No automatic assertion of conceptual originality.
    assert gate.render(record) == gate.render(gate.build(repo))


def test_only_the_live_register_excludes_itself(gate, repo):
    write_register(gate, repo)
    assert gate.REGISTER not in gate.build(repo)["files"]
    assert gate.main(["--check"], root=repo) == 0
    (repo / "provenance/other.json").write_text("{}")
    git(repo, "add", ".")
    assert gate.main(["--check"], root=repo) == 1
    assert "provenance/other.json" in gate.build(repo)["files"]


@pytest.mark.parametrize("change", ["add", "edit", "delete", "rename", "mode"])
def test_each_repository_change_refuses_a_stale_register(gate, repo, change, capsys):
    write_register(gate, repo)
    if change == "add":
        (repo / "new.language").write_text("new source")
        git(repo, "add", ".")
    elif change == "edit":
        (repo / "app.py").write_text("print('changed')\n")
    elif change == "delete":
        git(repo, "rm", "app.py")
    elif change == "rename":
        git(repo, "mv", "app.py", "renamed.py")
    else:
        os.chmod(repo / "app.py", 0o755)
        git(repo, "add", ".")
    assert gate.main(["--check"], root=repo) == 1
    assert "stale" in capsys.readouterr().out
    write_register(gate, repo)
    assert gate.main(["--check"], root=repo) == 0


def test_snapshot_is_commit_pinned_and_reproduces_after_later_changes(gate, repo):
    anchor = git(repo, "rev-parse", "HEAD")
    frozen = gate.build(repo, snapshot=anchor)
    (repo / "app.py").write_text("print('newer')\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "later source")
    assert gate.build(repo, snapshot=anchor) == frozen
    assert frozen["snapshot"] == anchor
    assert frozen["files"]["app.py"]["sha256"] != gate.build(repo)["files"]["app.py"]["sha256"]
    out = repo / "frozen.json"
    assert gate.main(["--write", "--snapshot", anchor, "--out", str(out)], root=repo) == 0
    assert gate.main(["--check-snapshot", str(out)], root=repo) == 0
    record = json.loads(out.read_text())
    record["files"]["app.py"]["sha256"] = "0" * 64
    out.write_text(json.dumps(record))
    assert gate.main(["--check-snapshot", str(out)], root=repo) == 1


def test_paths_and_symlinks_are_hashed_without_following_targets(gate, repo):
    name = "space and\nnewline.py"
    (repo / name).write_bytes(b"content")
    (repo / "link").symlink_to("app.py")
    git(repo, "add", ".")
    record = gate.build(repo)
    assert record["files"][name]["sha256"] == hashlib.sha256(b"content").hexdigest()
    assert record["files"]["link"]["mode"] == "120000"
    assert record["files"]["link"]["sha256"] == hashlib.sha256(b"app.py").hexdigest()
    git(repo, "commit", "-qm", "paths and link")
    assert gate.build(repo, snapshot="HEAD")["files"] == record["files"]


def test_untracked_files_are_not_evidence_and_missing_tracked_files_fail(gate, repo):
    before = gate.build(repo)
    (repo / "local-secret.txt").write_text("never register an untracked file")
    assert gate.build(repo) == before
    (repo / "app.py").unlink()
    assert gate.main(["--write"], root=repo) == 1


def test_submodule_is_refused_instead_of_claiming_to_cover_external_code(gate, repo):
    sha = git(repo, "rev-parse", "HEAD")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},vendor")
    assert gate.main(["--write"], root=repo) == 1


def test_concept_links_are_explicit_and_do_not_change_classification(gate, repo):
    concepts = repo / "provenance/concepts"
    concepts.mkdir(parents=True)
    (concepts / "PROV-01.yaml").write_text(
        "concept_id: PROV-01\nclassification: UNKNOWN\n"
        "implementation:\n- path: app.py\ntests: []\ncanonical_spec: []\n"
    )
    git(repo, "add", ".")
    record = gate.build(repo)
    assert record["files"]["app.py"]["concepts"] == ["PROV-01"]
    assert "classification" not in record["files"]["app.py"]
    (repo / "app.py").write_text("different implementation")
    assert gate.build(repo, snapshot="HEAD")["files"]["app.py"]["concepts"] == []
