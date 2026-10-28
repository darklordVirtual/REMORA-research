"""Verifier-side recomputation of DecisionEnvelope audit hashes (SEC-01).

Schema version 3 records (SR-01 remediation, 2026-10-28) are sealed only
after every audit field is populated, so a verifier can rebuild the hash
preimage from the stored envelope alone and confirm both the chain hash and
the HMAC signature. Version 2 records sealed the hash before the tenant,
actor, policy and argument fields were written; they cannot be recomputed
and verify by chain linkage only. This module dispatches on
``audit.schema_version`` so both kinds remain checkable without rewriting
history.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from dataclasses import dataclass

from remora.governance.envelope import normalize_audit_for_hash

__all__ = [
    "EnvelopeVerifyResult",
    "canonical_envelope_for_hash",
    "compute_envelope_chain_hash",
    "recompute_stored_hash",
    "verify_stored_envelope",
]


@dataclass(frozen=True)
class EnvelopeVerifyResult:
    """Outcome of verifying one stored envelope.

    ``hash_ok`` is ``None`` when the record predates v3 and cannot be
    recomputed at all; ``signature_ok`` is ``None`` when there is no
    key to check it against. A supplied key requires a signature.
    """

    schema_version: str | None
    hash_ok: bool | None
    signature_ok: bool | None
    mode: str  # "recompute" | "links"
    detail: str = ""


def canonical_envelope_for_hash(envelope_payload: dict) -> dict:
    """Return an envelope payload suitable for deterministic chain hashing.

    A non-dict payload is an internal invariant violation, not user input:
    silently canonicalising it to ``{}`` gave every malformed envelope the
    same chain hash for a given predecessor, so the hash could not tell two
    different bad inputs apart.
    """
    if not isinstance(envelope_payload, dict):
        raise TypeError(
            f"envelope payload must be a mapping to be chain-hashed, got "
            f"{type(envelope_payload).__name__}"
        )
    canonical = deepcopy(envelope_payload)
    audit = canonical.get("audit") if isinstance(canonical, dict) else None
    if isinstance(audit, dict):
        if audit.get("schema_version") == "3":
            # v3 (SR-01 / SEC-01): every populated audit field is inside the
            # preimage. ``previous_hash`` is prefixed into the preimage rather
            # than serialised; ``hash`` and ``signature`` are the seal itself.
            for key in ("hash", "previous_hash", "signature"):
                audit.pop(key, None)
        else:
            # v2 legacy rule. ``genesis`` is a pure derivative of
            # ``previous_hash``, which is already excluded here and instead
            # prefixed into the preimage. Hashing it would change every
            # envelope hash and break the committed tenant chains for no added
            # binding. Fields written after the v2 seal (tenant, actor, policy
            # and argument binding) cannot be recomputed from a stored v2
            # record — that gap is SR-01; v2 records verify by chain links
            # only.
            for key in ("hash", "previous_hash", "signature", "timestamp_utc",
                        "genesis"):
                audit.pop(key, None)
    # Post-v2 audit keys are omitted when unset so control-plane chains
    # recorded before those fields existed keep verifying (see
    # remora/governance/envelope.py::POST_V2_AUDIT_KEYS).
    normalize_audit_for_hash(canonical)
    return canonical


def compute_envelope_chain_hash(*, previous_hash: str | None, envelope_payload: dict) -> str:
    """Compute SHA-256(previous_hash || canonical_envelope_json)."""
    canonical = canonical_envelope_for_hash(envelope_payload)
    serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    preimage = f"{previous_hash or ''}:{serialized}"
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def recompute_stored_hash(stored: dict) -> str:
    """Rebuild the chain hash from a stored envelope payload alone."""
    audit = stored.get("audit") if isinstance(stored, dict) else None
    if not isinstance(audit, dict):
        raise TypeError("stored envelope carries no audit block to recompute")
    previous_hash = audit.get("previous_hash")
    return compute_envelope_chain_hash(
        previous_hash=previous_hash if isinstance(previous_hash, str) else None,
        envelope_payload=stored,
    )


def verify_stored_envelope(stored: dict, signing_key: str | None = None) -> EnvelopeVerifyResult:
    """Verify one stored envelope against its own seal.

    v3 records are recomputed from the stored payload; v2 records are
    reported as links-only because their seal predates the fields a
    recompute would bind.
    """
    audit = stored.get("audit") if isinstance(stored, dict) else None
    if not isinstance(audit, dict):
        return EnvelopeVerifyResult(
            schema_version=None, hash_ok=False, signature_ok=None,
            mode="recompute", detail="stored envelope carries no audit block",
        )
    version = audit.get("schema_version")
    version_str = version if isinstance(version, str) else None
    if version_str == "2":
        return EnvelopeVerifyResult(
            schema_version=version_str, hash_ok=None, signature_ok=None,
            mode="links",
            detail=(
                "v2 records sealed the hash before tenant/actor/policy/argument "
                "fields were written (SR-01); verify by chain linkage only"
            ),
        )
    if version_str != "3":
        return EnvelopeVerifyResult(
            schema_version=version_str, hash_ok=False, signature_ok=None,
            mode="recompute", detail="unsupported envelope schema version",
        )
    stored_hash = audit.get("hash")
    if not isinstance(stored_hash, str) or not stored_hash.strip():
        return EnvelopeVerifyResult(
            schema_version=version_str, hash_ok=False, signature_ok=None,
            mode="recompute", detail="v3 record without an audit hash",
        )
    recomputed = recompute_stored_hash(stored)
    hash_ok = hmac.compare_digest(recomputed, stored_hash)

    signature = audit.get("signature")
    if signing_key:
        expected = hmac.new(
            signing_key.encode("utf-8"),
            stored_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signature_ok: bool | None = (
            isinstance(signature, str) and signature.isascii()
            and hmac.compare_digest(expected, signature)
        )
    else:
        signature_ok = None
    return EnvelopeVerifyResult(
        schema_version=version_str, hash_ok=hash_ok, signature_ok=signature_ok,
        mode="recompute",
        detail="" if hash_ok else "recomputed hash differs from stored hash",
    )
