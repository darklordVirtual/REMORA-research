# Author: Stian Skogbrott
# License: Apache-2.0
"""Dataclasses for the Governance Intelligence Layer.

All types are frozen, deterministic value objects. They carry *signals*, not
decisions: the policy engine (``RemoraDecisionEngine``) remains authoritative.

Severity vocabularies
---------------------
Risk tiers:        ``low < medium < high < critical``; anything else is ``unknown``.
Blast radii:       ``none, local, tenant, system, external, production, unknown``.
Fleet effects:     ``none, local, tenant, systemic, unknown``
                   (``critical_mass`` is accepted from callers and preserved).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from remora.policy.observation import PolicyObservation

# Canonical risk-tier ordering. "unknown" is intentionally NOT in this map:
# unknown is not a rank, it is the absence of one, and must never be coerced
# to "low" (see docs/research/governance_intelligence_layer.md).
RISK_TIER_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}

BLAST_RADII: frozenset[str] = frozenset(
    {"none", "local", "tenant", "system", "external", "production", "unknown"}
)

FLEET_EFFECTS: frozenset[str] = frozenset(
    {"none", "local", "tenant", "systemic", "unknown"}
)


@dataclass(frozen=True)
class NormalizedMetadata:
    """Fail-closed normalisation of caller-supplied action metadata.

    ``unknown`` values are explicit, never silently coerced to a safe value.
    """

    risk_tier: str                    # low | medium | high | critical | unknown
    action_type: str                  # canonical action type or "unknown"
    target_environment: str           # prod | staging | dev | unknown
    domain: str | None                # lowercased domain, or None when absent
    tool_name: str | None             # lowercased tool name, or None when absent

    # Fail-closed derived fields
    metadata_complete: bool
    metadata_unknown_fields: tuple[str, ...]
    mutating_action: bool
    production_like_environment: bool
    destructive_or_irreversible: bool

    # Raw values as supplied by the caller (for audit transparency)
    raw_risk_tier: str | None = None
    raw_action_type: str | None = None
    raw_target_environment: str | None = None


@dataclass(frozen=True)
class ActionSemantics:
    """Deterministic semantic signals extracted from action text and tool metadata."""

    inferred_action_type: str
    inferred_domain: str | None
    inferred_risk_tier: str | None
    mutating: bool
    destructive: bool
    irreversible: bool
    external_side_effect: bool
    credential_or_secret_risk: bool
    bulk_scope: bool
    production_signal: bool
    confidence: float
    matched_patterns: tuple[str, ...]
    explanation: str
    # Coercion signals (consumed by enrichment → PolicyObservation hard blocks)
    coercion_signal: bool = False
    blackmail_signal: bool = False
    safety_critical: bool = False


@dataclass(frozen=True)
class MisspecificationAssessment:
    """Deterministic misspecification-risk inference. No LLM calls."""

    classification_confidence: float
    model_misspecification_risk: float
    classification_alternatives: tuple[dict[str, Any], ...]
    environment_confidence: float
    environment_mismatch_detected: bool
    objective_ambiguity: float
    possible_objectives: tuple[str, ...]
    state_transition_uncertain: bool
    rollback_available: bool | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CausalConsequenceAssessment:
    """Causal-consequence *inspired* governance signals.

    This is a conservative heuristic blast-radius model, not causal decision
    theory: it estimates what executing the action is expected to touch, not
    a full interventional distribution.
    """

    state_change_expected: bool
    affected_assets: tuple[str, ...]
    blast_radius: str                 # one of BLAST_RADII
    rollback_available: bool | None
    irreversible: bool
    downstream_effects: tuple[str, ...]
    causal_uncertainty: float
    expected_loss: float
    if_executed: str
    if_blocked: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PolicyGeneralizationAssessment:
    """LDT-*inspired* standing-policy risk: would repeatedly ACCEPTing this
    class of action across agents/tenants/time remain safe?

    Heuristic and deterministic — not Logical Decision Theory.
    """

    policy_generalization_risk: float
    similar_action_seen_count: int
    repeated_action_pattern: bool
    fleet_level_effect: str           # one of FLEET_EFFECTS
    standing_policy_safe: bool
    generalized_counterfactual: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class GovernanceIntelligenceResult:
    """Full output of the enrichment pipeline.

    ``enriched_observation`` is a new ``PolicyObservation`` with governance
    fields populated under strengthen-only merge rules. The original
    observation is never mutated, and the layer never makes the final
    ACCEPT/VERIFY/ABSTAIN/ESCALATE decision.
    """

    normalized: NormalizedMetadata
    semantics: ActionSemantics
    misspecification: MisspecificationAssessment
    causal: CausalConsequenceAssessment
    generalization: PolicyGeneralizationAssessment | None
    enriched_observation: "PolicyObservation"
    warnings: tuple[str, ...] = field(default=())
    explanation: str = ""
