# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for scripts/check_action_pins.py (supply-chain invariant)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("check_action_pins", ROOT / "scripts" / "check_action_pins.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


def _write(tmp: Path, body: str) -> Path:
    (tmp / "w.yml").write_text(body, encoding="utf-8")
    return tmp


def test_floating_tag_is_violation(tmp_path: Path) -> None:
    d = _write(tmp_path, "steps:\n  - uses: actions/checkout@v4\n")
    assert mod.find_violations(d) == ["w.yml:2: actions/checkout@v4"]


def test_branch_ref_is_violation(tmp_path: Path) -> None:
    d = _write(tmp_path, "steps:\n  - uses: foo/bar@main\n")
    assert len(mod.find_violations(d)) == 1


def test_full_sha_passes(tmp_path: Path) -> None:
    d = _write(tmp_path, "steps:\n  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v4\n")
    assert mod.find_violations(d) == []


def test_short_sha_is_violation(tmp_path: Path) -> None:
    d = _write(tmp_path, "steps:\n  - uses: actions/checkout@3d3c42e5\n")
    assert len(mod.find_violations(d)) == 1


def test_local_and_docker_exempt(tmp_path: Path) -> None:
    d = _write(tmp_path, "steps:\n  - uses: ./.github/actions/x\n  - uses: docker://alpine:3\n")
    assert mod.find_violations(d) == []


def test_repository_workflows_are_pinned() -> None:
    assert mod.find_violations(ROOT / ".github" / "workflows") == []
