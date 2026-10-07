# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Signed federation evidence and projection records (SDD sections 5 and 14).

The evidence a transport adapter receives is the canonical envelope bytes,
signed with Ed25519 in ``REMORA/FEDERATION-ACTION/v1``. The bytes travel
base64-encoded and are verified as they are: a verifier never re-serialises
the envelope, so no language's JSON encoding decides what was signed.

Every bridge evaluation also produces a projection record that travels with
the result: which native claim, which projection, what survived, what did
not, and the digests of the native evidence, the transport evidence, the
adapter, the map and the capability declaration.

Record versions. ``remora-federation-projection-v2`` (written now) adds the
subject the result is about, how that subject was selected, and the native
result with its reason, beside the projection; projection strength and native
result stay separate fields. ``remora-federation-projection-v1`` records stay
readable through ``read_projection_record``, which never reads a report
binding into a record that did not carry one.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any, Iterable

from remora.crypto import Signature, SignatureDomain, SigningKey, VerificationKey, sign, verify
from remora.policy.observation import _canonical_json

__all__ = ["EVIDENCE_FORMAT", "PROJECTION_SCHEMA", "PROJECTION_SCHEMA_V1", "envelope_evidence",
           "projection_record", "read_projection_record", "verify_evidence"]

EVIDENCE_FORMAT = "remora-federation-evidence-v1"
PROJECTION_SCHEMA = "remora-federation-projection-v2"
PROJECTION_SCHEMA_V1 = "remora-federation-projection-v1"


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def envelope_evidence(document: dict[str, Any], key: SigningKey) -> bytes:
    """Sign ``document`` (envelope plus transport projection) into evidence bytes."""
    payload = _canonical_json(document).encode("utf-8")
    signature = sign(SignatureDomain.FEDERATION_ACTION, payload, key)
    return json.dumps({"format": EVIDENCE_FORMAT,
                       "envelope_b64": base64.b64encode(payload).decode("ascii"),
                       "signature": signature.to_dict()},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_evidence(evidence: bytes, keys: Iterable[VerificationKey]
                    ) -> tuple[bool, str, dict[str, Any] | None]:
    """(verified, reason, envelope). The Python twin of the adapter's integrity check."""
    try:
        outer = json.loads(evidence)
        if outer.get("format") != EVIDENCE_FORMAT:
            return False, "evidence_format_unknown", None
        payload = base64.b64decode(outer["envelope_b64"], validate=True)
        signature = Signature.from_dict(outer["signature"])
    except (ValueError, KeyError, TypeError, binascii.Error):
        return False, "evidence_malformed", None
    result = verify(SignatureDomain.FEDERATION_ACTION, payload, signature, list(keys))
    if not result.ok:
        return False, result.reason, None
    return True, "ok", json.loads(payload)


def projection_record(*, projection: dict[str, Any], transport: str, native_evidence: bytes,
                      transport_evidence: bytes, adapter_digest: str, projection_map_digest: str,
                      capabilities_digest: str, remora_revision: str, transport_revision: str,
                      subject: Any, evidence_selection: Any,
                      native_result: Any = None) -> dict[str, Any]:
    """A ``remora-federation-projection-v2`` record.

    ``subject`` and ``evidence_selection`` say exactly which native evidence
    the record describes. ``native_result`` is what the native verifier
    concluded about that subject, or ``None`` when the record describes a
    projection at issuance and no native evaluation of the subject is reported.
    """
    return {
        "schema_version": PROJECTION_SCHEMA,
        **projection,
        "subject": subject.to_dict(),
        "evidence_selection": evidence_selection.to_dict(),
        "native_result": native_result.to_dict() if native_result is not None else None,
        "transport": transport,
        "native_evidence_digest": _sha256(native_evidence),
        "transport_evidence_digest": _sha256(transport_evidence),
        "adapter_digest": adapter_digest,
        "projection_map_digest": projection_map_digest,
        "capabilities_digest": capabilities_digest,
        "remora_revision": remora_revision,
        "transport_revision": transport_revision,
    }


def read_projection_record(record: dict[str, Any]) -> dict[str, Any]:
    """Any supported record, in the v2 shape, with what it can and cannot say.

    A v1 record has no subject, selection or native result. It is returned with
    those as ``None`` and ``report_specific_binding: NOT_ESTABLISHED``: the
    absence of report identity is never filled in from surrounding metadata.
    A v2 record's binding is stated only as declared here; establishing it
    needs the signed result (``remora.federation.results.verify_result``).
    """
    version = record.get("schema_version")
    if version == PROJECTION_SCHEMA_V1:
        return {**record, "subject": None, "evidence_selection": None, "native_result": None,
                "report_specific_binding": "NOT_ESTABLISHED",
                "report_specific_binding_reason": "legacy_v1_record_has_no_subject"}
    if version == PROJECTION_SCHEMA:
        subject = record.get("subject") or {}
        declared = subject.get("kind") in ("operation_report", "execution_attempt",
                                           "effect_observation")
        return {**record, "report_specific_binding": "NOT_ESTABLISHED",
                "report_specific_binding_reason": (
                    "declared_requires_signed_result_verification" if declared
                    else "subject_is_not_report_specific")}
    raise ValueError(f"unknown projection record version {version!r}")
