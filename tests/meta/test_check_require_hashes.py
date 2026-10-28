# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for scripts/check_require_hashes.py (SR-11/SR-23, SEC-19).

The gate must catch a bare third-party install and a lock pin without a hash,
and must accept the legitimate patterns: hashed -r install, -c constraints,
pip self-upgrade, editable local install, and an explicit marker.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_require_hashes.py"


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=cwd or ROOT,
    )


def _tree(tmp_path: Path, workflow: str, locks: dict[str, str]) -> Path:
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "ci.yml").write_text(workflow, encoding="utf-8")
    for name, content in locks.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return tmp_path


_GOOD_LOCK = (
    "pytest==9.1.1 \\\n"
    "    --hash=sha256:" + "a" * 64 + "\n"
)
_BAD_LOCK = "pytest==9.1.1\n"


def test_repo_tree_passes() -> None:
    proc = _run()
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_bare_third_party_install_fails(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        "jobs:\n  x:\n    steps:\n      - run: pip install cyclonedx-bom\n",
        {"requirements-ci.lock": _GOOD_LOCK,
         "requirements-release.lock": _GOOD_LOCK},
    )
    proc = _run("--root", str(tree))
    assert proc.returncode == 1
    assert "without --require-hashes" in proc.stdout


def test_lock_pin_without_hash_fails(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        "jobs:\n  x:\n    steps: []\n",
        {"requirements-ci.lock": _BAD_LOCK,
         "requirements-release.lock": _GOOD_LOCK},
    )
    proc = _run("--root", str(tree))
    assert proc.returncode == 1
    assert "no sha256 hash" in proc.stdout


def test_legitimate_patterns_pass(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        "jobs:\n  x:\n    steps:\n"
        "      - run: pip install --require-hashes -r requirements-ci.lock\n"
        "      - run: pip install -e \".[dev]\" -c /tmp/constraints.txt\n"
        "      - run: python -m pip install --upgrade pip\n"
        "      - run: pip install -e .\n"
        "      # hash-exempt: verbatim README contract\n"
        "      - run: pip install -e \".[dev]\"\n"
        "      # pinned: dispatch-only tooling\n"
        "      - run: pip install inspect-ai==0.3.248\n",
        {"requirements-ci.lock": _GOOD_LOCK,
         "requirements-release.lock": _GOOD_LOCK},
    )
    proc = _run("--root", str(tree))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_pinned_but_unmarked_direct_install_fails(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        "jobs:\n  x:\n    steps:\n      - run: pip install pymupdf==1.28.0\n",
        {"requirements-ci.lock": _GOOD_LOCK,
         "requirements-release.lock": _GOOD_LOCK},
    )
    proc = _run("--root", str(tree))
    assert proc.returncode == 1
    assert "unmarked" in proc.stdout
