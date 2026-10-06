# SPDX-License-Identifier: BUSL-1.1
"""Typed evidence-admission models (CoSAI §7.4).

Five immutable concepts stand between a raw external observation and REMORA's
property-verdict logic. Every one of them answers a question the frozen
conformance checkers deliberately take as a trusted premise; these types
record *why* the premise holds, or record that it does not.

None of these types carry authority. They are evidence records: they say what
was established, for which scope, from which vantage, with which gaps. They
cannot authorize, upgrade a decision, mint a lease or cause execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from remora import frozen_json
from remora.evidence.admission.canonical import (
    canonical_digest,
    require_identifier,
)


class ProcessingStatus(StrEnum):
    """The processing axis: did admission *run* on this input at all?

    Malformed input, unsupported schemas, acquisition failures and verifier
    errors are processing failures. They are not NOT_ESTABLISHED — that status
    is a property conclusion after applicable verification has run (CoSAI C2).
    """

    COMPLETED = "completed"
    REJECTED_EVIDENCE = "rejected_evidence"
    UNSUPPORTED = "unsupported"
    ACQUISITION_FAILED = "acquisition_failed"
    VERIFIER_FAILED = "verifier_failed"


class EstablishmentStatus(StrEnum):
    """Per-fact establishment, derived, never caller-asserted."""

    ESTABLISHED = "established"
    NOT_ESTABLISHED = "not_established"
    REFUTED = "refuted"


class ManifestTrust(StrEnum):
    """A declaration is not automatically trusted (CoSAI C4 precondition)."""

    DECLARED = "declared"
    ACCEPTED = "accepted"
    NOT_ESTABLISHED = "not_established"


class CoverageState(StrEnum):
    """The denominator, explicit. Never claim absence from INCOMPLETE/UNKNOWN."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


class VantageIndependence(StrEnum):
    """Independence is derived from facts or remains unestablished.

    There is no path from a self-declared boolean to INDEPENDENT.
    """

    INDEPENDENT = "independent"
    NOT_INDEPENDENT = "not_independent"
    NOT_ESTABLISHED = "not_established"


@dataclass(frozen=True)
class ProducerCapabilityManifest:
    """What an evidence producer was capable of observing, for a bounded scope.

    ``fields_visible`` is the producer's declared capability; whether that
    declaration is trusted is a deployment decision recorded in ``trust``.
    A manifest with trust=DECLARED is a claim, not evidence of capability.
    """

    producer_id: str
    manifest_id: str
    schema_version: str
    fields_visible: tuple[str, ...]
    scope: Mapping[str, Any]
    trust: ManifestTrust
    valid_from: int
    valid_until: int
    provenance_ref: str = ""
    digest: str = ""

    def __post_init__(self) -> None:
        require_identifier(self.producer_id, "producer_id")
        require_identifier(self.manifest_id, "manifest_id")
        require_identifier(self.schema_version, "schema_version")
        object.__setattr__(self, "fields_visible",
                           tuple(sorted(set(self.fields_visible))))
        # Deep copy: the digest below must keep describing the scope this
        # record holds, whatever the caller does with its own nested dicts.
        object.__setattr__(self, "scope", frozen_json.freeze(self.scope))
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        computed_digest = canonical_digest({
            "producer_id": self.producer_id,
            "manifest_id": self.manifest_id,
            "schema_version": self.schema_version,
            "fields_visible": list(self.fields_visible),
            "scope": frozen_json.thaw(self.scope),
            "trust": self.trust.value,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "provenance_ref": self.provenance_ref,
        })
        if self.digest and self.digest != computed_digest:
            raise ValueError("manifest digest does not match manifest content")
        object.__setattr__(self, "digest", computed_digest)

    def covers_field(self, field_name: str) -> bool:
        """Declared visibility of one field. Not proof of capability."""
        return field_name in self.fields_visible

    def valid_at(self, when: int) -> bool:
        return self.valid_from <= when < self.valid_until


