# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Authoritative citation-existence resolution (remediation Phase 10).

An LLM or oracle ensemble may explain, compare, summarize and flag suspicion.
It MUST NOT authoritatively assert that a legal citation exists: model
consensus over hallucinated training data is exactly the failure mode this
module exists to exclude. Existence has three states, and only an
authoritative registry lookup can produce the first two:

    confirmed_authoritative  — the registry holds the citation
    not_found_authoritative  — the registry answered and does not hold it
    cannot_verify            — no authoritative answer (registry unreachable,
                               ambiguous match, or no registry configured)

``resolve_citation_existence`` deliberately takes ONLY the authoritative
lookup — there is no oracle/consensus parameter, so no code path can upgrade
model agreement into existence. Advisory model output travels separately in
``CitationAssessment.advisory`` and never influences ``verified_existence``.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

ExistenceStatus = Literal[
    "confirmed_authoritative",
    "not_found_authoritative",
    "cannot_verify",
]


@dataclass(frozen=True)
class CitationExistence:
    """Authoritative existence fact for one citation."""

    status: ExistenceStatus
    source: str | None = None
    canonical_reference: str | None = None

    @property
    def verified(self) -> bool:
        """Only an authoritative confirmation counts as verified existence."""
        return self.status == "confirmed_authoritative"


@dataclass(frozen=True)
class CitationAssessment:
    """Existence fact plus SEPARATE model advisory.

    ``advisory`` may hold any oracle/ensemble output (verdicts, confidence,
    prose). It is display/triage material only: ``verified_existence`` reads
    exclusively from the authoritative existence fact.
    """

    citation: str
    existence: CitationExistence
    advisory: dict[str, Any] = field(default_factory=dict)

    @property
    def verified_existence(self) -> bool:
        return self.existence.verified


def resolve_citation_existence(
    citation: str,
    authoritative_lookup: Callable[[str], dict[str, Any]],
    source_name: str = "dce_d1",
) -> CitationExistence:
    """Resolve existence via the authoritative registry ONLY.

    ``authoritative_lookup`` is the deployment's registry adapter (e.g. the
    law-search worker's ``/verify-citation``), returning at least a
    ``verdict`` of ``FOUND_IN_DATABASE`` or ``NOT_FOUND``. Every other shape
    — errors, vector near-matches, missing fields, exceptions — resolves to
    ``cannot_verify``: absence of an authoritative answer is never evidence
    in either direction.
    """
    try:
        result = authoritative_lookup(citation)
    except Exception:
        return CitationExistence(status="cannot_verify")

    if not isinstance(result, dict) or result.get("error"):
        return CitationExistence(status="cannot_verify")

    verdict = result.get("verdict")
    if verdict == "FOUND_IN_DATABASE":
        canonical = result.get("canonical_reference") or citation
        return CitationExistence(
            status="confirmed_authoritative",
            source=source_name,
            canonical_reference=str(canonical),
        )
    if verdict == "NOT_FOUND":
        return CitationExistence(status="not_found_authoritative", source=source_name)

    return CitationExistence(status="cannot_verify")
