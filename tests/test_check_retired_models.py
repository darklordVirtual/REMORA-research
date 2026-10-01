# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The retired-model gate fails on the defaults it exists to stop."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_retired_models as gate  # noqa: E402


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


@pytest.mark.parametrize("identifier", [
    "claude-3-5-sonnet-latest",           # the #582 live-benchmark default
    "anthropic/claude-3.5-haiku",         # the #582 recommended-swarm default
    "claude-3-7-sonnet-20250219",
    "claude-3-haiku-20240307",
    "anthropic/claude-opus-4.1",
    "claude-2.1",
])
def test_a_retired_default_fails(tmp_path, identifier):
    root = _tree(tmp_path, {"experiments/run.py": f'MODEL = "{identifier}"\n'})
    violations = gate.find_violations(root)
    assert len(violations) == 1 and "experiments/run.py:1" in violations[0]


def test_current_models_pass(tmp_path):
    root = _tree(tmp_path, {"remora/x.py": 'M = ["claude-opus-5", "anthropic/claude-haiku-4.5", "claude-sonnet-5"]\n'})
    assert gate.find_violations(root) == []


def test_frozen_path_allows_only_its_named_identifier(tmp_path):
    root = _tree(tmp_path, {"remora/oracles/factory.py":
                            'A = "anthropic/claude-3.5-sonnet"\nB = "anthropic/claude-3.5-haiku"\n'})
    violations = gate.find_violations(root)
    assert violations == ["remora/oracles/factory.py:2: claude-3.5-haiku (Claude Haiku 3.5, retired 2026-02-19)"]


def test_history_outside_scanned_code_is_ignored(tmp_path):
    root = _tree(tmp_path, {"docs/history.md": "We ran claude-3-5-sonnet in 2025.\n",
                            "tests/test_x.py": 'FAMILY = "claude-3.5-haiku"\n'})
    assert gate.find_violations(root) == []


def test_the_repository_passes():
    assert gate.find_violations(ROOT) == []


def test_every_frozen_path_exists_and_still_needs_its_exemption():
    for rel, (allowed, reason) in gate.FROZEN.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert reason, rel
        assert any(a in text for a in allowed), f"{rel} no longer needs its FROZEN entry"
