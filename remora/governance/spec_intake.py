# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Content-bound context intake and evidence-vector spec fidelity.

Nguyen & Nguyen's SDAD paper (arXiv:2608.20341v1) treats context ingestion as
part of execution and proposes four Spec Fidelity dimensions: completeness,
consistency, unambiguity and verifiability. REMORA adopts that decomposition,
but not a scalar "quality" score. A weighted total could hide a failed
load-bearing dimension behind three easy passes.

This module therefore produces two deliberately narrow artifacts:

* :class:`ContextManifest` binds the exact source bytes, revisions, model
  route, prompt template and governance authorities used at intake. It is
  content-addressed and signed by a deployment identity.
* :class:`SpecFidelityReceipt` records a separate, evidenced verdict for each
  dimension. Positive and negative findings carry the same provenance rule.

Scope boundary: these checks establish structural coverage and provenance of
the measurement. They do not prove the source is true, the specification is
semantically correct, or an implementation conforms to it. The module is an
intake library; binding its manifest hash into final dispatch authority remains
part of RMR-004 rather than being claimed here.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping, Sequence

__all__ = [
    "ContextManifest",
    "ContextSource",
    "DimensionAssessment",
    "DimensionVerdict",
    "EvidenceFinding",
    "RequirementTrace",
    "SpecFidelityReceipt",
    "SpecIntakeEvidence",
    "SpecIntakeRefused",
    "assess_spec_intake",
    "verify_context_manifest",
    "verify_spec_fidelity_receipt",
]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIMENSIONS = ("completeness", "consistency", "unambiguity", "verifiability")


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _require_text(name: str, value: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be empty")


def _require_sha256(name: str, value: str) -> None:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase hex SHA-256 digest")


def _require_time(name: str, value: str) -> None:
    _require_text(name, value)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must carry an explicit timezone")


def _require_unique(name: str, values: Sequence[str]) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{name} must not contain duplicates")
    for value in values:
        _require_text(name, value)


@dataclass(frozen=True)
class ContextSource:
    """One immutable, byte-addressed input to spec construction."""

    source_id: str
    uri: str
    revision: str
    content_sha256: str
    purpose: str

    def __post_init__(self) -> None:
        for name in ("source_id", "uri", "revision", "purpose"):
            _require_text(name, str(getattr(self, name)))
        _require_sha256("content_sha256", self.content_sha256)

    def to_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "uri": self.uri,
            "revision": self.revision,
            "content_sha256": self.content_sha256,
            "purpose": self.purpose,
        }


