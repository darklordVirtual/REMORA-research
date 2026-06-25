"""Evidence-grounded routing for critical-phase oracle decisions.

This package provides an independent evidence channel that can break
oracle-consensus groupthink in the critical phase.  When oracle trust
scores anti-correlate with correctness (see NEGATIVE_RESULTS.md, Finding 3),
retrieved-evidence quality becomes the primary routing signal.
"""
from remora.evidence.evidence_types import (
    EvidenceDecision,
    EvidenceLabel,
    EvidenceSignal,
)
from remora.evidence.evidence_router import CriticalEvidenceRouter
from remora.evidence.provider import (
    EvidenceProvider,
    EvidenceProviderResult,
    OracleProxyEvidenceProvider,
)
from remora.evidence.static_jsonl_provider import StaticJsonlEvidenceProvider
from remora.evidence.rag_provider import (
    InMemoryRetrievalBackend,
    JaccardNLIScorer,
    NLIResult,
    RAGEvidenceProvider,
    RAGProviderResult,
    RetrievalBackend,
    RetrievedPassage,
)
from remora.evidence.cyber import (
    CyberEvidenceMatch,
    CyberEvidenceProvider,
    CyberEvidenceRecord,
    CyberTriageResult,
    CyberTriageVerdict,
    DefensivePoCPlan,
    ExploitClassification,
    PoCReadiness,
)
from remora.evidence.finding_envelope import (
    CyberFindingEnvelope,
    DisclosureLedger,
    DisclosureStatus,
    ResearchArtifactRef,
    TargetScanProfile,
)
from remora.evidence.benchmark import (
    AllDomainsBenchmarkResult,
    BenchmarkCase,
    BenchmarkCaseResult,
    DomainBenchmarkResult,
    DomainBenchmarkRunner,
    combine_results,
)
from remora.evidence.domains import (
    AIGovernanceClassification,
    AIGovernanceEvidenceProvider,
    AIGovernanceTriageResult,
    AIGovernanceVerdict,
    FinanceEvidenceProvider,
    FinanceRiskClassification,
    FinanceTriageResult,
    FinanceVerdict,
    DOMAIN_REGISTRY,
    get_provider,
)

__all__ = [
    "CriticalEvidenceRouter",
    "EvidenceDecision",
    "EvidenceProvider",
    "EvidenceProviderResult",
    "EvidenceLabel",
    "EvidenceSignal",
    "InMemoryRetrievalBackend",
    "JaccardNLIScorer",
    "NLIResult",
    "OracleProxyEvidenceProvider",
    "RAGEvidenceProvider",
    "RAGProviderResult",
    "RetrievalBackend",
    "RetrievedPassage",
    "StaticJsonlEvidenceProvider",
    # Cyber evidence
    "CyberEvidenceMatch",
    "CyberEvidenceProvider",
    "CyberEvidenceRecord",
    "CyberTriageResult",
    "CyberTriageVerdict",
    "DefensivePoCPlan",
    "ExploitClassification",
    "PoCReadiness",
    # GO-STAR bridge types
    "CyberFindingEnvelope",
    "DisclosureLedger",
    "DisclosureStatus",
    "ResearchArtifactRef",
    "TargetScanProfile",
    # Cross-domain benchmark
    "AllDomainsBenchmarkResult",
    "BenchmarkCase",
    "BenchmarkCaseResult",
    "DomainBenchmarkResult",
    "DomainBenchmarkRunner",
    "combine_results",
    # Domain providers
    "AIGovernanceClassification",
    "AIGovernanceEvidenceProvider",
    "AIGovernanceTriageResult",
    "AIGovernanceVerdict",
    "FinanceEvidenceProvider",
    "FinanceRiskClassification",
    "FinanceTriageResult",
    "FinanceVerdict",
    "DOMAIN_REGISTRY",
    "get_provider",
]
