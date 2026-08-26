# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for scripts/check_prose_style.py (structural prose tells, shrink-only baseline)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("check_prose_style", ROOT / "scripts" / "check_prose_style.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


def test_emdash_counted_in_prose_only() -> None:
    text = "A prose line — with a dash.\n| table — cell |\n# heading — here\n```\ncode — here\n```\n"
    assert mod.scan_text(text)["emdash"] == 1


def test_arrow_in_sentence_counted_but_pipeline_notation_kept() -> None:
    assert mod.scan_text("The request → the gate refuses it.\n")["arrow"] == 1
    assert mod.scan_text("Agent → Proposal → Grant → PEP → Effect\n")["arrow"] == 0
    assert mod.scan_text("`a.py` → `b.py` → `c.py`\n")["arrow"] == 0


def test_bold_bullet_and_contrast() -> None:
    c = mod.scan_text("- **Scope:** narrow\n* plain bullet\nIt is not just fast, but correct.\n")
    assert c["bold_bullet"] == 1
    assert c["not_but"] == 1


def test_filler_and_participle_tail_and_copula() -> None:
    c = mod.scan_text(
        "It is worth noting that X. We did it in order to Y. Importantly, Z.\n"
        "The gate refuses it, ensuring safety.\nThe hash serves as a key.\n"
    )
    assert c["filler"] == 3
    assert c["ing_tail"] == 1
    assert c["copula_dodge"] == 1


def test_compare_is_shrink_only() -> None:
    base = {"a.md": {"emdash": 3}, "b.md": {"arrow": 1}}
    cur = {"a.md": {"emdash": 4}, "b.md": {}}
    reg, imp = mod.compare(cur, base)
    assert reg == ["a.md: emdash 3 -> 4"]
    assert imp == ["b.md: arrow 1 -> 0"]


def test_new_file_starts_at_zero() -> None:
    reg, _ = mod.compare({"new.md": {"emdash": 1}}, {})
    assert reg == ["new.md: emdash 0 -> 1"]


def test_repository_is_at_or_below_baseline() -> None:
    reg, _ = mod.compare(mod.scan_repo(), mod.load_baseline())
    assert reg == []