@dataclass(frozen=True)
class ContextManifest:
    """Signed, content-addressed record of exactly what intake consumed."""

    schema_version: int
    intake_id: str
    spec_id: str
    spec_revision: str
    intent_authority_hash: str
    tool_spec_hash: str
    policy_bundle_hash: str
    prompt_template_hash: str
    tool_manifest_hash: str
    model_provider: str
    model_id: str
    model_route_revision: str
    sources: tuple[ContextSource, ...]
    generated_at: str
    signing_identity: str
    signature_algorithm: str
    manifest_sha256: str
    signature: str

    @classmethod
    def build(
        cls,
        *,
        intake_id: str,
        spec_id: str,
        spec_revision: str,
        intent_authority_hash: str,
        tool_spec_hash: str,
        policy_bundle_hash: str,
        prompt_template_hash: str,
        tool_manifest_hash: str,
        model_provider: str,
        model_id: str,
        model_route_revision: str,
        sources: Sequence[ContextSource],
        generated_at: str,
        signing_identity: str,
        signing_key: bytes,
    ) -> "ContextManifest":
        for name, value in (
            ("intake_id", intake_id),
            ("spec_id", spec_id),
            ("spec_revision", spec_revision),
            ("model_provider", model_provider),
            ("model_id", model_id),
            ("model_route_revision", model_route_revision),
            ("signing_identity", signing_identity),
        ):
            _require_text(name, value)
        for name, value in (
            ("intent_authority_hash", intent_authority_hash),
            ("tool_spec_hash", tool_spec_hash),
            ("policy_bundle_hash", policy_bundle_hash),
            ("prompt_template_hash", prompt_template_hash),
            ("tool_manifest_hash", tool_manifest_hash),
        ):
            _require_sha256(name, value)
        _require_time("generated_at", generated_at)
        if not signing_key:
            raise ValueError("signing_key must not be empty")
        ordered_sources = tuple(sorted(sources, key=lambda item: item.source_id))
        if not ordered_sources:
            raise ValueError("sources must contain at least one context source")
        _require_unique("source_id", [item.source_id for item in ordered_sources])

        unsigned = cls(
            schema_version=1,
            intake_id=intake_id,
            spec_id=spec_id,
            spec_revision=spec_revision,
            intent_authority_hash=intent_authority_hash,
            tool_spec_hash=tool_spec_hash,
            policy_bundle_hash=policy_bundle_hash,
            prompt_template_hash=prompt_template_hash,
            tool_manifest_hash=tool_manifest_hash,
            model_provider=model_provider,
            model_id=model_id,
            model_route_revision=model_route_revision,
            sources=ordered_sources,
            generated_at=generated_at,
            signing_identity=signing_identity,
            signature_algorithm="hmac-sha256",
            manifest_sha256="",
            signature="",
        )
        payload = unsigned.signing_payload()
        manifest_sha256 = _digest(payload)
        signature = hmac.new(
            signing_key, _canonical(payload), hashlib.sha256
        ).hexdigest()
        return replace(
            unsigned, manifest_sha256=manifest_sha256, signature=signature)

    def signing_payload(self) -> dict[str, Any]:
        """Canonical payload; digest and signature cannot sign themselves."""
        return {
            "schema_version": self.schema_version,
            "intake_id": self.intake_id,
            "spec_id": self.spec_id,
            "spec_revision": self.spec_revision,
            "intent_authority_hash": self.intent_authority_hash,
            "tool_spec_hash": self.tool_spec_hash,
            "policy_bundle_hash": self.policy_bundle_hash,
            "prompt_template_hash": self.prompt_template_hash,
            "tool_manifest_hash": self.tool_manifest_hash,
            "model_provider": self.model_provider,
            "model_id": self.model_id,
            "model_route_revision": self.model_route_revision,
            "sources": [source.to_dict() for source in self.sources],
            "generated_at": self.generated_at,
            "signing_identity": self.signing_identity,
            "signature_algorithm": self.signature_algorithm,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.signing_payload(),
            "manifest_sha256": self.manifest_sha256,
            "signature": self.signature,
        }


