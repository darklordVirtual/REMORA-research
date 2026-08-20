# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The Module Stability Index in ARCHITECTURE.md is machine-checked.

Section 9 claims to be the stability contract. On 2026-08-20 it listed two
directories that no longer existed (moved to `remora/research_attic/` the
previous day) and omitted `remora/sdk/` — the one surface with an external
backward-compatibility guarantee — entirely. A contract nobody verifies
drifts into fiction, and the doc-governance gate checks register bookkeeping,
not whether a documented path is real.
"""
from __future__ import annotations

import pytest

import re
from pathlib import Path

#: Documentation/register consistency gate, not a behaviour test.
#: Split out so a documentation drift and a governance regression do
#: not fail the same way (self-review 2026-08-20).
pytestmark = pytest.mark.docgate

ROOT = Path(__file__).resolve().parent.parent
ARCH = ROOT / "ARCHITECTURE.md"
VALID_RATINGS = {"STABLE", "CORE", "EXPERIMENTAL", "RESEARCH_ONLY", "HISTORICAL"}

#: Top-level entries under remora/ that need no row: private/dunder names and
#: the package marker itself.
_NOT_A_MODULE = {"__init__.py", "__pycache__", "py.typed", "README.md"}


def _index_rows() -> list[tuple[str, str]]:
    """(path, rating) for every row of the section 9 table."""
    text = ARCH.read_text(encoding="utf-8")
    start = text.index("## 9. Module Stability Index")
    section = text[start:]
    end = section.find("\n## ")
    if end != -1:
        section = section[:end]
    rows: list[tuple[str, str]] = []
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        rating = cells[1].strip("* ")
        for path in re.findall(r"`([^`]+)`", cells[0]):
            rows.append((path, rating))
    return rows


def test_the_table_parses() -> None:
    rows = _index_rows()
    assert len(rows) >= 20, f"only {len(rows)} rows parsed — did the format change?"


def test_every_listed_path_exists() -> None:
    missing = [p for p, _ in _index_rows() if not (ROOT / p).exists()]
    assert missing == [], (
        f"ARCHITECTURE.md section 9 lists paths that do not exist: {missing}"
    )


def test_every_rating_is_from_the_vocabulary() -> None:
    bad = {r for _, r in _index_rows() if r not in VALID_RATINGS}
    assert not bad, f"unknown stability ratings: {sorted(bad)}"


def test_every_top_level_module_is_classified() -> None:
    """A module nobody classified is a module nobody decided about."""
    listed = {p.rstrip("/") for p, _ in _index_rows()}
    unclassified: list[str] = []
    for entry in sorted((ROOT / "remora").iterdir()):
        if entry.name in _NOT_A_MODULE or entry.name.startswith("."):
            continue
        rel = f"remora/{entry.name}" + ("/" if entry.is_dir() else "")
        if rel.rstrip("/") in listed:
            continue
        # A row may cover a specific file inside the package instead.
        if any(p.startswith(rel.rstrip("/") + "/") for p in listed):
            continue
        unclassified.append(rel)
    assert unclassified == [], (
        "top-level modules missing from the Module Stability Index: "
        f"{unclassified}"
    )


def test_the_stable_surface_is_listed_as_stable() -> None:
    ratings = dict(_index_rows())
    assert ratings.get("remora/sdk/") == "STABLE", (
        "remora/sdk is the only surface with an external BC guarantee; the "
        "index must say so"
    )
