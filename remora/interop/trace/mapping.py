# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Map one signed REMORA federation result into TRACE v0.2 record shape.

REMORA's role towards AgenTrust TRACE is ``external-evidence-source``: it
holds signed evidence another system assembles into a record, and it issues
no TRACE Trust Record of its own. That is the role AgenTrust assigned to the
same case in agentrust-io/integrations#170 (APS), and the one Nobulex and
probityai-observed-effect declare. The output of this module is therefore a
*mapping*, not a Trust Record, and it claims no TRACE conformance level.

The source is a ``remora-federation-result-evidence-v1`` envelope
(``remora.federation.results``). It is verified first, against keys the
caller supplies and the exact subject the caller names, by REMORA's own
``verify_result``. Nothing is mapped from an envelope that does not verify,
and the native result is carried verbatim: a CONTRADICTED stays CONTRADICTED.

Field by field
==============

====================  ==========================================================
TRACE field           source, or why it is absent
====================  ==========================================================
eat_profile           constant
iat                   caller's issuance time (never the execution time)
origin                ``third-party-control-plane``; producer, source event and
                      ingestion time from the request
model                 ``ExecutionContextV1.model_initiator``, only when the
                      context is bound by digest into the signed report
appraisal             ``status: none``: nothing here appraised the evidence;
                      ``verifier`` names the result's signing key
references            one pointer to the signed result, only when the caller
                      names a resolver (spec 3.1.2 rule 4)
subject               absent: REMORA's evidence names the principal of the
                      action, not a workload SVID or DID
runtime               absent: ``measurement`` is required even for
                      ``software-only`` and REMORA holds no workload
                      measurement; its runtime identity hash is not one
policy                absent: the native evidence carries no policy bundle digest
data_class            absent: REMORA's data scope does not classify downstream data
build_provenance      absent: no SLSA level in the native evidence
cnf                   absent: export signing is not part of this mapping
====================  ==========================================================

Values REMORA holds but does not map (the deployment-asserted runtime identity
hash and build digest, the data scope) are kept in the ``remora`` sidecar
under ``available_unmapped``, so the loss is visible rather than silent.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from remora.crypto import Signature, VerificationKey
from remora.federation.results import verify_result
from remora.federation.subjects import Report, SelectionRefused, SubjectRef, select_report
from remora.governance.execution_identity import ExecutionContextRefused, ExecutionContextV1
from remora.interop.jcs import CANONICAL_FORMAT, canonicalise

__all__ = ["EAT_PROFILE", "MAPPING_SCHEMA", "REFERENCE_REL", "TRACE_REQUIRED", "ExportRequest",
           "TraceExportRefused", "map_result"]

MAPPING_SCHEMA = "remora-trace-mapping-v1"
EAT_PROFILE = "tag:agentrust-io.com,2026:trace-v0.2"

#: ``required`` of trace-claim.json at the pinned commit (upstream-lock.json).
TRACE_REQUIRED = ("eat_profile", "iat", "subject", "model", "runtime", "policy", "data_class",
                  "build_provenance", "appraisal", "cnf")

#: Unregistered on purpose. ``condition-appraisal`` is the nearest registered
#: value, but it names an *independent* check, and a REMORA result signed by
#: REMORA is not one. Spec 3.1.2 allows an unregistered rel.
REFERENCE_REL = "remora-native-claim-result"

#: The refusal codes this module raises; a subset of the SDD's exit codes.
REFUSAL_CODES = ("INVALID_INPUT", "NATIVE_EVIDENCE_INVALID", "AMBIGUOUS_SUBJECT",
                 "BINDING_MISMATCH")

_IAT_MIN, _IAT_MAX = 1_700_000_000, 9_007_199_254_740_991
_RETENTION = re.compile(
    r"^P(\d+W|(\d+Y(\d+M)?(\d+D)?|\d+M(\d+D)?|\d+D)(T(\d+H(\d+M)?(\d+S)?|\d+M(\d+S)?|\d+S))?"
    r"|T(\d+H(\d+M)?(\d+S)?|\d+M(\d+S)?|\d+S))$")

