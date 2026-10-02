# SPDX-License-Identifier: BUSL-1.1
"""Evidence admission layer (CoSAI §7.4) — public surface.

Deliberately small: five typed records, the trust configuration, the
admission report, and one operation. No convenience helpers, no authority.
"""
from remora.evidence.admission.admission import (
    FACT_NAMES,
    EvidenceAdmission,
    TrustConfig,
    admit_evidence,
)
from remora.evidence.admission.models import (
    CoverageAttestation,
    CoverageState,
    EstablishmentStatus,
    InvocationBindingProof,
    KnownGap,
    ManifestTrust,
    ObservationVantage,
    PriorCommitment,
    ProcessingStatus,
    ProducerCapabilityManifest,
    VantageIndependence,
)
from remora.evidence.admission.reasons import REASON_CODES

__all__ = [
    "FACT_NAMES",
    "REASON_CODES",
    "CoverageAttestation",
    "CoverageState",
    "EstablishmentStatus",
    "EvidenceAdmission",
    "InvocationBindingProof",
    "KnownGap",
    "ManifestTrust",
    "ObservationVantage",
    "PriorCommitment",
    "ProcessingStatus",
    "ProducerCapabilityManifest",
    "TrustConfig",
    "VantageIndependence",
    "admit_evidence",
]
