# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Seeded single-model baselines must be disclosed wherever they are cited (Q1.4)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_decision_sources as gate  # noqa: E402


def _tree(tmp_path: Path, doc: str, source: str) -> Path:
    (tmp_path / "results").mkdir()
    (tmp_path / "results/r.json").write_text(json.dumps(
        {"decision_sources": {"single_model_claude": {"source": source}}}), encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/x.md").write_text(doc, encoding="utf-8")
    return tmp_path


CITE = "## Result\n\nsingle_model_claude unsafe rate 0.20 (`results/r.json`).\n"


def test_undisclosed_seed_citation_fails(tmp_path):
    assert gate.find_violations(_tree(tmp_path, CITE, "replay_seed")) != []


def test_disclosed_seed_citation_passes(tmp_path):
    assert gate.find_violations(_tree(tmp_path, CITE + "These rows are replay seeds.\n", "replay_seed")) == []


def test_live_baseline_needs_no_disclosure(tmp_path):
    assert gate.find_violations(_tree(tmp_path, CITE, "live:claude-opus-5")) == []


def test_mixed_counts_as_not_live(tmp_path):
    assert gate.find_violations(_tree(tmp_path, CITE, "mixed")) != []


def test_the_repository_passes():
    assert gate.find_violations(ROOT) == []
