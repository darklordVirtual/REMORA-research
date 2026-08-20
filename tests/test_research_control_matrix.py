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

import pytest

#: Documentation/register consistency gate, not a behaviour test.
#: Split out so a documentation drift and a governance regression do
#: not fail the same way (self-review 2026-08-20).
pytestmark = pytest.mark.docgate

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


def test_res003_does_not_claim_crc_implementation() -> None:
    """External review 2026-08-05: crc.py states 'CRC-inspired, NOT a CRC
    procedure' (no finite-sample term, non-monotone loss, hand-tuned
    weights). The matrix must not claim the CRC guarantee as implemented."""
    entry = next(e for e in _data()["entries"] if e["id"] == "RES-003")
    assert entry["maturity"] == "empirically_evaluated_adaptation", entry["maturity"]
    assert "finite_sample_risk_control" not in entry["concepts"]
    assert "CRC-inspired" in entry["title"]


def test_res008_is_a_conceptual_translation_not_the_architecture() -> None:
    """External review 2026-08-05: REMORA implements a governance translation
    of Nested Learning, not the Hope architecture. The maturity label must
    say so."""
    entry = next(e for e in _data()["entries"] if e["id"] == "RES-008")
    assert entry["maturity"] == "conceptual_translation_implemented", entry["maturity"]


def test_res001_scope_names_deterministic_psn_operationalisation() -> None:
    """External review 2026-08-05: the code computes binary per-instance
    PS/PN indicators, not population-level probabilities; the scope boundary
    must carry that distinction."""
    entry = next(e for e in _data()["entries"] if e["id"] == "RES-001")
    assert "Deterministic" in entry["scope_boundary"]
    assert "binary" in entry["scope_boundary"].lower()


# ── Bibliography reconciliation (added 2026-08-07) ──────────────────────────
# The matrix maps 10 implemented research lines while the paper cites 64 works.
# Review asked the obvious question: where are the rest used? These tests bind
# the answer so it cannot rot into an unexplained gap again.


def _bib() -> dict:
    return _data()["bibliography"]


def test_every_paper_reference_has_a_declared_role() -> None:
    mod = _load_module()
    paper = ROOT / _bib().get("paper", "paper/remora_paper.md")
    refs = mod._paper_references(paper)
    assert len(refs) >= 60, f"only {len(refs)} references parsed — parser broke"
    declared = {(w["surname"], str(w["year"])) for w in _bib()["works"]}
    missing = sorted(set(refs) - declared)
    assert not missing, (
        "paper references with no declared role in the control matrix: "
        f"{missing}"
    )


def test_no_stale_declared_works() -> None:
    """A work removed from the paper must not linger in the reconciliation."""
    mod = _load_module()
    paper = ROOT / _bib().get("paper", "paper/remora_paper.md")
    refs = set(mod._paper_references(paper))
    stale = sorted({(w["surname"], str(w["year"])) for w in _bib()["works"]} - refs)
    assert not stale, f"declared works absent from the paper: {stale}"


def test_roles_are_from_the_vocabulary() -> None:
    mod = _load_module()
    bad = [(w["surname"], w.get("role")) for w in _bib()["works"]
           if w.get("role") not in mod.BIBLIOGRAPHY_ROLES]
    assert not bad, f"works with an unknown role: {bad}"


def test_code_claiming_roles_name_an_existing_anchored_file() -> None:
    """A role that claims codebase presence must be verifiable: the file exists
    and actually mentions the source. This is what stops the reconciliation
    from becoming a list of assertions nobody checks."""
    offenders: list[str] = []
    for w in _bib()["works"]:
        for path in w.get("code") or []:
            p = ROOT / path
            anchor = w.get("anchor", w["surname"])
            if not p.exists():
                offenders.append(f"{w['surname']}: missing file {path}")
            elif anchor not in p.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(f"{w['surname']}: {anchor!r} absent from {path}")
    assert not offenders, "\n".join(offenders)


