# SPDX-License-Identifier: BUSL-1.1
"""Evidence admission: derive which premises are established, and why.

``admit_evidence`` joins typed evidence records against deployment-owned
trust material and returns an :class:`EvidenceAdmission` — a report, not a
verdict input. It derives the premises the frozen conformance checkers take
as trusted booleans (source accepted, scope accepted, coverage complete, same
protected operation, ...) from evidence, or records that they are not
established.

The layer is fail-closed: anything not positively established is reported as
not established, with a reason code. It never touches authority: no import of
``remora.enforcement``, ``remora.execution`` or ``remora.policy`` exists in
this package, and a test keeps it that way.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from remora.evidence.admission.models import (
    CoverageAttestation,
    CoverageState,
    EstablishmentStatus,
    InvocationBindingProof,
    ManifestTrust,
    ObservationVantage,
    PriorCommitment,
    ProcessingStatus,
    ProducerCapabilityManifest,
    VantageIndependence,
)

#: Derived fact names, in the vocabulary of the conformance premises they
#: substantiate. The mapping from these names to checker premise keys is a
#: consumer decision; the admission layer does not write checker inputs.
FACT_NAMES: tuple[str, ...] = (
    "source_accepted",
    "scope_accepted",
    "producer_visibility_established",
    "observation_coverage_complete",
    "effect_observation_accepted",
    "same_protected_operation",
    "vantage_independent",
    "invocation_binding_established",
    "prior_commitment_established",
)


@dataclass(frozen=True)
class TrustConfig:
    """Deployment-owned trust material. Never read from the evidence itself.

    ``accepted_producers`` maps producer_id to the manifest digest the
    deployment has reviewed and accepted. A manifest whose digest is not in
    this map is DECLARED at best — a claim, not accepted capability.
    """

    accepted_producers: Mapping[str, str] = field(default_factory=dict)
    trusted_vantage_domains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "accepted_producers",
            MappingProxyType(dict(self.accepted_producers)),
        )


@dataclass(frozen=True)
class EvidenceAdmission:
    """The admission report: what was established, and for what scope."""

    processing: ProcessingStatus
    reason_codes: tuple[str, ...]
    established_facts: Mapping[str, EstablishmentStatus]
    evidence_digest: str
    scope: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "established_facts", MappingProxyType(dict(self.established_facts)),
        )
        object.__setattr__(self, "scope", MappingProxyType(dict(self.scope)))

    def is_established(self, fact: str) -> bool:
        return self.established_facts.get(fact) is EstablishmentStatus.ESTABLISHED

    def all_established(self, facts: tuple[str, ...]) -> bool:
        return all(self.is_established(f) for f in facts)


def _fail(processing: ProcessingStatus, reason: str) -> EvidenceAdmission:
    return EvidenceAdmission(
        processing=processing,
        reason_codes=(reason,),
        established_facts={},
        evidence_digest="",
        scope={},
    )


def admit_evidence(
    *,
    evidence_digest: str,
    manifest: ProducerCapabilityManifest | None,
    coverage: CoverageAttestation | None,
    vantage: ObservationVantage | None,
    binding: InvocationBindingProof | None,
    prior_commitment: PriorCommitment | None,
    trust: TrustConfig,
    expected_invocation: Mapping[str, Any],
    execution_started_at: int,
    evaluated_fields: tuple[str, ...],
    evaluated_interval: tuple[int, int],
    now: int,
) -> EvidenceAdmission:
    """Join evidence records against deployment-owned trust material.

    All inputs are typed records; nothing here parses raw bytes. Callers
    handling untrusted bytes must parse through ``canonical.decode_bounded``
    (or their own bounded parser) and construct the typed records first —
    construction failures are processing failures, not admissions.

    Returns an :class:`EvidenceAdmission`. When ``processing`` is not
    COMPLETED, no facts are established and ``established_facts`` is empty.
    """
    reasons: list[str] = []
    facts: dict[str, EstablishmentStatus] = {
        name: EstablishmentStatus.NOT_ESTABLISHED for name in FACT_NAMES
    }

    # ── Provenance: is this producer accepted for this manifest? ──────────
    manifest_accepted = False
    if manifest is None:
        reasons.append("evidence_source_unaccepted")
    elif manifest.trust is ManifestTrust.NOT_ESTABLISHED:
        reasons.append("producer_visibility_not_established")
    elif trust.accepted_producers.get(manifest.producer_id) != manifest.digest:
        # DECLARED or ACCEPTED in the manifest is the producer's label; the
        # deployment's map is the authority. A self-declared manifest whose
        # digest is not in the map stays a claim.
        reasons.append("producer_capability_self_declared")
    elif not manifest.valid_at(now):
        reasons.append("commitment_expired")
    else:
        manifest_accepted = True

    # ── Producer visibility: declared, accepted, and covering the fields ──
    if manifest_accepted and all(
        manifest.covers_field(f) for f in evaluated_fields
    ):
        facts["producer_visibility_established"] = EstablishmentStatus.ESTABLISHED
    elif manifest is not None and manifest_accepted:
        reasons.append("producer_visibility_not_established")

    if manifest_accepted:
        facts["source_accepted"] = EstablishmentStatus.ESTABLISHED

    # ── Coverage: explicit denominator, scoped to this invocation ─────────
    if coverage is not None and manifest_accepted:
        if coverage.producer_id != (manifest.producer_id if manifest else ""):
            reasons.append("coverage_scope_mismatch")
        elif coverage.invocation_id != expected_invocation.get("invocation_id", ""):
            reasons.append("coverage_scope_mismatch")
        elif coverage.state is CoverageState.UNKNOWN:
            reasons.append("coverage_unknown")
        elif coverage.state is CoverageState.INCOMPLETE:
            reasons.append("coverage_incomplete")
        elif not all(coverage.covers_field(f) for f in evaluated_fields):
            reasons.append("coverage_incomplete")
        elif not coverage.covers_interval(*evaluated_interval):
            reasons.append("coverage_incomplete")
        else:
            facts["observation_coverage_complete"] = (
                EstablishmentStatus.ESTABLISHED
            )
            facts["effect_observation_accepted"] = EstablishmentStatus.ESTABLISHED

    # ── Vantage: independence derived, never declared ─────────────────────
    if vantage is not None:
        independence = vantage.independence
        if independence is VantageIndependence.NOT_INDEPENDENT:
            reasons.append(
                "self_report_not_independent"
                if vantage.observer_id == vantage.observed_party
                else "observation_vantage_not_independent"
            )
        elif independence is VantageIndependence.NOT_ESTABLISHED:
            reasons.append("observation_vantage_not_established")
        elif (
            trust.trusted_vantage_domains
            and vantage.control_domain not in trust.trusted_vantage_domains
        ):
            reasons.append("observation_vantage_not_established")
        else:
            facts["vantage_independent"] = EstablishmentStatus.ESTABLISHED

    # ── Binding: every declared axis must match (CoSAI C5) ────────────────
    if binding is not None:
        if binding.matches(
            proposal_id=str(expected_invocation.get("proposal_id", "")),
            execution_id=str(expected_invocation.get("execution_id", "")),
            tool_call_hash=str(expected_invocation.get("tool_call_hash", "")),
            dispatch_id=str(expected_invocation.get("dispatch_id", "")),
            toolspec_hash=str(expected_invocation.get("toolspec_hash", "")),
            tenant=str(expected_invocation.get("tenant", "")),
            target=str(expected_invocation.get("target", "")),
            operation=str(expected_invocation.get("operation", "")),
            attempt=str(expected_invocation.get("attempt", "")),
        ):
            facts["invocation_binding_established"] = (
                EstablishmentStatus.ESTABLISHED
            )
            facts["scope_accepted"] = EstablishmentStatus.ESTABLISHED
            facts["same_protected_operation"] = EstablishmentStatus.ESTABLISHED
        else:
            if (
                binding.tool_call_hash
                != str(expected_invocation.get("tool_call_hash", ""))
            ):
                reasons.append("tool_call_hash_mismatch")
            else:
                reasons.append("binding_scope_mismatch")

    # ── Prior commitment: must predate the execution it evaluates ─────────
    if prior_commitment is not None:
        if not prior_commitment.binds_to(
            proposal_id=str(expected_invocation.get("proposal_id", "")),
            tool_call_hash=str(expected_invocation.get("tool_call_hash", "")),
            target=str(expected_invocation.get("target", "")),
            operation=str(expected_invocation.get("operation", "")),
        ):
            reasons.append("prior_commitment_scope_mismatch")
        elif not prior_commitment.predates(execution_started_at):
            reasons.append("prior_commitment_postdates_execution")
        elif not prior_commitment.valid_at(now):
            reasons.append("commitment_expired")
        else:
            facts["prior_commitment_established"] = EstablishmentStatus.ESTABLISHED

    return EvidenceAdmission(
        processing=ProcessingStatus.COMPLETED,
        reason_codes=tuple(dict.fromkeys(reasons)),
        established_facts=facts,
        evidence_digest=evidence_digest,
        scope=dict(expected_invocation),
    )