@dataclass(frozen=True)
class KnownGap:
    """One named hole in a coverage interval."""

    start: int
    end: int
    reason: str

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("gap end must be after start")
        require_identifier(self.reason, "gap.reason")


@dataclass(frozen=True)
class CoverageAttestation:
    """The coverage denominator for one invocation, made explicit.

    An attestation is a producer's statement about what its observation covers.
    COMPLETE with no gaps is still only as strong as the producer's accepted
    capability; the admission layer joins the two.
    """

    invocation_id: str
    fields: tuple[str, ...]
    interval_start: int
    interval_end: int
    state: CoverageState
    producer_id: str
    known_gaps: tuple[KnownGap, ...] = ()
    provenance_ref: str = ""
    digest: str = ""

    def __post_init__(self) -> None:
        require_identifier(self.invocation_id, "invocation_id")
        require_identifier(self.producer_id, "producer_id")
        if self.interval_end <= self.interval_start:
            raise ValueError("interval_end must be after interval_start")
        object.__setattr__(self, "fields", tuple(sorted(set(self.fields))))
        object.__setattr__(self, "known_gaps",
                           tuple(sorted(self.known_gaps, key=lambda g: (g.start, g.end))))
        if self.state is CoverageState.COMPLETE and self.known_gaps:
            raise ValueError("COMPLETE coverage cannot carry known gaps")
        computed_digest = canonical_digest({
            "invocation_id": self.invocation_id,
            "fields": list(self.fields),
            "interval_start": self.interval_start,
            "interval_end": self.interval_end,
            "state": self.state.value,
            "producer_id": self.producer_id,
            "known_gaps": [
                {"start": g.start, "end": g.end, "reason": g.reason}
                for g in self.known_gaps
            ],
            "provenance_ref": self.provenance_ref,
        })
        if self.digest and self.digest != computed_digest:
            raise ValueError("coverage digest does not match attestation content")
        object.__setattr__(self, "digest", computed_digest)

    def covers_field(self, field_name: str) -> bool:
        return field_name in self.fields

    def covers_interval(self, start: int, end: int) -> bool:
        """True only when the interval is inside and no known gap overlaps."""
        if start < self.interval_start or end > self.interval_end:
            return False
        if self.state is not CoverageState.COMPLETE:
            return False
        return all(g.end <= start or g.start >= end for g in self.known_gaps)


@dataclass(frozen=True)
class ObservationVantage:
    """Who observed, relative to the observed system.

    ``declared_independence`` is the observer's own claim and is never read
    as evidence. Independence is derived from ``control_domain`` relative to
    the observed party, or remains NOT_ESTABLISHED.
    """

    observer_id: str
    observed_party: str
    control_domain: str
    observed_control_domain: str
    can_observed_party_forge: bool
    can_observed_party_suppress: bool
    declared_independence: bool = False
    provenance_ref: str = ""

    def __post_init__(self) -> None:
        require_identifier(self.observer_id, "observer_id")
        require_identifier(self.observed_party, "observed_party")
        require_identifier(self.control_domain, "control_domain")
        require_identifier(self.observed_control_domain,
                           "observed_control_domain")

    @property
    def independence(self) -> VantageIndependence:
        """Derived, never read from the observer's own declaration."""
        if self.observer_id == self.observed_party:
            return VantageIndependence.NOT_INDEPENDENT
        if self.can_observed_party_forge or self.can_observed_party_suppress:
            return VantageIndependence.NOT_INDEPENDENT
        if self.control_domain != self.observed_control_domain:
            return VantageIndependence.INDEPENDENT
        return VantageIndependence.NOT_ESTABLISHED


