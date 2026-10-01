# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Roadmap work-package identifiers are unique.

PR #580 added a second "## RF-12" to docs/13-research-frontier-roadmap.md;
the tenant-isolation package already held it, and nothing noticed. The
shelf, the research matrix and the remediation register all cite RF ids, so
a duplicate makes a citation ambiguous.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_rf_heading_is_unique() -> None:
    text = (ROOT / "docs/13-research-frontier-roadmap.md").read_text(encoding="utf-8")
    ids = re.findall(r"^## (RF-\d+)\b", text, re.M)
    assert ids, "no RF headings found"
    duplicates = sorted(i for i, n in Counter(ids).items() if n > 1)
    assert duplicates == [], f"duplicate work-package ids: {duplicates}"


def test_namespace_note_names_the_highest_id() -> None:
    text = (ROOT / "docs/13-research-frontier-roadmap.md").read_text(encoding="utf-8")
    highest = max(int(i) for i in re.findall(r"^## RF-(\d+)\b", text, re.M))
    assert f"RF-01…RF-{highest:02d}" in text
