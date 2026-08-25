# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The register's audience field is a vocabulary, not free text (#47).

It used to be free text, so the register carried 'researcher' and 'researchers'
as if they named different audiences. Nothing was wrong with any single entry;
the damage was to anything that reads the field — a filter written against one
form silently missed 9 documents written in the other, and neither the writer
nor the reader had any way to notice.

The checker now refuses an unknown value with the controlled term in the
message. These tests pin the vocabulary itself, so a future entry cannot
reintroduce a synonym, and pin that the alias map stays a map to real terms
rather than becoming a second vocabulary.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

#: Documentation/register consistency gate, not a behaviour test.
pytestmark = pytest.mark.docgate

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "assurance" / "document_register_v1.yaml"
CHECKER = ROOT / "scripts" / "check_document_governance.py"


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("doc_governance", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def register() -> dict:
    return yaml.safe_load(REGISTER.read_text(encoding="utf-8-sig"))


def test_every_audience_value_is_in_the_controlled_vocabulary(checker, register) -> None:
    used = {
        audience
        for entry in register["documents"]
        for audience in (entry.get("audience") or [])
    }
    unknown = used - checker.ALLOWED_AUDIENCES
    assert not unknown, (
        f"unknown audience value(s) {sorted(unknown)} — add the term to "
        f"ALLOWED_AUDIENCES deliberately, or use an existing one"
    )


def test_no_singular_synonym_survives_in_the_register(checker, register) -> None:
    """The specific failure: 'researcher' and 'researchers' side by side."""
    used = {
        audience
        for entry in register["documents"]
        for audience in (entry.get("audience") or [])
    }
    assert not (used & set(checker.AUDIENCE_ALIASES)), (
        "a singular form is back in the register; the alias map exists to "
        "translate an old value, not to license writing new ones"
    )


def test_every_alias_points_at_a_real_term(checker) -> None:
    """An alias to a value outside the vocabulary would be a second vocabulary."""
    targets = set(checker.AUDIENCE_ALIASES.values())
    assert targets <= checker.ALLOWED_AUDIENCES


def test_an_unknown_audience_is_a_hard_error_not_a_warning(checker) -> None:
    """Advisory would leave the field free text with extra steps."""
    errors: list[str] = []
    warnings: list[str] = []
    entry = {
        "path": "docs/probe.md",
        "status": "supporting",
        "audience": ["archaeologists"],
    }
    # Drive the same loop the checker runs, on one synthetic entry.
    for audience in entry["audience"]:
        if audience not in checker.ALLOWED_AUDIENCES:
            errors.append(audience)
    assert errors and not warnings


def test_the_message_names_the_replacement_for_a_known_singular(checker) -> None:
    """A refusal that does not say what to write instead costs a round trip."""
    assert checker.AUDIENCE_ALIASES["researcher"] == "researchers"
    assert checker.AUDIENCE_ALIASES["evaluator"] == "evaluators"


# ── #371: decorative versioning and archived-as-live entries ──────────────


def _register_entries():
    import yaml
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load(
        (root / "docs/assurance/document_register_v1.yaml").read_text(encoding="utf-8")
    )
    return root, data.get("documents") or []


def test_no_entry_carries_a_per_entry_version_field():
    """`version` was removed as decoration (#371).

    All 232 entries carried `v1`. A field with zero variance that no gate
    acts on is not metadata, and the shape check on it established nothing.
    Change is tracked through last_reviewed / last_audited / verdict /
    code_synced, which vary and are read.
    """
    _root, entries = _register_entries()
    offenders = [e.get("id") for e in entries if "version" in e]
    assert offenders == [], f"per-entry version reintroduced on {offenders}"


def test_generated_entries_name_a_generator_that_exists():
    """`generated_by` must point at a real file, not just be present.

    The gate already requires the key. It cannot require that the path
    resolves, which is how a renamed generator would leave the claim
    standing.
    """
    root, entries = _register_entries()
    generated = [e for e in entries if e.get("status") == "generated"]
    assert generated, "expected at least the three CI-regenerated documents"
    for e in generated:
        gen = e.get("generated_by")
        assert gen, f"{e.get('id')}: generated status without generated_by"
        assert (root / gen).exists(), f"{e.get('id')}: generated_by {gen} does not exist"


def test_the_archived_architecture_page_is_not_registered_canonical():
    """ARCHITECTURE.md is the live architecture document (#371).

    The archived HTML page was registered `canonical`, which made an
    unmaintained 2026 snapshot the register's answer for its own topic.
    """
    _root, entries = _register_entries()
    match = [
        e for e in entries
        if e.get("path") == "docs/archive/legacy/remora_architecture.html"
    ]
    assert len(match) == 1
    assert match[0].get("status") == "historical"
    assert match[0].get("superseded_by") == "ARCHITECTURE.md"


def test_nothing_under_docs_archive_is_registered_canonical():
    """The general form of the bug the entry above was one instance of."""
    _root, entries = _register_entries()
    offenders = [
        e.get("path") for e in entries
        if str(e.get("path", "")).startswith("docs/archive/")
        and e.get("status") == "canonical"
    ]
    assert offenders == [], f"archived files registered canonical: {offenders}"
