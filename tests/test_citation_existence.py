# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Phase 10: legal citation existence is an authoritative-registry fact.

Pins the contract that an LLM/oracle ensemble can never establish that a
citation exists — including the worst case where every model hallucinates
the same nonexistent citation with high confidence and full agreement.
"""
from __future__ import annotations

import pytest

from remora.legal import (
    CitationAssessment,
    CitationExistence,
    resolve_citation_existence,
)

FAKE_CITATION = "HR-2019-9999-A"  # nonexistent


def _lookup_found(citation: str) -> dict:
    return {"verdict": "FOUND_IN_DATABASE", "canonical_reference": citation}


def _lookup_not_found(_citation: str) -> dict:
    return {"verdict": "NOT_FOUND"}


def _lookup_unreachable(_citation: str) -> dict:
    return {"error": "HTTP 503: service unavailable"}


# The Phase 10 core scenario: unanimous, confident model hallucination.
UNANIMOUS_HALLUCINATION_ADVISORY = {
    "status": "NEEDS_CONTENT_CHECK",  # every oracle "confirmed" it
    "confidence": 0.99,
    "models_agreed": True,
    "oracle_claim": "The case clearly exists and established a famous rule.",
}


def test_authoritative_found_confirms() -> None:
    existence = resolve_citation_existence("HR-2016-01234-A", _lookup_found)
    assert existence.status == "confirmed_authoritative"
    assert existence.verified is True
    assert existence.canonical_reference == "HR-2016-01234-A"
    assert existence.source == "dce_d1"


def test_authoritative_not_found_is_not_found() -> None:
    existence = resolve_citation_existence(FAKE_CITATION, _lookup_not_found)
    assert existence.status == "not_found_authoritative"
    assert existence.verified is False


def test_unreachable_registry_is_cannot_verify() -> None:
    existence = resolve_citation_existence(FAKE_CITATION, _lookup_unreachable)
    assert existence.status == "cannot_verify"
    assert existence.verified is False


def test_lookup_exception_is_cannot_verify() -> None:
    def boom(_c: str) -> dict:
        raise ConnectionError("network down")

    assert resolve_citation_existence(FAKE_CITATION, boom).status == "cannot_verify"


@pytest.mark.parametrize(
    "weird", [None, [], "FOUND_IN_DATABASE", {"verdict": "VECTOR_MATCH"}, {}]
)
def test_non_authoritative_shapes_are_cannot_verify(weird) -> None:
    existence = resolve_citation_existence(FAKE_CITATION, lambda _c: weird)
    assert existence.status == "cannot_verify"


def test_unanimous_model_hallucination_never_verifies_existence() -> None:
    """All models hallucinate the same nonexistent citation, confidently and
    in agreement. Existence must NOT become verified."""
    for lookup in (_lookup_not_found, _lookup_unreachable):
        assessment = CitationAssessment(
            citation=FAKE_CITATION,
            existence=resolve_citation_existence(FAKE_CITATION, lookup),
            advisory=UNANIMOUS_HALLUCINATION_ADVISORY,
        )
        assert assessment.verified_existence is False
        # The advisory is preserved as a separate field — visible, never load-bearing.
        assert assessment.advisory["confidence"] == 0.99


def test_advisory_cannot_upgrade_existence_by_construction() -> None:
    """resolve_citation_existence takes no oracle input at all — assert the
    structural property so a future parameter addition is a conscious act."""
    import inspect

    params = list(inspect.signature(resolve_citation_existence).parameters)
    assert params == ["citation", "authoritative_lookup", "source_name"]


def test_verified_requires_exactly_confirmed_authoritative() -> None:
    for status in ("not_found_authoritative", "cannot_verify"):
        assert CitationExistence(status=status).verified is False
    assert CitationExistence(status="confirmed_authoritative").verified is True