def test_positioning_only_claims_no_code() -> None:
    """positioning_only asserts the source is NOT in the codebase; naming code
    would contradict the role."""
    bad = [w["surname"] for w in _bib()["works"]
           if w.get("role") == "positioning_only" and w.get("code")]
    assert not bad, f"positioning_only works naming code: {bad}"


def test_implemented_line_points_at_a_real_entry() -> None:
    ids = {e["id"] for e in _data()["entries"]}
    bad = [(w["surname"], w.get("entry")) for w in _bib()["works"]
           if w.get("role") == "implemented_line" and w.get("entry") not in ids]
    assert not bad, f"implemented_line works naming an unknown entry: {bad}"


def test_code_only_works_are_locatable() -> None:
    """Sources absent from the paper must still be findable: a module that
    cites them, or the research line whose narrative attribution carries them."""
    ids = {e["id"] for e in _data()["entries"]}
    offenders: list[str] = []
    for w in _bib().get("code_only") or []:
        code, entry = w.get("code") or [], w.get("entry")
        if not code and not entry:
            offenders.append(f"{w['surname']}: neither code nor entry")
        if entry and entry not in ids:
            offenders.append(f"{w['surname']}: unknown entry {entry}")
        for path in code:
            p = ROOT / path
            anchor = w.get("anchor", w["surname"])
            if not p.exists() or anchor not in p.read_text(
                    encoding="utf-8", errors="ignore"):
                offenders.append(f"{w['surname']}: {anchor!r} not in {path}")
    assert not offenders, "\n".join(offenders)


def test_generated_view_renders_the_reconciliation() -> None:
    text = GENERATED.read_text(encoding="utf-8")
    assert "## Bibliography reconciliation" in text
    assert "### Cited in code but not in the paper" in text


# ── Unambiguous source identity (added 2026-08-07) ──────────────────────────
# Surname+year cannot separate two works by one author: an audit of the
# reconciliation could not tell Angelopoulos 2021 from 2022, nor the three
# distinct Wang publications, so every surname-based check was ambiguous.
# A stable id is the unambiguous key; a declared arXiv/DOI/ISBN is a factual
# claim and is therefore only accepted when the paper's own reference line
# already carries it.


def _all_bib_works() -> list[dict]:
    b = _bib()
    return list(b["works"]) + list(b.get("code_only") or [])


def test_every_work_has_a_unique_wellformed_id() -> None:
    mod = _load_module()
    works = _all_bib_works()
    ids = [w.get("id") for w in works]
    assert all(ids), [w["surname"] for w in works if not w.get("id")]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate source ids: {dupes}"
    bad = [i for i in ids if not mod._ID_RE.match(str(i))]
    assert not bad, f"ids must be lowercase-hyphenated ASCII: {bad}"


def test_declared_identifiers_are_corroborated_by_the_paper() -> None:
    """An arXiv/DOI/ISBN in the matrix must appear in the paper's reference
    line. This is what makes an identifier unfabricatable."""
    mod = _load_module()
    bib = _bib()
    lines = mod._paper_reference_lines(ROOT / bib["paper"])
    offenders: list[str] = []
    for w in bib["works"]:
        ref = lines.get((w["surname"], str(w["year"])), "")
        for field in mod.IDENTIFIER_FIELDS:
            val = w.get(field)
            if val and str(val) not in ref:
                offenders.append(f"{w['id']}: {field}={val} absent from paper")
    assert not offenders, "\n".join(offenders)


def test_fabricated_identifier_is_rejected() -> None:
    """The guard must actually fire — a plausible but invented arXiv id has to
    fail validation, otherwise the corroboration rule is decorative."""
    mod = _load_module()
    data = _data()
    target = next(w for w in data["bibliography"]["works"] if w.get("arxiv"))
    target["arxiv"] = "2499.99999"  # plausible shape, not in the paper
    errors = mod.validate(data)
    assert any("2499.99999" in e for e in errors), (
        "a fabricated arXiv id passed validation: the corroboration rule is "
        "not enforcing anything"
    )


def test_missing_id_is_rejected() -> None:
    mod = _load_module()
    data = _data()
    data["bibliography"]["works"][0].pop("id", None)
    assert any("missing id" in e for e in mod.validate(data))
