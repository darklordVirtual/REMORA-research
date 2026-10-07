# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Signed federation evidence and projection records (SDD sections 5 and 14).

The evidence a transport adapter receives is the canonical envelope bytes,
signed with Ed25519 in ``REMORA/FEDERATION-ACTION/v1``. The bytes travel
base64-encoded and are verified as they are: a verifier never re-serialises
the envelope, so no language's JSON encoding decides what was signed.

Every bridge evaluation also produces a projection record
(``remora-federation-projection-v1``) that travels with the result: which
native claim, which projection, what survived, what did not, and the
digests of the native evidence, the transport evidence, the adapter, the map
and the capability declaration.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any, Iterable

from remora.crypto import Signature, SignatureDomain, SigningKey, VerificationKey, sign, verify
from remora.policy.observation import _canonical_json

__all__ = ["EVIDENCE_FORMAT", "PROJECTION_SCHEMA", "envelope_evidence", "projection_record",
           "verify_evidence"]

EVIDENCE_FORMAT = "remora-federation-evidence-v1"
PROJECTION_SCHEMA = "remora-federation-projection-v1"


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
                      capabilities_digest: str, remora_revision: str,
                      transport_revision: str) -> dict[str, Any]:
    return {
        "schema_version": PROJECTION_SCHEMA,
        **projection,
        "transport": transport,
        "native_evidence_digest": _sha256(native_evidence),
        "transport_evidence_digest": _sha256(transport_evidence),
        "adapter_digest": adapter_digest,
        "projection_map_digest": projection_map_digest,
        "capabilities_digest": capabilities_digest,
        "remora_revision": remora_revision,
        "transport_revision": transport_revision,
    }
