# Author: Stian Skogbrott
# License: Apache-2.0
"""Governance Intelligence Layer — pre-policy enrichment of agent-action metadata.

Converts raw agent-action metadata into conservative, deterministic governance
signals *before* the policy engine runs:

- fail-closed normalisation (unknown is not safe)
- action-semantics extraction (no LLM calls)
- misspecification-risk inference
- causal-consequence (blast radius / expected loss) signals
- LDT-inspired policy-generalization (standing policy / fleet) risk

The layer prepares signals; ``remora.policy.RemoraDecisionEngine`` remains the
authoritative decision-maker. Enrichment may only strengthen risk, never
weaken it. Heuristic and research-grade — not production-certified, and not a
safety guarantee.
"""
from __future__ import annotations

from remora.governance_intelligence.action_semantics import (
    detect_blackmail,
    detect_coercion,
    extract_action_semantics,
)
from remora.governance_intelligence.causal_consequence import assess_causal_consequence
from remora.governance_intelligence.enrichment import (
    enrich_policy_observation,
    enrich_then_decide,
)
from remora.governance_intelligence.misspecification import assess_misspecification
from remora.governance_intelligence.normalization import (
    normalize_action_type,
    normalize_domain,
    normalize_environment,
    normalize_metadata,
    normalize_risk_tier,
    normalize_tool_name,
)
from remora.governance_intelligence.policy_generalization import (
    assess_policy_generalization,
)
from remora.governance_intelligence.types import (
    ActionSemantics,
    CausalConsequenceAssessment,
    GovernanceIntelligenceResult,
    MisspecificationAssessment,
    NormalizedMetadata,
    PolicyGeneralizationAssessment,
)

__all__ = [
    "ActionSemantics",
    "CausalConsequenceAssessment",
    "GovernanceIntelligenceResult",
    "MisspecificationAssessment",
    "NormalizedMetadata",
    "PolicyGeneralizationAssessment",
    "assess_causal_consequence",
    "assess_misspecification",
    "assess_policy_generalization",
    "detect_blackmail",
    "detect_coercion",
    "enrich_policy_observation",
    "enrich_then_decide",
    "extract_action_semantics",
    "normalize_action_type",
    "normalize_domain",
    "normalize_environment",
    "normalize_metadata",
    "normalize_risk_tier",
    "normalize_tool_name",
]
