# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""One executed invocation, exported so a third party can check it offline.

What the export holds, for one directly ACCEPTed proposal:

* the ``assessed``, ``execution_authorized`` and ``execution_result`` chain
  entries, each with its previous hash, its entry hash and the exact canonical
  payload string the entry hash covers;
* the signed decision grant and the signed execution lease, each with the
  exact bytes its signature covers;
* the authorization context fields the grant's ``context_hash`` covers;
* the request reference the call arrived in, when the front end supplied one.

The whole body is signed once more with Ed25519 under ``REMORA/EVIDENCE/v1``
by the exporting service. A verifier needs three public keys (grant, lease,
evidence) and no secret, and it never re-serialises anything: every signature
and every hash is checked over bytes the export carries.

What this does not establish
----------------------------
The evidence signature says the exporting service stated these records. The
chain entries are HMAC-signed in the store and that signature is not
exported, so an entry's authenticity rests on the evidence signature, not on
the chain. The grant and lease signatures are independent of the exporter,
because the PDP and the lease issuer hold their own keys. None of this shows
that the effect happened, that every path to the tool passes through REMORA,
or that the capture on the other side is complete.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from remora.errors import RemoraError
from remora.timebase import utc_now

FORMAT = "remora-invocation-evidence-v1"
ENVELOPE_FORMAT = "remora-invocation-evidence-envelope-v1"
ENV_EVIDENCE_PRIVATE = "REMORA_EVIDENCE_SIGNING_KEY_ED25519_PRIVATE"

#: Stated in every export, so a reader of the bytes alone sees the ceiling.
LIMITS = (
    "chain entries are authenticated by the evidence signature, not by the store's HMAC",
    "an executed record is REMORA's dispatch outcome, not an observed external effect",
    "the request reference is what the front end recorded; it does not show every path "
    "to the tool passes through it",
)


class InvocationEvidenceUnavailable(RemoraError):
    """The proposal cannot be exported as one signed invocation, with a reason."""

    code = "invocation_evidence_unavailable"
    category = "execution"

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason


def evidence_signing_key() -> Any:
    """The configured evidence key, or None when this process has none."""
    seed = os.environ.get(ENV_EVIDENCE_PRIVATE, "").strip()
    if not seed:
        return None
    from remora.crypto import SignatureDomain, SigningKey

    return SigningKey.from_text(seed, {SignatureDomain.EVIDENCE})


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _entry(entry: Any) -> dict[str, Any]:
    from remora.governance.tenant_chain import _canonical

    return {
        "event": entry.payload.get("event"),
        "sequence_no": entry.sequence_no,
        "timestamp": entry.timestamp,
        "previous_hash": entry.previous_hash,
        "entry_hash": entry.entry_hash,
        "payload_canonical": _canonical(entry.payload),
    }


def _grant_section(data: dict[str, Any]) -> dict[str, Any]:
    from remora.crypto import SignatureDomain
    from remora.enforcement.token import FORMAT_V3, PolicyDecisionToken

    token = PolicyDecisionToken.from_dict(data)
    return {
        "token": token.to_dict(),
        "signed_payload_b64": _b64(token.signed_payload()),
        # Only v3 is checkable with a public key. A v1/v2 grant is HMAC and
        # is exported so a verifier can say so, not so it can be trusted.
        "domain": SignatureDomain.POLICY_GRANT_ASYMMETRIC.value
        if token.format == FORMAT_V3 else None,
    }


def _lease_section(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    from remora.crypto import SignatureDomain
    from remora.enforcement.lease import ExecutionLease
    from remora.enforcement.lease_signing import ALG_ED25519_V2

    lease = ExecutionLease.from_dict(data)
    return {
        "lease": lease.to_dict(),
        "signed_payload_b64": _b64(lease.signed_payload()),
        "domain": SignatureDomain.EXECUTION_LEASE.value
        if lease.sig_alg == ALG_ED25519_V2 else None,
    }


def select_invocation(entries: list[Any], proposal_id: str) -> tuple[Any, Any, Any]:
    """The assessed, authorized and result entries of one direct ACCEPT."""
    mine = [e for e in entries if e.payload.get("proposal_id") == proposal_id]
    if not mine:
        raise InvocationEvidenceUnavailable("proposal_not_found")
    assessed = [e for e in mine if e.payload.get("event") == "assessed"]
    if len(assessed) != 1 or assessed[0].payload.get("decision") != "accept":
        raise InvocationEvidenceUnavailable(
            "not_a_direct_accept", "only a directly ACCEPTed proposal is exported")
    jti = assessed[0].payload.get("grant_jti")
    authorized = [
        e for e in mine
        if e.payload.get("event") == "execution_authorized"
        and e.payload.get("grant_jti") == jti
    ]
    if not authorized:
        raise InvocationEvidenceUnavailable("not_executed")
    if len(authorized) != 1:
        raise InvocationEvidenceUnavailable("ambiguous_authorization")
    if "grant" not in authorized[0].payload:
        raise InvocationEvidenceUnavailable(
            "grant_not_recorded", "recorded before grants were kept in the chain")
    results = [
        e for e in mine
        if e.payload.get("event") == "execution_result"
        and e.payload.get("intent_sequence_no") == authorized[0].sequence_no
    ]
    if len(results) != 1:
        raise InvocationEvidenceUnavailable("result_not_recorded")
    return assessed[0], authorized[0], results[0]


def build_invocation_evidence(
    entries: list[Any],
    *,
    tenant: str,
    proposal_id: str,
    signing_key: Any,
    exported_at: str | None = None,
) -> dict[str, Any]:
    """Build and sign the export for one proposal. Raises when it cannot."""
    if signing_key is None:
        raise InvocationEvidenceUnavailable(
            "evidence_key_unavailable", f"{ENV_EVIDENCE_PRIVATE} is not set")
    assessed, authorized, result = select_invocation(entries, proposal_id)
    body: dict[str, Any] = {
        "format": FORMAT,
        "tenant": tenant,
        "proposal_id": proposal_id,
        "exported_at": exported_at or utc_now().isoformat(),
        "request_ref": assessed.payload.get("request_ref"),
        "authorization_context": assessed.payload.get("authorization_context"),
        "grant": _grant_section(authorized.payload["grant"]),
        "lease": _lease_section(result.payload.get("lease")),
        "chain": [_entry(assessed), _entry(authorized), _entry(result)],
        "limits": list(LIMITS),
    }
    payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")
    from remora.crypto import SignatureDomain, sign

    signature = sign(SignatureDomain.EVIDENCE, payload, signing_key)
    return {
        "format": ENVELOPE_FORMAT,
        "payload_b64": _b64(payload),
        "signature": {
            "alg": signature.algorithm,
            "domain": signature.domain,
            "kid": signature.kid,
            "value": signature.value,
        },
    }


__all__ = [
    "ENVELOPE_FORMAT",
    "ENV_EVIDENCE_PRIVATE",
    "FORMAT",
    "LIMITS",
    "InvocationEvidenceUnavailable",
    "build_invocation_evidence",
    "evidence_signing_key",
    "select_invocation",
]
