# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the NEGATIVE_RESULTS.md status gate.

The document is the project's honesty surface, and its credibility depends on a
reader being able to tell a live bug from a falsified hypothesis. Before
2026-07-31 they could not: §21 still read "active highest-priority gap" after
§§22-35 resolved it. These tests pin both halves — that the live document is
consistent, and that the gate still refuses each way it can go wrong.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_negative_results_status.py"


def _load():
    spec = importlib.util.spec_from_file_location("cnrs", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_live_document_is_consistent() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT
    )
    assert proc.returncode == 0, proc.stderr


def test_every_section_carries_a_status() -> None:
    mod = _load()
    lines = mod.DOC.read_text(encoding="utf-8").splitlines()
    statuses, errors = mod.parse_sections(lines)
    assert errors == [], errors
    # 35 numbered sections, none unmarked.
    assert len(statuses) == 36
    assert set(statuses.values()) <= set(mod.VALID)


def test_the_falsified_hypotheses_are_accepted_not_open() -> None:
    # The whole point of the taxonomy: §18 (temperature) and §19 (AgentHarm
    # FBR) must never read as open bugs inviting a threshold change.
    mod = _load()
    statuses, _ = mod.parse_sections(mod.DOC.read_text(encoding="utf-8").splitlines())
    for section in (18, 19, 20, 29):
        assert statuses[section] == "accepted", section


def test_the_resolved_routing_findings_are_superseded() -> None:
    mod = _load()
    statuses, _ = mod.parse_sections(mod.DOC.read_text(encoding="utf-8").splitlines())
    for section in (21, 22, 26, 32):
        assert statuses[section] == "superseded", section


def test_a_missing_marker_is_caught() -> None:
    mod = _load()
    errors = mod.parse_sections(["## §7 A finding with no marker", "Body text."])[1]
    assert len(errors) == 1 and "no <!-- finding-status" in errors[0]


def test_an_invalid_status_is_caught() -> None:
    mod = _load()
    errors = mod.parse_sections(
        ["## §7 A finding", "<!-- finding-status: maybe -->"]
    )[1]
    assert len(errors) == 1 and "expected one of" in errors[0]


def test_summary_group_disagreeing_with_a_section_is_caught() -> None:
    mod = _load()
    text = (
        '### Accepted negative results — do not "fix" these\n'
        "| A finding (§7) | why | High |\n"
    )
    errors = mod.check_summary_groups(text, {7: "open"})
    drift = [e for e in errors if "§7" in e and "one of them is stale" in e]
    assert len(drift) == 1


def test_resolved_by_column_is_not_read_as_a_status_claim() -> None:
    # "Coverage loss (§32) | resolved by §35" must not assert that §35 is
    # itself superseded — only the first cell identifies the finding.
    mod = _load()
    text = (
        "### Superseded — resolved by a later section, kept for the causal chain\n"
        "| Coverage loss (§32) | §35 | outcome |\n"
    )
    errors = mod.check_summary_groups(text, {32: "superseded", 35: "open"})
    assert [e for e in errors if "§35" in e] == []


def test_an_open_section_with_no_backlog_theme_is_caught() -> None:
    mod = _load()
    text = "<!-- backlog-start -->\n1. **A theme** (§34) — text.\n<!-- backlog-end -->"
    errors = mod.check_backlog(text, {34: "open", 33: "open"})
    assert len(errors) == 1 and "§33" in errors[0]


def test_a_backlog_theme_citing_a_closed_section_is_caught() -> None:
    mod = _load()
    text = "<!-- backlog-start -->\n1. **A theme** (§18) — text.\n<!-- backlog-end -->"
    errors = mod.check_backlog(text, {18: "accepted"})
    assert len(errors) == 1 and "not 'open'" in errors[0]


def test_backlog_prose_may_cite_a_closed_section_for_context() -> None:
    # Theme 5 legitimately says "not a route to reviving temperature (§18)".
    mod = _load()
    text = (
        "<!-- backlog-start -->\n"
        "1. **NLI parity** (§3) — explicitly not a way to revive §18.\n"
        "<!-- backlog-end -->"
    )
    assert mod.check_backlog(text, {3: "open"}) == []


def test_declared_counts_must_match_the_markers() -> None:
    mod = _load()
    text = "Counts: **9 `open`**, **4 `accepted`**, **20 `superseded`**."
    errors = mod.check_counts(text, {1: "open", 2: "accepted"})
    assert any("declares 9 'open'" in e for e in errors)