NON_CLAIMS = (
    "not_a_trace_trust_record",
    "no_trace_conformance_level",
    "references_are_pointers_not_evidence",
    "native_result_is_remora_verifier_output_not_re_evaluated",
    "independent_verification_not_established",
    "runtime_capability_surface_completeness_not_established",
    "effect_not_established_by_this_mapping",
)


class TraceExportRefused(ValueError):
    """No mapping is produced. ``code`` is one of ``REFUSAL_CODES``."""

    def __init__(self, code: str, reason: str) -> None:
        if code not in REFUSAL_CODES:
            raise ValueError(f"unknown TRACE refusal code: {code!r}")
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class ExportRequest:
    """What the caller asks to export, and the facts only the caller can supply.

    ``subject`` is explicit: the exporter never picks a report. ``expected_*``
    are checked against the bound execution context when one is given.
    """

    native_claim: str
    subject: SubjectRef
    issued_at: int
    ingested_at: int
    producer: str
    resolver: str | None = None
    retention: str | None = None
    expected_tenant: str | None = None
    expected_principal: str | None = None


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _epoch(value: Any, name: str) -> int:
    if type(value) is not int or not _IAT_MIN <= value <= _IAT_MAX:
        raise TraceExportRefused("INVALID_INPUT", f"{name}_out_of_range")
    return value


def _check_request(request: ExportRequest) -> None:
    if type(request.subject) is not SubjectRef:
        raise TraceExportRefused("INVALID_INPUT", "subject_not_a_subject_ref")
    if not request.subject.report_specific:
        raise TraceExportRefused("AMBIGUOUS_SUBJECT", "subject_not_report_specific")
    _epoch(request.issued_at, "issued_at")
    _epoch(request.ingested_at, "ingested_at")
    if request.ingested_at > request.issued_at:
        raise TraceExportRefused("INVALID_INPUT", "ingested_after_issued")
    for name in ("native_claim", "producer"):
        value = getattr(request, name)
        if type(value) is not str or not value.strip():
            raise TraceExportRefused("INVALID_INPUT", f"{name}_empty")
    if request.resolver is not None and (type(request.resolver) is not str
                                         or not request.resolver.strip()):
        raise TraceExportRefused("INVALID_INPUT", "resolver_empty")
    if request.retention is not None:
        if request.resolver is None:
            raise TraceExportRefused("INVALID_INPUT", "retention_without_resolver")
        if type(request.retention) is not str or not _RETENTION.match(request.retention):
            raise TraceExportRefused("INVALID_INPUT", "retention_not_iso8601_duration")


def _select(reports: Sequence[Report], subject: SubjectRef) -> Report:
    try:
        report, _ = select_report(reports, report_digest=subject.report_digest)
    except SelectionRefused as exc:
        raise TraceExportRefused("AMBIGUOUS_SUBJECT", exc.reason) from exc
    return report


def _bound_context(report: Report, execution_context: str,
                   request: ExportRequest) -> ExecutionContextV1:
    try:
        context = ExecutionContextV1.from_canonical(execution_context)
    except ExecutionContextRefused as exc:
        raise TraceExportRefused("INVALID_INPUT", exc.reason) from exc
    bound = report.body.get("execution_context_digest") if isinstance(report.body, dict) else None
    if bound is None:
        raise TraceExportRefused("BINDING_MISMATCH", "execution_context_not_bound_to_report")
    if bound != context.digest():
        raise TraceExportRefused("BINDING_MISMATCH", "execution_context_digest_differs")
    if request.expected_tenant is not None and context.tenant_id != request.expected_tenant:
        raise TraceExportRefused("BINDING_MISMATCH", "tenant_differs")
    if (request.expected_principal is not None
            and context.subject.principal_id != request.expected_principal):
        raise TraceExportRefused("BINDING_MISMATCH", "principal_differs")
    return context


def _absent(context: ExecutionContextV1 | None) -> dict[str, str]:
    absent = {
        "subject": "no_verified_workload_identity_in_native_evidence",
        "runtime": "no_workload_measurement_software_only_semantics_unresolved",
        "policy": "no_policy_bundle_digest_in_native_evidence",
        "data_class": ("native_data_scope_does_not_classify_downstream_data"
                       if context is not None else "no_data_classification_in_native_evidence"),
        "build_provenance": ("no_slsa_level_in_native_evidence" if context is not None
                             else "no_build_provenance_in_native_evidence"),
        "cnf": "export_signing_not_part_of_mapping",
    }
    if context is None:
        absent["model"] = "no_execution_context_bound_to_subject"
    return absent


