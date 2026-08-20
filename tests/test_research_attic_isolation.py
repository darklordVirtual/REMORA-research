# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The research attic stays outside every production path.

remora/research_attic/ holds retained research modules with no runtime role.
This test pins the contract from the attic's __init__ docstring: nothing under
remora/ (outside the attic itself), servers/, or scripts/ may import an attic
module — the only exceptions are scripts/check_readme_claims.py (it proves
README claims still import) and the demo script for an attic module. A new production importer must instead
move the module OUT of the attic with a capability-register entry.
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
ATTIC = ROOT / "remora" / "research_attic"
ALLOWED = {
    ROOT / "scripts" / "check_readme_claims.py",
    ROOT / "scripts" / "demo_future_concept.py",  # demo OF an attic module
}

_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+remora\.research_attic\b", re.MULTILINE
)


def _py_files(base: Path):
    for path in base.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def test_attic_modules_exist() -> None:
    assert (ATTIC / "__init__.py").exists()
    assert (ATTIC / "statphys" / "potts.py").exists()


def test_no_production_code_imports_the_attic() -> None:
    offenders: list[str] = []
    for base in (ROOT / "remora", ROOT / "servers", ROOT / "scripts"):
        for path in _py_files(base):
            if ATTIC in path.parents or path in ALLOWED:
                continue
            if _IMPORT_RE.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], (
        "production code imports remora.research_attic — move the module out "
        f"of the attic instead: {offenders}"
    )


def test_no_stale_imports_of_moved_modules() -> None:
    """The old top-level names must not creep back in anywhere."""
    moved = r"remora\.(codegraph|zkp|gaa|correlation_error|future_concept|statphys|theory|proofs)\b"
    stale_re = re.compile(rf"^\s*(?:from|import)\s+{moved}", re.MULTILINE)
    offenders: list[str] = []
    for base in (ROOT / "remora", ROOT / "servers", ROOT / "scripts",
                 ROOT / "tests", ROOT / "experiments"):
        for path in _py_files(base):
            if ATTIC in path.parents:
                continue
            if stale_re.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"stale pre-attic import paths: {offenders}"