class SpecIntakeRefused(ValueError):
    """The intake cannot establish a trusted basis for an assessment."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def verify_context_manifest(
    manifest: ContextManifest, trusted_signers: Mapping[str, bytes]
) -> None:
    """Verify manifest structure, content address and signer binding."""
    if manifest.schema_version != 1:
        raise SpecIntakeRefused(
            "context_schema_unsupported",
            f"context manifest schema {manifest.schema_version!r} is unsupported",
        )
    if manifest.signature_algorithm != "hmac-sha256":
        raise SpecIntakeRefused(
            "context_signature_algorithm_unsupported",
            f"unsupported signature algorithm {manifest.signature_algorithm!r}",
        )
    try:
        for name, value in (
            ("intake_id", manifest.intake_id),
            ("spec_id", manifest.spec_id),
            ("spec_revision", manifest.spec_revision),
            ("model_provider", manifest.model_provider),
            ("model_id", manifest.model_id),
            ("model_route_revision", manifest.model_route_revision),
            ("signing_identity", manifest.signing_identity),
        ):
            _require_text(name, value)
        for name, value in (
            ("intent_authority_hash", manifest.intent_authority_hash),
            ("tool_spec_hash", manifest.tool_spec_hash),
            ("policy_bundle_hash", manifest.policy_bundle_hash),
            ("prompt_template_hash", manifest.prompt_template_hash),
            ("tool_manifest_hash", manifest.tool_manifest_hash),
            ("manifest_sha256", manifest.manifest_sha256),
            ("signature", manifest.signature),
        ):
            _require_sha256(name, value)
        _require_time("generated_at", manifest.generated_at)
        if not manifest.sources:
            raise ValueError("sources must contain at least one context source")
        source_ids = [source.source_id for source in manifest.sources]
        _require_unique("source_id", source_ids)
        if source_ids != sorted(source_ids):
            raise ValueError("sources must be sorted by source_id")
    except ValueError as exc:
        raise SpecIntakeRefused("context_structure_invalid", str(exc)) from exc
    key = trusted_signers.get(manifest.signing_identity)
    if not key:
        raise SpecIntakeRefused(
            "context_signer_untrusted",
            f"context signer {manifest.signing_identity!r} is not trusted",
        )
    payload = manifest.signing_payload()
    expected_digest = _digest(payload)
    if not hmac.compare_digest(expected_digest, manifest.manifest_sha256):
        raise SpecIntakeRefused(
            "context_digest_mismatch",
            "context manifest content no longer matches manifest_sha256",
        )
    expected_signature = hmac.new(
        key, _canonical(payload), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, manifest.signature):
        raise SpecIntakeRefused(
            "context_signature_invalid",
            "context manifest signature does not verify under its bound identity",
        )


@dataclass(frozen=True)
class EvidenceFinding:
    """A positive or negative finding with equal provenance burden."""

    finding_id: str
    detail: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text("finding_id", self.finding_id)
        _require_text("detail", self.detail)
        _require_unique("evidence_refs", self.evidence_refs)
        if not self.evidence_refs:
            raise ValueError("a finding requires at least one evidence reference")

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "detail": self.detail,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class RequirementTrace:
    """Requirement -> acceptance criterion -> verification evidence."""

    requirement_id: str
    acceptance_criteria: tuple[str, ...]
    verification_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text("requirement_id", self.requirement_id)
        _require_unique("acceptance_criteria", self.acceptance_criteria)
        _require_unique("verification_refs", self.verification_refs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "acceptance_criteria": list(self.acceptance_criteria),
            "verification_refs": list(self.verification_refs),
        }


@dataclass(frozen=True)
class SpecIntakeEvidence:
    """Explicit evidence supplied to the four structural checks."""

    requirement_ids: tuple[str, ...]
    acceptance_criterion_ids: tuple[str, ...]
    failure_mode_ids: tuple[str, ...]
    edge_case_ids: tuple[str, ...]
    traces: tuple[RequirementTrace, ...]
    consistency_check_refs: tuple[str, ...]
    contradictions: tuple[EvidenceFinding, ...]
    ambiguity_check_refs: tuple[str, ...]
    unresolved_terms: tuple[EvidenceFinding, ...]

    def __post_init__(self) -> None:
        for name in (
            "requirement_ids",
            "acceptance_criterion_ids",
            "failure_mode_ids",
            "edge_case_ids",
            "consistency_check_refs",
            "ambiguity_check_refs",
        ):
            _require_unique(name, getattr(self, name))
        _require_unique(
            "trace.requirement_id", [trace.requirement_id for trace in self.traces]
        )
        _require_unique(
            "contradiction.finding_id",
            [finding.finding_id for finding in self.contradictions],
        )
        _require_unique(
            "unresolved_term.finding_id",
            [finding.finding_id for finding in self.unresolved_terms],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_ids": list(self.requirement_ids),
            "acceptance_criterion_ids": list(self.acceptance_criterion_ids),
            "failure_mode_ids": list(self.failure_mode_ids),
            "edge_case_ids": list(self.edge_case_ids),
            "traces": [trace.to_dict() for trace in self.traces],
            "consistency_check_refs": list(self.consistency_check_refs),
            "contradictions": [item.to_dict() for item in self.contradictions],
            "ambiguity_check_refs": list(self.ambiguity_check_refs),
            "unresolved_terms": [item.to_dict() for item in self.unresolved_terms],
        }


class DimensionVerdict(StrEnum):
    SATISFIED = "SATISFIED"
    REFUSED = "REFUSED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class DimensionAssessment:
    name: str
    verdict: DimensionVerdict
    evidence_refs: tuple[str, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.name not in _DIMENSIONS:
            raise ValueError(f"unknown Spec Fidelity dimension {self.name!r}")
        _require_unique("dimension.evidence_refs", self.evidence_refs)
        _require_unique("dimension.reasons", self.reasons)
        if self.verdict is DimensionVerdict.SATISFIED and self.reasons:
            raise ValueError("a satisfied dimension cannot carry refusal reasons")
        if (self.verdict is DimensionVerdict.SATISFIED
                and not self.evidence_refs):
            raise ValueError("a satisfied dimension requires evidence references")
        if self.verdict is not DimensionVerdict.SATISFIED and not self.reasons:
            raise ValueError("a non-satisfied dimension requires a reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "verdict": self.verdict.value,
            "evidence_refs": list(self.evidence_refs),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class SpecFidelityReceipt:
    """Four-dimensional receipt; never a scalar quality score."""

    schema_version: int
    manifest_sha256: str
    evaluator_identity: str
    evaluated_at: str
    evidence_sha256: str
    dimensions: tuple[DimensionAssessment, ...]
    signature_algorithm: str
    receipt_sha256: str
    signature: str

    @property
    def intake_status(self) -> str:
        verdicts = {dimension.verdict for dimension in self.dimensions}
        if verdicts == {DimensionVerdict.SATISFIED}:
            return "INTAKE_ACCEPTED"
        if DimensionVerdict.REFUSED in verdicts:
            return "INTAKE_REFUSED"
        return "INTAKE_UNRESOLVED"

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_sha256": self.manifest_sha256,
            "evaluator_identity": self.evaluator_identity,
            "evaluated_at": self.evaluated_at,
            "evidence_sha256": self.evidence_sha256,
            "dimensions": [dimension.to_dict() for dimension in self.dimensions],
            "intake_status": self.intake_status,
            "signature_algorithm": self.signature_algorithm,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.payload(),
            "receipt_sha256": self.receipt_sha256,
            "signature": self.signature,
        }


def _dimension(
    name: str,
    *,
    evidence_refs: Sequence[str],
    refused: Sequence[str] = (),
    unresolved: Sequence[str] = (),
) -> DimensionAssessment:
    if refused:
        verdict = DimensionVerdict.REFUSED
        reasons = tuple(refused)
    elif unresolved:
        verdict = DimensionVerdict.UNRESOLVED
        reasons = tuple(unresolved)
    else:
        verdict = DimensionVerdict.SATISFIED
        reasons = ()
    return DimensionAssessment(
        name=name,
        verdict=verdict,
        evidence_refs=tuple(dict.fromkeys(evidence_refs)),
        reasons=reasons,
    )


def assess_spec_intake(
    *,
    manifest: ContextManifest,
    evidence: SpecIntakeEvidence,
    trusted_signers: Mapping[str, bytes],
    evaluator_identity: str,
    evaluated_at: str,
    evaluator_signing_key: bytes,
) -> SpecFidelityReceipt:
    """Assess the SDAD Spec Fidelity vector against content-bound context."""
    verify_context_manifest(manifest, trusted_signers)
    _require_text("evaluator_identity", evaluator_identity)
    _require_time("evaluated_at", evaluated_at)
    if not evaluator_signing_key:
        raise ValueError("evaluator_signing_key must not be empty")

    trace_by_requirement = {trace.requirement_id: trace for trace in evidence.traces}
    requirement_set = set(evidence.requirement_ids)
    acceptance_set = set(evidence.acceptance_criterion_ids)

    completeness_refusals: list[str] = []
    completeness_refs: list[str] = []
    for name, ids in (
        ("requirements", evidence.requirement_ids),
        ("acceptance_criteria", evidence.acceptance_criterion_ids),
        ("failure_modes", evidence.failure_mode_ids),
        ("edge_cases", evidence.edge_case_ids),
    ):
        if not ids:
            completeness_refusals.append(f"missing_{name}")
        completeness_refs.extend(f"{name}:{item}" for item in ids)
    for requirement_id in evidence.requirement_ids:
        trace = trace_by_requirement.get(requirement_id)
        if trace is None:
            completeness_refusals.append(f"requirement_untraced:{requirement_id}")
            continue
        if not trace.acceptance_criteria:
            completeness_refusals.append(
                f"acceptance_criteria_unlinked:{requirement_id}")
        for criterion in trace.acceptance_criteria:
            if criterion not in acceptance_set:
                completeness_refusals.append(
                    f"unknown_acceptance_criterion:{requirement_id}:{criterion}")
            else:
                completeness_refs.append(
                    f"trace:{requirement_id}->{criterion}")

    structural_conflicts = [
        f"trace_for_unknown_requirement:{trace.requirement_id}"
        for trace in evidence.traces
        if trace.requirement_id not in requirement_set
    ]
    contradiction_reasons = [
        f"contradiction:{finding.finding_id}" for finding in evidence.contradictions
    ]
    consistency_refs = list(evidence.consistency_check_refs)
    for finding in evidence.contradictions:
        consistency_refs.extend(finding.evidence_refs)

    ambiguity_reasons = [
        f"unresolved_term:{finding.finding_id}" for finding in evidence.unresolved_terms
    ]
    ambiguity_refs = list(evidence.ambiguity_check_refs)
    for finding in evidence.unresolved_terms:
        ambiguity_refs.extend(finding.evidence_refs)

    verifiability_refusals: list[str] = []
    verifiability_unresolved: list[str] = []
    verifiability_refs: list[str] = []
    if not evidence.requirement_ids:
        verifiability_unresolved.append("requirements_absent")
    for requirement_id in evidence.requirement_ids:
        trace = trace_by_requirement.get(requirement_id)
        if trace is None or not trace.verification_refs:
            verifiability_refusals.append(
                f"verification_missing:{requirement_id}")
            continue
        verifiability_refs.extend(trace.verification_refs)

    dimensions = (
        _dimension(
            "completeness",
            evidence_refs=completeness_refs,
            refused=completeness_refusals,
        ),
        _dimension(
            "consistency",
            evidence_refs=consistency_refs,
            refused=(*structural_conflicts, *contradiction_reasons),
            unresolved=(() if evidence.consistency_check_refs else
                        ("consistency_checks_absent",)),
        ),
        _dimension(
            "unambiguity",
            evidence_refs=ambiguity_refs,
            refused=ambiguity_reasons,
            unresolved=(() if evidence.ambiguity_check_refs else
                        ("ambiguity_checks_absent",)),
        ),
        _dimension(
            "verifiability",
            evidence_refs=verifiability_refs,
            refused=verifiability_refusals,
            unresolved=verifiability_unresolved,
        ),
    )
    evidence_sha256 = _digest(evidence.to_dict())
    unsigned = SpecFidelityReceipt(
        schema_version=1,
        manifest_sha256=manifest.manifest_sha256,
        evaluator_identity=evaluator_identity,
        evaluated_at=evaluated_at,
        evidence_sha256=evidence_sha256,
        dimensions=dimensions,
        signature_algorithm="hmac-sha256",
        receipt_sha256="",
        signature="",
    )
    payload = unsigned.payload()
    return replace(
        unsigned,
        receipt_sha256=_digest(payload),
        signature=hmac.new(
            evaluator_signing_key, _canonical(payload), hashlib.sha256
        ).hexdigest(),
    )


def verify_spec_fidelity_receipt(
    receipt: SpecFidelityReceipt,
    trusted_evaluators: Mapping[str, bytes],
) -> None:
    """Verify receipt integrity and bind its evaluator to trusted key material.

    This verifies who produced which structural assessment. It deliberately
    does not turn the referenced evidence into semantic truth.
    """
    if receipt.schema_version != 1:
        raise SpecIntakeRefused(
            "receipt_schema_unsupported",
            f"Spec Fidelity receipt schema {receipt.schema_version!r} is unsupported",
        )
    if receipt.signature_algorithm != "hmac-sha256":
        raise SpecIntakeRefused(
            "receipt_signature_algorithm_unsupported",
            f"unsupported receipt algorithm {receipt.signature_algorithm!r}",
        )
    key = trusted_evaluators.get(receipt.evaluator_identity)
    if not key:
        raise SpecIntakeRefused(
            "receipt_evaluator_untrusted",
            f"receipt evaluator {receipt.evaluator_identity!r} is not trusted",
        )
    names = [dimension.name for dimension in receipt.dimensions]
    if tuple(names) != _DIMENSIONS:
        raise SpecIntakeRefused(
            "receipt_dimensions_invalid",
            "receipt must carry the four dimensions once, in canonical order",
        )
    try:
        _require_sha256("manifest_sha256", receipt.manifest_sha256)
        _require_sha256("evidence_sha256", receipt.evidence_sha256)
        _require_sha256("receipt_sha256", receipt.receipt_sha256)
        _require_sha256("signature", receipt.signature)
        _require_time("evaluated_at", receipt.evaluated_at)
    except ValueError as exc:
        raise SpecIntakeRefused("receipt_structure_invalid", str(exc)) from exc
    payload = receipt.payload()
    if not hmac.compare_digest(_digest(payload), receipt.receipt_sha256):
        raise SpecIntakeRefused(
            "receipt_digest_mismatch",
            "Spec Fidelity receipt no longer matches receipt_sha256",
        )
    expected_signature = hmac.new(
        key, _canonical(payload), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, receipt.signature):
        raise SpecIntakeRefused(
            "receipt_signature_invalid",
            "Spec Fidelity receipt signature does not verify for its evaluator",
        )
