# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Producer-side negative-evidence semantics for synthetic conformance fixtures.

This module extends the evidence-sufficiency research profile with one narrow
historical claim:

    no_delegation_in_window

It deliberately does not establish architectural non-bypassability.  The core
invariant is that a producer's declared capability is not equivalent to an
emission obligation, and neither is equivalent to complete bounded
observation.

The module consumes evidence/context only. Authored fixture expectations are
not accepted by this API.
"""
from __future__ import annotations

from typing import Any, Mapping

from checker import EvidenceStatus, EvidenceVerdict


PROPERTY_ID = "no_delegation_in_window"
REQUIRED_CAPABILITY = "read_delegation"

_REASON_GUIDANCE: dict[str, tuple[tuple[str, ...], str]] = {
    "scope_unaccepted_or_missing": (
        ("accepted bounded observation scope",),
        "bind the observation to the evaluated tenant, subject, interval and configuration",
    ),
    "direct_event_evidence_unaccepted": (
        ("accepted direct event evidence",),
        "establish provenance and admissibility for the observed delegation event",
    ),
    "event_presence_unknown": (
        ("decisive event presence/absence observation",),
        "determine whether delegation was observed in the bounded interval",
    ),
    "producer_declaration_unavailable": (
        ("producer capability declaration",),
        "supply the producer declaration applicable to the evaluated interval",
    ),
    "producer_capability_not_declared": (
        ("declared producer capability: read_delegation",),
        "establish that the producer was declared able to observe delegation",
    ),
    "effective_access_unestablished": (
        ("effective producer access",),
        "establish that the declared capability was effective for the evaluated source and interval",
    ),
    "emission_obligation_unestablished": (
        ("mandatory emission obligation",),
        "establish that a present delegation would have been emitted into this evidence stream",
    ),
    "collection_not_closed": (
        ("closed observation collection",),
        "close the bounded observation interval under the profile's finalization rule",
    ),
    "delivery_integrity_unestablished": (
        ("delivery integrity",),
        "establish that required emitted events reached the evaluated collection",
    ),
    "suppression_gap_unexcluded": (
        ("absence of relevant suppression gaps",),
        "exclude filtering, sampling or suppression gaps relevant to delegation evidence",
    ),
}


def _result(
    status: EvidenceStatus,
    reason: str,
    context: Mapping[str, Any],
) -> EvidenceVerdict:
    missing: tuple[str, ...] = ()
    decisive_if: str | None = None
    if status is EvidenceStatus.NOT_ESTABLISHED:
        missing, decisive_if = _REASON_GUIDANCE.get(reason, ((), None))
    return EvidenceVerdict(
        claim=PROPERTY_ID,
        status=status,
        reason=reason,
        scope=dict(context.get("scope", {})),
        missing_evidence=missing,
        decisive_if=decisive_if,
    )


def _unknown(reason: str, context: Mapping[str, Any]) -> EvidenceVerdict:
    return _result(EvidenceStatus.NOT_ESTABLISHED, reason, context)


def assess_producer_negative_evidence(
    property_id: str,
    observations: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    premise_source: str = "synthetic_fixture",
) -> EvidenceVerdict:
    """Assess one bounded producer-side absence claim.

    The supported claim is historical and narrow.  A direct, admissible
    delegation observation can refute it without global negative-evidence
    coverage.  Establishment from absence requires each producer-side premise:
    declared capability, effective access, mandatory emission, closed
    collection, delivery integrity and no relevant suppression gap.

    Production evidence admission is intentionally not implemented.
    """
    if premise_source != "synthetic_fixture":
        raise ValueError(
            "producer negative-evidence profile accepts only synthetic_fixture premises; "
            "production evidence admission is intentionally not implemented"
        )
    if property_id != PROPERTY_ID:
        raise ValueError(
            f"unsupported property {property_id!r}; this profile only evaluates {PROPERTY_ID!r}"
        )
    if not isinstance(observations, Mapping) or not isinstance(context, Mapping):
        raise ValueError("observations and context must be mappings")

    if context.get("scope_accepted") is not True:
        return _unknown("scope_unaccepted_or_missing", context)

    # Violation evidence is asymmetric: an accepted direct event witness can
    # refute the narrow absence claim without first proving global absence
    # coverage.
    if observations.get("delegation_observed") is True:
        if observations.get("delegation_evidence_accepted") is not True:
            return _unknown("direct_event_evidence_unaccepted", context)
        return _result(
            EvidenceStatus.VIOLATED,
            "accepted_delegation_observed_in_bounded_scope",
            context,
        )

    if observations.get("delegation_observed") is not False:
        return _unknown("event_presence_unknown", context)

    declaration_state = observations.get("declaration_state")
    if declaration_state == "UNAVAILABLE":
        return _unknown("producer_declaration_unavailable", context)
    if declaration_state != "PRESENT":
        raise ValueError("declaration_state must be PRESENT or UNAVAILABLE")

    if "declared_capabilities" not in observations:
        return _unknown("producer_capability_not_declared", context)
    capabilities = observations.get("declared_capabilities")
    if not isinstance(capabilities, list) or not all(isinstance(v, str) for v in capabilities):
        raise ValueError("declared_capabilities must be a list of strings when declaration is PRESENT")
    if REQUIRED_CAPABILITY not in capabilities:
        return _unknown("producer_capability_not_declared", context)

    if observations.get("effective_access") is not True:
        return _unknown("effective_access_unestablished", context)
    if observations.get("mandatory_emission") is not True:
        return _unknown("emission_obligation_unestablished", context)
    if observations.get("collection_closed") is not True:
        return _unknown("collection_not_closed", context)
    if observations.get("delivery_integrity") is not True:
        return _unknown("delivery_integrity_unestablished", context)
    if observations.get("suppression_gap_absent") is not True:
        return _unknown("suppression_gap_unexcluded", context)

    return _result(
        EvidenceStatus.ESTABLISHED,
        "absence_supported_by_bounded_producer_coverage",
        context,
    )
