# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""AROMER is a subproject, and the dependency runs one way only.

Issue #297 decided that ``remora/aromer/`` is a named subproject rather than
attic material: it is under active research, so it keeps its own version line
and its own claims, but it must stay off the decision path. The half that can
rot silently is the direction of the dependency, so it is pinned here.

AROMER may import the core. The core may never import AROMER. A new importer in
``remora/`` or ``servers/`` means the overlay has quietly become part of the
enforcing path, and the fix is a deliberate promotion — capability-register
entry, stated wiring status, claim discipline — not a wider allowlist.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

#: Documentation/register consistency gate, not a behaviour test.
pytestmark = pytest.mark.docgate

ROOT = Path(__file__).resolve().parent.parent
AROMER = ROOT / "remora" / "aromer"
CHARTER = ROOT / "docs" / "aromer" / "SUBPROJECT.md"

#: Scripts and tests may drive the subproject; the core may not depend on it.
_SEARCHED = (ROOT / "remora", ROOT / "servers")

_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+remora\.aromer\b", re.MULTILINE)


def _py_files(base: Path):
    for path in base.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def test_no_core_module_imports_aromer() -> None:
    offenders: list[str] = []
    for base in _SEARCHED:
        for path in _py_files(base):
            if AROMER in path.parents or path == AROMER / "__init__.py":
                continue
            if _IMPORT_RE.search(path.read_text(encoding="utf-8", errors="replace")):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], (
        "core code imports remora.aromer — the overlay would be on the decision "
        f"path. Promote it deliberately instead of widening this test: {offenders}"
    )


def test_aromer_carries_its_own_version() -> None:
    """A subproject with no version line is a directory, not a subproject."""
    from remora.aromer import AROMER_VERSION

    assert AROMER_VERSION.strip()
    import remora

    core_version = getattr(remora, "__version__", None)
    if core_version:
        assert AROMER_VERSION != core_version, (
            "AROMER's version must be independent of the core package version"
        )


def test_aromer_is_classified_experimental_in_the_truth_contract() -> None:
    """Not product surface: never a prerequisite for the canonical path."""
    import yaml

    contract = yaml.safe_load(
        (ROOT / "docs" / "product" / "product_truth_contract.yaml").read_text(
            encoding="utf-8"
        )
    )
    entry = next(c for c in contract["capabilities"] if c["name"] == "AROMER")
    assert entry["class"] == "experimental"


def test_the_charter_exists_and_states_the_one_way_rule() -> None:
    text = CHARTER.read_text(encoding="utf-8")
    assert "one-way dependency" in text.lower()
    assert "cascade" in text.lower(), (
        "the charter must record that remora/cascade/ was deliberately left open"
    )
