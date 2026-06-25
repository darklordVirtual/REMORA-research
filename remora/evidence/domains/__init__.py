# Author: Stian Skogbrott
# License: Apache-2.0
"""Modular domain evidence providers for REMORA governance.

Each domain provider follows the same interface as CyberEvidenceProvider:
a ``triage()`` method that accepts domain-specific kwargs and returns a
domain-specific ``TriageResult`` that carries a unified four-verdict
governance action (ESCALATE / REPORT_READY / NEEDS_REVIEW / LIKELY_FALSE_POSITIVE).

Available domains
-----------------
cyber           CyberEvidenceProvider   — vulnerability management
ai_governance   AIGovernanceProvider    — AI/ML safety and EU AI Act
finance         FinanceEvidenceProvider — AML, sanctions, compliance
"""
from remora.evidence.domains.ai_governance import (
    AIGovernanceEvidenceProvider,
    AIGovernanceClassification,
    AIGovernanceTriageResult,
    AIGovernanceVerdict,
)
from remora.evidence.domains.finance import (
    FinanceEvidenceProvider,
    FinanceRiskClassification,
    FinanceTriageResult,
    FinanceVerdict,
)

DOMAIN_REGISTRY: dict[str, str] = {
    "cyber": "remora.evidence.cyber.CyberEvidenceProvider",
    "ai_governance": "remora.evidence.domains.ai_governance.AIGovernanceEvidenceProvider",
    "finance": "remora.evidence.domains.finance.FinanceEvidenceProvider",
}


def get_provider(domain: str) -> object:
    """Return a default-constructed provider for the given domain name."""
    if domain == "cyber":
        from remora.evidence.cyber import CyberEvidenceProvider
        return CyberEvidenceProvider()
    if domain == "ai_governance":
        return AIGovernanceEvidenceProvider()
    if domain == "finance":
        return FinanceEvidenceProvider()
    raise ValueError(f"Unknown domain {domain!r}. Available: {sorted(DOMAIN_REGISTRY)}")


__all__ = [
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
