# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Research-control matrix integrity.

The matrix is the machine-checked research -> code -> test chain. Its value is
that it cannot drift: every referenced path must exist, the rendered view must
be current, and the registered lines must cover the numbered sections of
docs/09-related-work.md.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "research" / "research_control_matrix_v1.yaml"
GENERATED = ROOT / "docs" / "research" / "research_control_matrix.generated.md"
SCRIPT = ROOT / "scripts" / "generate_research_control_matrix.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("gen_rcm", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _data() -> dict:
    with open(REGISTER, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_register_parses_and_validates() -> None:
    mod = _load_module()
    errors = mod.validate(_data())
    assert errors == [], errors


def test_every_code_and_test_path_exists() -> None:
    data = _data()
    for e in data["entries"]:
        for path in list(e.get("code", []) or []) + list(e.get("tests", []) or []):
            assert (ROOT / path).exists(), f"{e['id']}: missing {path}"


def test_generated_view_is_up_to_date() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr


def test_implemented_lines_have_tests() -> None:
    """Anything claimed implemented_and_tested must actually cite tests."""
    for e in _data()["entries"]:
        if e["maturity"] == "implemented_and_tested":
            assert e.get("tests"), f"{e['id']} is implemented_and_tested but lists no tests"


def test_in_code_citations_are_present_in_the_cited_code() -> None:
    """Every entry that claims an in-code citation must have its anchor
    (author/arXiv id) verbatim in one of its code files — the mapping is exact,
    not merely plausible."""
    for e in _data()["entries"]:
        if not e.get("in_code_citation"):
            continue
        anchor = e.get("citation_anchor")
        assert anchor, f"{e['id']}: in_code_citation without citation_anchor"
        hit = any(
            (ROOT / p).exists() and anchor in (ROOT / p).read_text(encoding="utf-8", errors="ignore")
            for p in e["code"]
        )
        assert hit, f"{e['id']}: anchor {anchor!r} not found in {e['code']}"


def test_anchor_drift_is_rejected() -> None:
    """The validator must FAIL when a citation anchor is not in the code —
    a citation-binding gate that cannot fail would be decoration."""
    mod = _load_module()
    data = _data()
    # Corrupt the first in-code-cited entry's anchor to something absent.
    for e in data["entries"]:
        if e.get("in_code_citation"):
            e["citation_anchor"] = "NoSuchAuthorXYZ"
            break
    errors = mod.validate(data)
    assert any("not found in any code file" in err for err in errors), errors


def test_no_named_paper_line_claims_in_code_citation() -> None:
    """Idea-family lines must not silently claim an in-code citation."""
    for e in _data()["entries"]:
        if not e.get("in_code_citation"):
            assert "citation_anchor" not in e, f"{e['id']}: idea-family line must not set citation_anchor"


def test_compendium_refs_are_wellformed() -> None:
    """Every compendium ref (per-line + landscape) must be a lowercase-hyphen id;
    the landscape scope-boundary entries must carry theme/chapter/reason."""
    mod = _load_module()
    data = _data()
    for e in data["entries"]:
        refs = e.get("compendium_refs")
        assert refs is None or isinstance(refs, list), e["id"]
        for r in refs or []:
            assert mod._REF_RE.fullmatch(r), f"{e['id']}: malformed ref {r!r}"
    for area in (data.get("landscape") or {}).get("not_implemented", []):
        for field in ("theme", "compendium_chapter", "reason"):
            assert area.get(field), f"landscape area missing {field}"


def test_malformed_compendium_ref_is_rejected() -> None:
    """The crosswalk validator must refuse a malformed ref id — pattern check
    runs with or without the local compendium."""
    mod = _load_module()
    data = _data()
    data["entries"][0].setdefault("compendium_refs", []).append("Bad_ID")
    assert any("malformed" in e for e in mod.validate(data))


def test_compendium_ref_drift_is_rejected_when_landscape_present() -> None:
    """When the local compendium is present, a ref that is not in it must fail —
    the crosswalk cannot drift from the landscape. Skipped in CI where the
    gitignored compendium is absent (the check is a local drift-guard)."""
    import pytest

    mod = _load_module()
    if not mod.COMPENDIUM.exists():
        pytest.skip("local compendium absent (expected in CI)")
    data = _data()
    data["entries"][0].setdefault("compendium_refs", []).append("no-such-work-9999")
    assert any("no-such-work-9999" in e and "drifted" in e for e in mod.validate(data))


def test_covers_related_work_sections() -> None:
    """One matrix entry per numbered section of the related-work doc."""
    related = (ROOT / "docs" / "09-related-work.md").read_text(encoding="utf-8")
    section_nums = set(re.findall(r"^## (\d+)\.", related, flags=re.MULTILINE))
    cited = set()
    for e in _data()["entries"]:
        m = re.search(r"§(\d+)", e["related_work_section"])
        if m:
            cited.add(m.group(1))
    assert section_nums <= cited, f"related-work sections not in matrix: {section_nums - cited}"
