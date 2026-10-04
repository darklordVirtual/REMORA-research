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

import hashlib
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Callable, Mapping

from remora.evidence.admission.canonical import canonical_digest, decode_bounded
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
from remora.evidence.admission.reasons import REASON_CODES

_EVIDENCE_RECORD_NAMES = frozenset({
    "manifest", "coverage", "vantage", "binding", "prior_commitment",
})


def _typed_evidence_digest(
    *,
    manifest: ProducerCapabilityManifest | None,
    coverage: CoverageAttestation | None,
    vantage: ObservationVantage | None,
    binding: InvocationBindingProof | None,
    prior_commitment: PriorCommitment | None,
) -> str:
    return canonical_digest({
        "manifest": manifest.digest if manifest is not None else None,
        "coverage": coverage.digest if coverage is not None else None,
        "vantage": (
            {
                "observer_id": vantage.observer_id,
                "observed_party": vantage.observed_party,
                "control_domain": vantage.control_domain,
                "observed_control_domain": vantage.observed_control_domain,
                "can_observed_party_forge": vantage.can_observed_party_forge,
                "can_observed_party_suppress": vantage.can_observed_party_suppress,
                "declared_independence": vantage.declared_independence,
                "provenance_ref": vantage.provenance_ref,
            }
            if vantage is not None else None
        ),
        "binding": (
            {
                "evidence_id": binding.evidence_id,
                "proposal_id": binding.proposal_id,
                "execution_id": binding.execution_id,
                "tool_call_hash": binding.tool_call_hash,
                "dispatch_id": binding.dispatch_id,
                "toolspec_hash": binding.toolspec_hash,
                "tenant": binding.tenant,
                "target": binding.target,
                "operation": binding.operation,
                "attempt": binding.attempt,
            }
            if binding is not None else None
        ),
        "prior_commitment": (
            prior_commitment.digest if prior_commitment is not None else None
        ),
    })

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

    ``accepted_producers`` and ``accepted_prior_commitments`` map identifiers
    to deployment-reviewed content digests. ``accepted_coverage`` maps a
    producer to the digests of the coverage attestations the deployment has
    accepted from it: an accepted producer's manifest says what it *could*
    see, and only an accepted attestation says what it *did* cover for one
    invocation. A statement whose digest is not in that set is a claim,
    whatever its content says. Vantage independence also requires membership
    in ``trusted_vantage_domains``.
    """

    accepted_producers: Mapping[str, str] = field(default_factory=dict)
    accepted_prior_commitments: Mapping[str, str] = field(default_factory=dict)
    trusted_vantage_domains: tuple[str, ...] = ()
    accepted_coverage: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "accepted_producers",
            MappingProxyType(dict(self.accepted_producers)),
        )
        object.__setattr__(
            self, "accepted_prior_commitments",
            MappingProxyType(dict(self.accepted_prior_commitments)),
        )
        object.__setattr__(
            self, "accepted_coverage",
            MappingProxyType({
                str(producer): tuple(str(d) for d in digests)
                for producer, digests in dict(self.accepted_coverage).items()
            }),
        )

    def accepts_coverage(self, producer_id: str, digest: str) -> bool:
        """True only when the deployment recorded this exact attestation."""
        return bool(digest) and digest in self.accepted_coverage.get(producer_id, ())


@dataclass(frozen=True)
class EvidenceAdmission:
    """The admission report: what was established, and for what scope."""

    processing: ProcessingStatus
    reason_codes: tuple[str, ...]
    established_facts: Mapping[str, EstablishmentStatus]
    evidence_digest: str
    scope: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.processing, ProcessingStatus):
            raise ValueError("processing must be a ProcessingStatus")
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


def processing_failure(
    processing: ProcessingStatus,
    reason: str,
) -> EvidenceAdmission:
    """Create a processing-only report for failures outside this package."""
    if not isinstance(processing, ProcessingStatus):
        raise ValueError("processing must be a ProcessingStatus")
    if processing is ProcessingStatus.COMPLETED:
        raise ValueError("processing failure cannot be COMPLETED")
    if reason not in REASON_CODES:
        raise ValueError("unknown evidence-admission reason code")
    return _fail(processing, reason)


def process_evidence_payload(
    raw: bytes,
    *,
    schema: str,
    parse: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    trust: TrustConfig,
    expected_invocation: Mapping[str, Any],
    execution_started_at: int,
    evaluated_fields: tuple[str, ...],
    evaluated_interval: tuple[int, int],
    now: int,
) -> EvidenceAdmission:
    """Parse bounded evidence and keep processing failures off the fact axis.

    ``parse`` converts a supported payload to exactly the five typed evidence
    records. Trust and evaluation scope remain deployment-owned arguments.
    Callback exception text is never copied into the report.
    """
    if type(schema) is not str or not schema:
        raise ValueError("schema must be a nonempty string")
    try:
        payload = decode_bounded(raw)
    except (TypeError, ValueError, RecursionError):
        return _fail(ProcessingStatus.REJECTED_EVIDENCE, "malformed_evidence")

    if type(payload) is not dict or type(payload.get("schema")) is not str:
        return _fail(ProcessingStatus.REJECTED_EVIDENCE, "malformed_evidence")
    if payload["schema"] != schema:
        return _fail(
            ProcessingStatus.UNSUPPORTED,
            "unsupported_evidence_schema",
        )

    try:
        records = parse(payload)
        if not isinstance(records, Mapping):
            raise ValueError("parser must return an evidence-record mapping")
        if set(records) != _EVIDENCE_RECORD_NAMES:
            raise ValueError("parser returned unexpected evidence records")
    except Exception:
        return _fail(ProcessingStatus.REJECTED_EVIDENCE, "malformed_evidence")

    try:
        result = admit_evidence(
            manifest=records["manifest"],
            coverage=records["coverage"],
            vantage=records["vantage"],
            binding=records["binding"],
            prior_commitment=records["prior_commitment"],
            trust=trust,
            expected_invocation=expected_invocation,
            execution_started_at=execution_started_at,
            evaluated_fields=evaluated_fields,
            evaluated_interval=evaluated_interval,
            now=now,
        )
    except Exception:
        return _fail(ProcessingStatus.VERIFIER_FAILED, "verifier_failed")
    return replace(result, evidence_digest=hashlib.sha256(raw).hexdigest())


def admit_evidence(
    *,
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
    reasons.append("effect_observation_not_supplied")

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

    manifest_scope_matches = False
    if manifest is not None and manifest.scope:
        manifest_scope_matches = all(
            key in expected_invocation
            and type(expected_invocation[key]) is type(value)
            and expected_invocation[key] == value
            for key, value in manifest.scope.items()
        )

    # ── Producer visibility: declared, accepted, and covering the fields ──
    if manifest is not None and manifest_accepted and manifest_scope_matches and all(
        manifest.covers_field(f) for f in evaluated_fields
    ):
        facts["producer_visibility_established"] = EstablishmentStatus.ESTABLISHED
    elif manifest is not None and manifest_accepted:
        reasons.append(
            "producer_visibility_not_established"
            if manifest_scope_matches else "producer_scope_mismatch"
        )

    if manifest_accepted:
        facts["source_accepted"] = EstablishmentStatus.ESTABLISHED

    # ── Coverage: explicit denominator, scoped to this invocation ─────────
    # An accepted producer is not an accepted statement. The attestation's
    # digest must be in the deployment's accepted set for that producer, or
    # a COMPLETE statement in an accepted producer's name is just a claim.
    # The producer must also be able to see every field it attests (C4).
    if coverage is not None and manifest_accepted and manifest_scope_matches:
        if coverage.producer_id != (manifest.producer_id if manifest else ""):
            reasons.append("coverage_scope_mismatch")
        elif coverage.invocation_id != expected_invocation.get("invocation_id", ""):
            reasons.append("coverage_scope_mismatch")
        elif not trust.accepts_coverage(coverage.producer_id, coverage.digest):
            reasons.append("coverage_attestation_unaccepted")
        elif manifest is not None and not all(
            manifest.covers_field(f) for f in evaluated_fields
        ):
            reasons.append("producer_visibility_not_established")
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
    else:
        reasons.append("coverage_incomplete")

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
        elif vantage.control_domain not in trust.trusted_vantage_domains:
            reasons.append("observation_vantage_not_established")
        else:
            facts["vantage_independent"] = EstablishmentStatus.ESTABLISHED
    else:
        reasons.append("observation_vantage_not_established")

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
    else:
        reasons.append("invocation_binding_not_established")

    # ── Prior commitment: must predate the execution it evaluates ─────────
    if prior_commitment is not None:
        if (
            trust.accepted_prior_commitments.get(prior_commitment.commitment_id)
            != prior_commitment.digest
        ):
            reasons.append("prior_commitment_unaccepted")
        elif not prior_commitment.binds_to(
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
    else:
        reasons.append("prior_commitment_missing")

    return EvidenceAdmission(
        processing=ProcessingStatus.COMPLETED,
        reason_codes=tuple(dict.fromkeys(reasons)),
        established_facts=facts,
        evidence_digest=_typed_evidence_digest(
            manifest=manifest,
            coverage=coverage,
            vantage=vantage,
            binding=binding,
            prior_commitment=prior_commitment,
        ),
        scope=dict(expected_invocation),
    )