@dataclass(frozen=True)
class InvocationBindingProof:
    """The bounded join between evidence and the evaluated action (CoSAI C5).

    Identifier equality alone is not binding. A proof names the lineage the
    evidence binds to *and* the content digests; ``matches()`` compares every
    named axis, not a convenient subset.
    """

    evidence_id: str
    proposal_id: str
    execution_id: str
    tool_call_hash: str
    dispatch_id: str = ""
    toolspec_hash: str = ""
    tenant: str = ""
    target: str = ""
    operation: str = ""
    attempt: str = ""

    def __post_init__(self) -> None:
        for name in ("evidence_id", "proposal_id", "execution_id"):
            require_identifier(getattr(self, name), name)
        from remora.evidence.admission.canonical import require_sha256
        require_sha256(self.tool_call_hash, "tool_call_hash")
        if self.toolspec_hash:
            require_sha256(self.toolspec_hash, "toolspec_hash")

    def matches(
        self,
        *,
        proposal_id: str,
        execution_id: str,
        tool_call_hash: str,
        dispatch_id: str = "",
        toolspec_hash: str = "",
        tenant: str = "",
        target: str = "",
        operation: str = "",
        attempt: str = "",
    ) -> bool:
        """Every axis the proof declares must match. An empty axis on either
        side is a mismatch for that axis when the other side names it —
        binding to "unknown" is not binding."""
        pairs = (
            ("proposal_id", self.proposal_id, proposal_id),
            ("execution_id", self.execution_id, execution_id),
            ("tool_call_hash", self.tool_call_hash, tool_call_hash),
            ("dispatch_id", self.dispatch_id, dispatch_id),
            ("toolspec_hash", self.toolspec_hash, toolspec_hash),
            ("tenant", self.tenant, tenant),
            ("target", self.target, target),
            ("operation", self.operation, operation),
            ("attempt", self.attempt, attempt),
        )
        for _name, declared, presented in pairs:
            if declared and presented and declared != presented:
                return False
            if declared and not presented:
                return False
            if presented and not declared:
                return False
        return True


@dataclass(frozen=True)
class PriorCommitment:
    """A deployment-owned pre-execution commitment to an expected effect.

    The commitment must logically predate the execution it is later used to
    evaluate (CoSAI §7.4 prior-commitment binding). ``created_at`` earlier
    than the execution's dispatch time is necessary; the admission layer
    checks exactly that and nothing stronger — a dishonest clock is a
    deployment problem, not something this record can detect.
    """

    commitment_id: str
    proposal_id: str
    tool_call_hash: str
    target: str
    operation: str
    expected_digest: str
    created_at: int
    valid_until: int
    issuer: str
    provenance_ref: str
    digest: str = ""

    def __post_init__(self) -> None:
        for name in ("commitment_id", "proposal_id", "target", "operation",
                     "issuer", "provenance_ref"):
            require_identifier(getattr(self, name), name)
        from remora.evidence.admission.canonical import require_sha256
        require_sha256(self.tool_call_hash, "tool_call_hash")
        require_sha256(self.expected_digest, "expected_digest")
        if self.valid_until <= self.created_at:
            raise ValueError("valid_until must be after created_at")
        computed_digest = canonical_digest({
            "commitment_id": self.commitment_id,
            "proposal_id": self.proposal_id,
            "tool_call_hash": self.tool_call_hash,
            "target": self.target,
            "operation": self.operation,
            "expected_digest": self.expected_digest,
            "created_at": self.created_at,
            "valid_until": self.valid_until,
            "issuer": self.issuer,
            "provenance_ref": self.provenance_ref,
        })
        if self.digest and self.digest != computed_digest:
            raise ValueError("commitment digest does not match commitment content")
        object.__setattr__(self, "digest", computed_digest)

    def predates(self, execution_started_at: int) -> bool:
        return self.created_at <= execution_started_at

    def valid_at(self, when: int) -> bool:
        return self.created_at <= when < self.valid_until

    def binds_to(self, *, proposal_id: str, tool_call_hash: str,
                 target: str, operation: str) -> bool:
        return (
            self.proposal_id == proposal_id
            and self.tool_call_hash == tool_call_hash
            and self.target == target
            and self.operation == operation
        )