def map_result(evidence: bytes, keys: Iterable[VerificationKey], request: ExportRequest, *,
               reports: Sequence[Report], execution_context: str | None = None
               ) -> dict[str, Any]:
    """The TRACE-shaped mapping of one verified result, or ``TraceExportRefused``.

    ``reports`` are the native reports the caller holds; the one whose digest
    the subject names is used, and none is chosen by position. When
    ``execution_context`` (canonical ``ExecutionContextV1`` text) is given, the
    selected report's body must carry its digest as ``execution_context_digest``.
    """
    _check_request(request)
    report = _select(reports, request.subject)
    verified = verify_result(evidence, list(keys), native_claim=request.native_claim,
                             subject=request.subject, report=report)
    if not verified.bound:
        raise TraceExportRefused("NATIVE_EVIDENCE_INVALID", verified.reason)
    document = verified.document or {}
    context = (_bound_context(report, execution_context, request)
               if execution_context is not None else None)

    signer = Signature.from_dict(json.loads(evidence)["signature"]).kid
    evidence_digest = _sha256(evidence)
    subject = request.subject

    trace: dict[str, Any] = {
        "eat_profile": EAT_PROFILE,
        "iat": request.issued_at,
        "origin": {"kind": "third-party-control-plane", "producer": request.producer,
                   "source_event_id": f"{subject.operation_id}/{subject.report_id}",
                   "ingested_at": request.ingested_at},
        "appraisal": {"status": "none",
                      "verifier": f"urn:remora:federation-result-signer:{signer}"},
    }
    if context is not None:
        trace["model"] = {"provider": context.model_initiator.provider,
                          "model_id": context.model_initiator.model_id}
    if request.resolver is not None:
        reference: dict[str, Any] = {"rel": REFERENCE_REL, "id": evidence_digest,
                                     "resolver": request.resolver, "digest": evidence_digest}
        if request.retention is not None:
            reference["retention"] = request.retention
        trace["references"] = [reference]

    sidecar: dict[str, Any] = {
        "native_claim": request.native_claim,
        "subject": subject.to_dict(),
        "evidence_selection": document.get("evidence_selection"),
        "native_result": verified.native_result,
        "result_evidence_digest": evidence_digest,
        "result_signer_kid": signer,
        "reference_emitted": request.resolver is not None,
        "non_claims": list(NON_CLAIMS),
    }
    if context is not None:
        sidecar["execution_context"] = {
            "digest": "sha256:" + context.digest(),
            "tenant_id": context.tenant_id,
            "principal_id": context.subject.principal_id,
            "principal_authority": context.subject.authority.kind,
            "model_authority": {"kind": context.model_initiator.authority.kind,
                                "issuer": context.model_initiator.authority.issuer},
        }
        sidecar["available_unmapped"] = {
            "runtime_identity_hash": {
                "value": "sha256:" + context.runtime.runtime_identity_hash,
                "asserted_by": context.runtime.authority.kind,
                "why_not_mapped": "not_a_workload_measurement"},
            "build_provenance_digest": {
                "value": "sha256:" + context.runtime.build_provenance_digest,
                "asserted_by": context.runtime.authority.kind,
                "why_not_mapped": "no_slsa_level_and_artifact_not_verified"},
            "data_scope": {
                "classification": context.data_scope.classification,
                "scope": list(context.data_scope.scope),
                "ceiling": context.data_scope.ceiling,
                "why_not_mapped": "trace_data_class_covers_outputs_remora_scope_does_not"},
        }

    trace_bytes = canonicalise(trace)
    return {
        "schema_version": MAPPING_SCHEMA,
        "trace_role": "external-evidence-source",
        "trace_conformance_level": None,
        "is_trust_record": False,
        "trace": trace,
        "trace_canonicalization": CANONICAL_FORMAT,
        "trace_digest": _sha256(trace_bytes),
        "absent_required": _absent(context),
        "remora": sidecar,
    }
