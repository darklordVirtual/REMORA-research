# SPDX-License-Identifier: BUSL-1.1
"""Read-only evidence admission and offline verification for integrators."""
from collections.abc import Mapping
from typing import Any

from remora.evidence.admission import (
    CoverageAttestation, CoverageState, EstablishmentStatus, EvidenceAdmission,
    InvocationBindingProof, KnownGap, ManifestTrust, ObservationVantage,
    PriorCommitment, ProcessingStatus, ProducerCapabilityManifest, TrustConfig,
    VantageIndependence, admit_evidence, process_evidence_payload,
)

__all__ = [
    "CoverageAttestation", "CoverageState", "EstablishmentStatus", "EvidenceAdmission",
    "InvocationBindingProof", "KnownGap", "ManifestTrust", "ObservationVantage",
    "PriorCommitment", "ProcessingStatus", "ProducerCapabilityManifest", "TrustConfig",
    "VantageIndependence", "admit_evidence", "process_evidence_payload",
    "verify_grant_signature",
]


def verify_grant_signature(grant: Mapping[str, Any], *, public_key: str) -> bool:
    """Check a v3 grant against an independently supplied key, for offline evidence.

    This checks authorship only. Expiry, invocation binding and single use belong
    to the live redeemer. No process signing configuration is consulted.
    """
    from remora.crypto import ALGORITHM, Signature, SignatureDomain, VerificationKey, verify
    from remora.enforcement.token import FORMAT_V3, PolicyDecisionToken

    try:
        token = PolicyDecisionToken.from_dict(dict(grant))
        if token.format != FORMAT_V3 or token.is_signed is not True:
            return False
        domain = SignatureDomain.POLICY_GRANT_ASYMMETRIC
        key = VerificationKey.from_text(public_key, {domain})
        signature = Signature(ALGORITHM, domain.value, token.kid, token.signature)
        return verify(domain, token.signed_payload(), signature, [key]).ok
    except (TypeError, ValueError, AttributeError):
        return False
