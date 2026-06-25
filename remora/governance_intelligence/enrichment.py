# Author: Stian Skogbrott
# License: Apache-2.0
"""Enrichment pipeline — raw action metadata → enriched PolicyObservation.

Order of operations:

1. Fail-closed normalisation of caller-supplied labels.
2. Deterministic action-semantics extraction from text/tool metadata.
3. Misspecification-risk inference (label vs semantics disagreement).
4. Causal-consequence signals (blast radius, expected loss).
5. Policy-generalization (standing policy / fleet) risk.
6. Strengthen-only merge into a new ``PolicyObservation``.

Merge invariants (asserted by tests/policy/test_governance_intelligence_never_weakens_policy.py):

- Risk is only ever strengthened: tiers never lowered, risk floats only raised,
  confidence floats only lowered, hard-block flags never cleared.
- ``"unknown"`` is never coerced to a safe value.
- The layer never produces the final ACCEPT/VERIFY/ABSTAIN/ESCALATE decision;
  ``RemoraDecisionEngine`` remains authoritative.
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from remora.governance_intelligence.action_semantics import extract_action_semantics
from remora.governance_intelligence.causal_consequence import assess_causal_consequence
from remora.governance_intelligence.misspecification import assess_misspecification
from remora.governance_intelligence.normalization import (
    MUTATING_ACTION_TYPES,
    UNKNOWN,
    normalize_action_type,
    normalize_metadata,
)
from remora.governance_intelligence.policy_generalization import (
    FLEET_EFFECT_RANK,
    assess_policy_generalization,
)
from remora.governance_intelligence.types import (
    RISK_TIER_RANK,
    GovernanceIntelligenceResult,
)
from remora.policy.observation import PolicyObservation

if TYPE_CHECKING:
    from remora.policy.decision_engine import RemoraDecisionEngine
    from remora.policy.report import DecisionReport

# Severity proxy for action types, aligned with the trap classifier's base
# scores (see remora/policy/trap_classifier.py). Used only to decide whether a
# candidate action_type is *more severe* than the supplied one — the merge
# never replaces an action type with a less severe one.
_FALLBACK_SEVERITY: dict[str, float] = {
    "read": 0.0,
    UNKNOWN: 0.05,
    "write": 0.40,
    "permission_change": 0.55,
    "network_change": 0.72,
    "irreversible_delete": 0.95,
    "data_exfiltration": 0.95,
    "prod_deploy": 0.75,
    "privilege_escalation": 0.90,
}


def _action_severity(action: str | None) -> float:
    from remora.policy.trap_classifier import _ACTION_TRAP_SCORES
    if action is None:
        return 0.05
    action = action.strip().lower()
    if action in _ACTION_TRAP_SCORES:
        return _ACTION_TRAP_SCORES[action]
    if action in _FALLBACK_SEVERITY:
        return _FALLBACK_SEVERITY[action]
    return 0.40 if action in MUTATING_ACTION_TYPES else 0.05


def _merge_risk_tier(
    original: str | None,
    normalized_tier: str,
    inferred_tier: str | None,
    *,
    expected_loss: float,
    safety_critical: bool,
) -> str | None:
    """Return the strengthened risk tier (never lower than supplied)."""
    candidates: list[str] = []
    if normalized_tier in RISK_TIER_RANK:
        candidates.append(normalized_tier)
    if inferred_tier in RISK_TIER_RANK:
        candidates.append(inferred_tier)  # type: ignore[arg-type]
    if expected_loss >= 0.80:
        candidates.append("high")
    if safety_critical:
        candidates.append("critical")
    if not candidates:
        # Unknown stays unknown — never coerced to "low".
        return original
    merged = max(candidates, key=lambda t: RISK_TIER_RANK[t])
    if normalized_tier not in RISK_TIER_RANK and merged != "critical":
        # Supplied tier is unknown. Resolving it to anything below "critical"
        # would *disable* the engine's unknown-risk-tier gate, which is a
        # weakening ("unknown" routes mutating/prod actions to VERIFY; a
        # resolved low/medium/high tier may reach ACCEPT paths). "critical"
        # is the only tier whose floor (unconditional VERIFY) is at least as
        # strict as the unknown gate, so it is the only allowed resolution.
        return original
    return merged


def _merge_action_type(
    original: str | None,
    normalized_action: str,
    inferred_action: str,
    *,
    mismatch_flagged: bool,
) -> str | None:
    """Pick the most severe justified action type. Never picks a less severe one."""
    candidates: list[str] = []
    if original:
        candidates.append(original.strip().lower())
    if normalized_action != UNKNOWN:
        candidates.append(normalized_action)
    supplied_unknown = normalized_action == UNKNOWN
    if inferred_action != UNKNOWN and (supplied_unknown or mismatch_flagged):
        candidates.append(inferred_action)
    if not candidates:
        return original
    return max(candidates, key=_action_severity)


def _merge_fleet_effect(existing: str | None, assessed: str | None) -> str | None:
    if existing is None:
        return assessed
    if assessed is None:
        return existing
    return max(existing, assessed, key=lambda e: FLEET_EFFECT_RANK.get(e, 3))


def _safe_replace(
    obs: PolicyObservation, updates: dict[str, Any]
) -> tuple[PolicyObservation, list[str]]:
    """Apply *updates* via dataclasses.replace, skipping unknown fields.

    Future-proofing: if a target field is removed from PolicyObservation the
    enrichment layer degrades to a warning instead of crashing.
    """
    warnings: list[str] = []
    known = set(obs.__dataclass_fields__)
    applicable = {k: v for k, v in updates.items() if k in known}
    for k in updates.keys() - known:
        warnings.append(f"PolicyObservation has no field '{k}'; signal dropped")
    if not applicable:
        return obs, warnings
    return dataclasses.replace(obs, **applicable), warnings


def enrich_policy_observation(
    obs: PolicyObservation,
    *,
    tool_name: str | None = None,
    tool_arguments: dict[str, Any] | None = None,
    similar_action_seen_count: int | None = None,
    tenant_id: str | None = None,
    enable_policy_generalization: bool = True,
) -> GovernanceIntelligenceResult:
    """Run the full Governance Intelligence pipeline over one observation.

    Returns a :class:`GovernanceIntelligenceResult` whose
    ``enriched_observation`` has governance fields populated under
    strengthen-only rules. The input observation is never modified.
    """
    warnings: list[str] = []

    # 1. Fail-closed normalisation
    normalized = normalize_metadata(
        risk_tier=obs.risk_tier,
        action_type=obs.action_type,
        target_environment=obs.target_environment,
        domain=obs.domain,
        tool_name=tool_name,
    )
    if normalized.metadata_unknown_fields:
        warnings.append(
            "metadata unknown/unrecognised: "
            + ", ".join(normalized.metadata_unknown_fields)
        )

    # 2. Action semantics
    semantics = extract_action_semantics(
        obs.question,
        tool_name=tool_name,
        tool_arguments=tool_arguments,
        question=None,
    )

    # 3. Misspecification
    misspecification = assess_misspecification(
        normalized,
        semantics,
        tool_arguments=tool_arguments,
        rollback_available=obs.rollback_available,
        text=obs.question,
    )

    # 4. Causal consequence
    causal = assess_causal_consequence(
        normalized, semantics, misspecification, tenant_id=tenant_id
    )

    # 5. Policy generalization
    effective_count = similar_action_seen_count
    if obs.similar_action_seen_count is not None:
        effective_count = max(effective_count or 0, obs.similar_action_seen_count)
    generalization = None
    if enable_policy_generalization:
        generalization = assess_policy_generalization(
            normalized, semantics, causal,
            similar_action_seen_count=effective_count,
        )

    # 6. Strengthen-only merge
    mismatch_flagged = bool(misspecification.classification_alternatives)
    merged_tier = _merge_risk_tier(
        obs.risk_tier, normalized.risk_tier, semantics.inferred_risk_tier,
        expected_loss=causal.expected_loss,
        safety_critical=semantics.safety_critical,
    )
    merged_action = _merge_action_type(
        obs.action_type, normalized.action_type, semantics.inferred_action_type,
        mismatch_flagged=mismatch_flagged,
    )

    # classification_alternatives feeds the engine's alternative gates, so it
    # carries action-type strings. Only populated on genuine mismatch.
    alt_types = [
        str(d.get("action_type")) for d in misspecification.classification_alternatives
        if d.get("action_type")
    ]
    merged_alternatives = list(obs.classification_alternatives or [])
    for alt in alt_types:
        if alt not in merged_alternatives:
            merged_alternatives.append(alt)

    def _min_opt(existing: float | None, assessed: float) -> float:
        return assessed if existing is None else min(existing, assessed)

    def _max_opt(existing: float | None, assessed: float) -> float:
        return assessed if existing is None else max(existing, assessed)

    state_transition_uncertain = (
        obs.state_transition_uncertain
        or misspecification.state_transition_uncertain
        or (causal.state_change_expected and causal.causal_uncertainty >= 0.70)
    )

    updates: dict[str, Any] = {
        "risk_tier": merged_tier,
        "action_type": merged_action,
        "domain": obs.domain or semantics.inferred_domain,
        "classification_confidence": _min_opt(
            obs.classification_confidence, misspecification.classification_confidence
        ),
        "model_misspecification_risk": _max_opt(
            obs.model_misspecification_risk,
            misspecification.model_misspecification_risk,
        ),
        "classification_alternatives": merged_alternatives or None,
        "environment_confidence": _min_opt(
            obs.environment_confidence, misspecification.environment_confidence
        ),
        "environment_mismatch_detected": (
            obs.environment_mismatch_detected
            or misspecification.environment_mismatch_detected
        ),
        "state_transition_uncertain": state_transition_uncertain,
        "coercion_detected": obs.coercion_detected or semantics.coercion_signal,
        "blackmail_pattern_detected": (
            obs.blackmail_pattern_detected or semantics.blackmail_signal
        ),
    }
    if generalization is not None:
        updates["policy_generalization_risk"] = _max_opt(
            obs.policy_generalization_risk,
            generalization.policy_generalization_risk,
        )
        updates["fleet_level_effect"] = _merge_fleet_effect(
            obs.fleet_level_effect, generalization.fleet_level_effect
        )
        if effective_count is not None:
            updates["similar_action_seen_count"] = effective_count

    enriched, replace_warnings = _safe_replace(obs, updates)
    warnings.extend(replace_warnings)
    warnings.extend(misspecification.reasons)

    explanation_parts = [
        f"normalized: tier={normalized.risk_tier}, action={normalized.action_type}, "
        f"env={normalized.target_environment}",
        f"semantics: {semantics.inferred_action_type} "
        f"(tier={semantics.inferred_risk_tier}, confidence={semantics.confidence:.2f})",
        f"misspecification_risk={misspecification.model_misspecification_risk:.2f}",
        f"blast_radius={causal.blast_radius}, expected_loss={causal.expected_loss:.2f}",
    ]
    if generalization is not None:
        explanation_parts.append(
            f"policy_generalization_risk={generalization.policy_generalization_risk:.2f}, "
            f"fleet_level_effect={generalization.fleet_level_effect}"
        )

    return GovernanceIntelligenceResult(
        normalized=normalized,
        semantics=semantics,
        misspecification=misspecification,
        causal=causal,
        generalization=generalization,
        enriched_observation=enriched,
        warnings=tuple(warnings),
        explanation="; ".join(explanation_parts),
    )


def enrich_then_decide(
    obs: PolicyObservation,
    *,
    engine: "RemoraDecisionEngine | None" = None,
    tool_name: str | None = None,
    tool_arguments: dict[str, Any] | None = None,
    similar_action_seen_count: int | None = None,
    tenant_id: str | None = None,
    enable_policy_generalization: bool = True,
    return_intelligence: bool = False,
) -> "DecisionReport | tuple[DecisionReport, GovernanceIntelligenceResult]":
    """Enrich *obs* and route it through the (authoritative) policy engine.

    This is the optional integration path: callers that want governance
    intelligence opt in here; ``RemoraDecisionEngine.decide()`` itself is
    unchanged and remains fully backwards-compatible.
    """
    from remora.policy.decision_engine import RemoraDecisionEngine

    result = enrich_policy_observation(
        obs,
        tool_name=tool_name,
        tool_arguments=tool_arguments,
        similar_action_seen_count=similar_action_seen_count,
        tenant_id=tenant_id,
        enable_policy_generalization=enable_policy_generalization,
    )
    report = (engine or RemoraDecisionEngine()).decide(result.enriched_observation)
    if return_intelligence:
        return report, result
    return report


__all__ = [
    "enrich_policy_observation",
    "enrich_then_decide",
    "normalize_action_type",
]
