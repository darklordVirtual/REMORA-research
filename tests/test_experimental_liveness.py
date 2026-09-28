# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Every EXPERIMENTAL module is exercised by at least one test (quality program Q5.2).

A module rated EXPERIMENTAL in the Module Stability Index is research code,
but it still ships in the package. One nobody tests is one nobody would
notice breaking; it should be tested or retired, with the decision recorded
in ARCHITECTURE.md.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _experimental() -> list[str]:
    text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    section = text[text.index("## 9. Module Stability Index"):]
    end = section.find("\n## ", 5)
    section = section[:end] if end != -1 else section
    out = []
    for line in section.splitlines():
        if line.startswith("| `"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells[1].strip("* ") == "EXPERIMENTAL":
                out += [p.rstrip("/") for p in re.findall(r"`([^`]+)`", cells[0])]
    return out


def test_every_experimental_module_is_imported_by_a_test() -> None:
    sources = [p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "tests").rglob("*.py")]
    untested = []
    for path in _experimental():
        module = path.removesuffix(".py").replace("/", ".")
        pattern = re.compile(rf"(from|import)\s+{re.escape(module)}(\.|\s|$)", re.M)
        if not any(pattern.search(src) for src in sources):
            untested.append(path)
    assert untested == [], f"EXPERIMENTAL modules no test imports: {untested}"
