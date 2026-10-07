# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Signed, subject-bound native results (report-specific binding).

``result_evidence`` signs one native result together with the claim, the
subject it is about and how that subject was selected, in
``REMORA/FEDERATION-RESULT/v1``. Because the subject (operation id, report id,
report digest, sequence) is inside the signature, an ESTABLISHED result for
report A cannot be relabelled as a result for report B.

``verify_result`` checks the signature, that the signed subject is the one
the consumer asks about, that the selection names that same report, and,
when the consumer holds the report itself, that its bytes hash to the signed
digest. Anything else is NOT_ESTABLISHED, with a reason, and no native result
is returned.

``federate_result`` is the bridge step: select a report by a declared rule,
take the native verifier's result for that report only, project the claim,
and emit the signed result with a ``remora-federation-projection-v2`` record.
The native result is carried, never reinterpreted.
"""
from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from remora.crypto import Signature, SignatureDomain, SigningKey, VerificationKey, sign, verify
from remora.federation.subjects import (
    EvidenceSelection,
    NativeResult,
    Report,
    SelectionProfile,
    SubjectRef,
    select_report,
)
from remora.policy.observation import _canonical_json

__all__ = ["RESULT_EVIDENCE_FORMAT", "RESULT_SCHEMA", "ResultVerification", "federate_result",
           "result_evidence", "verify_result"]

RESULT_SCHEMA = "remora-federation-result-v1"
RESULT_EVIDENCE_FORMAT = "remora-federation-result-evidence-v1"


def result_document(*, native_claim: str, subject: SubjectRef, selection: EvidenceSelection,
                    native_result: NativeResult) -> dict[str, Any]:
    if subject.report_specific and selection.selected_digest != subject.report_digest:
        raise ValueError("the selection and the subject name different reports")
    return {"schema_version": RESULT_SCHEMA, "native_claim": native_claim,
            "subject": subject.to_dict(), "evidence_selection": selection.to_dict(),
            "native_result": native_result.to_dict()}


def result_evidence(document: dict[str, Any], key: SigningKey) -> bytes:
    payload = _canonical_json(document).encode("utf-8")
    signature = sign(SignatureDomain.FEDERATION_RESULT, payload, key)
    return json.dumps({"format": RESULT_EVIDENCE_FORMAT,
                       "result_b64": base64.b64encode(payload).decode("ascii"),
                       "signature": signature.to_dict()},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class ResultVerification:
    """Whether the result is bound to the asked subject; the native result only if so."""

    binding: str  # ESTABLISHED | NOT_ESTABLISHED
    reason: str
    native_result: dict[str, Any] | None = None
    document: dict[str, Any] | None = None

    @property
    def bound(self) -> bool:
        return self.binding == "ESTABLISHED"


def _refuse(reason: str) -> ResultVerification:
    return ResultVerification("NOT_ESTABLISHED", reason)


def verify_result(evidence: bytes, keys: Iterable[VerificationKey], *, native_claim: str,
                  subject: SubjectRef, report: Report | None = None) -> ResultVerification:
    """Is this the signed native result for ``native_claim`` about exactly ``subject``?"""
    try:
        outer = json.loads(evidence)
        if outer.get("format") != RESULT_EVIDENCE_FORMAT:
            return _refuse("result_format_unknown")
        payload = base64.b64decode(outer["result_b64"], validate=True)
        signature = Signature.from_dict(outer["signature"])
    except (ValueError, KeyError, TypeError, binascii.Error):
        return _refuse("result_evidence_malformed")
    checked = verify(SignatureDomain.FEDERATION_RESULT, payload, signature, list(keys))
    if not checked.ok:
        return _refuse(checked.reason)
    document = json.loads(payload)
    if document.get("schema_version") != RESULT_SCHEMA:
        return _refuse("result_schema_unknown")
    if document.get("native_claim") != native_claim:
        return _refuse("claim_differs")
    if document.get("subject") != subject.to_dict():
        return _refuse("subject_differs")
    selection = document.get("evidence_selection") or {}
    if subject.report_specific and selection.get("selected_digest") != subject.report_digest:
        return _refuse("selection_differs_from_subject")
    if report is not None:
        if report.subject() != subject:
            return _refuse("report_differs_from_subject")
    return ResultVerification("ESTABLISHED", "ok", document.get("native_result"), document)


def federate_result(*, native_claim: str, reports: Sequence[Report],
                    evaluate: Callable[[Report], NativeResult], key: SigningKey,
                    projection: dict[str, Any], record: Callable[..., dict[str, Any]],
                    report_id: str | None = None, report_digest: str | None = None,
                    profile: SelectionProfile | None = None) -> tuple[dict[str, Any], bytes]:
    """Select, evaluate the selected report natively, sign, and record.

    ``evaluate`` is the native verifier; it sees only the selected report.
    ``record`` builds the projection record (``evidence.projection_record``
    with the transport's digests bound). Raises ``SelectionRefused`` when no
    report is selected: no result is produced for an ambiguous subject.
    """
    report, selection = select_report(reports, report_id=report_id,
                                      report_digest=report_digest, profile=profile)
    subject = report.subject()
    native = evaluate(report)
    document = result_document(native_claim=native_claim, subject=subject, selection=selection,
                               native_result=native)
    evidence = result_evidence(document, key)
    return record(projection=projection, subject=subject, evidence_selection=selection,
                  native_result=native, native_evidence=_canonical_json(report.body).encode(),
                  transport_evidence=evidence), evidence
