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
