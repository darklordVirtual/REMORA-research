# Author: Stian Skogbrott
# License: Apache-2.0
"""LDT-*inspired* policy-generalization risk.

Asks the standing-policy question: *if REMORA ACCEPTed this class of action
repeatedly — across similar agents, tenants, and future cases — would that
standing policy remain safe?* A single DNS edit may be fine; a policy of
auto-accepting DNS edits is systemic risk.

This is a deterministic heuristic projection, not Logical Decision Theory:
there is no logical-counterfactual machinery, only conservative rules over
action class, environment, and observed repetition counts.
"""
from __future__ import annotations

from remora.governance_intelligence.normalization import UNKNOWN
from remora.governance_intelligence.types import (
    ActionSemantics,
    CausalConsequenceAssessment,
    NormalizedMetadata,
    PolicyGeneralizationAssessment,
)

# Action classes whose repetition is inherently systemic: they reshape shared
# infrastructure or security posture for everyone behind them.
_SYSTEMIC_ACTIONS: frozenset[str] = frozenset({
    "dns_change", "firewall_change", "network_change", "network_config",
    "disable_security", "privilege_escalation", "prod_deploy",
})

_EXTERNAL_ACTIONS: frozenset[str] = frozenset({
    "bulk_email", "external_publish", "webhook_trigger",
    "financial_write", "execute_transfer", "data_exfiltration",
})

_PERMISSION_ACTIONS: frozenset[str] = frozenset({
    "grant_permission", "revoke_permission", "permission_change", "unlock_access",
})

# Fleet-effect severity for strengthen-only merges (enrichment uses this).
FLEET_EFFECT_RANK: dict[str, int] = {
    "none": 0, "local": 1, "tenant": 2, "unknown": 3,
    "systemic": 4, "critical_mass": 5,
}

REPEATED_THRESHOLD = 3          # repetition becomes a *pattern*
FLOOD_THRESHOLD = 10            # repetition becomes a risk multiplier


def assess_policy_generalization(
    normalized: NormalizedMetadata,
    semantics: ActionSemantics,
    causal: CausalConsequenceAssessment,
    *,
    similar_action_seen_count: int | None = None,
) -> PolicyGeneralizationAssessment:
    """Project this action class to a standing policy and score the risk."""
    reasons: list[str] = []
    count = max(0, similar_action_seen_count or 0)
    repeated = count >= REPEATED_THRESHOLD

    action = (
        normalized.action_type
        if normalized.action_type != UNKNOWN
        else semantics.inferred_action_type
    )
    mutating = normalized.mutating_action or semantics.mutating
    destructive = normalized.destructive_or_irreversible or semantics.destructive
    prod_like = normalized.production_like_environment or semantics.production_signal
    critical = (
        normalized.risk_tier == "critical"
        or semantics.inferred_risk_tier == "critical"
    )

    # ── Base risk and fleet effect by action class ──────────────────────────
    if not mutating and action in ("read", UNKNOWN) and not semantics.external_side_effect:
        if action == "read":
            risk, effect = 0.05, "none"
            reasons.append("read-only class: standing accept policy is low risk")
        else:
            risk, effect = 0.40, UNKNOWN
            reasons.append("unknown action class: standing policy effect cannot be bounded")
    elif action in _SYSTEMIC_ACTIONS:
        risk, effect = 0.85, "systemic"
        reasons.append(f"repeatable '{action}' reshapes shared infrastructure: systemic")
    elif action in _EXTERNAL_ACTIONS or semantics.external_side_effect:
        risk, effect = 0.65, "tenant"
        reasons.append("repeated external sends generalize to tenant/external exposure")
    elif action in _PERMISSION_ACTIONS:
        risk, effect = 0.60, "tenant"
        reasons.append("repeated permission changes erode least-privilege over time")
    elif destructive and prod_like:
        risk, effect = 0.80, "systemic"
        reasons.append("standing policy of destructive production writes is systemic")
    elif mutating and prod_like:
        risk, effect = 0.60, "tenant"
        reasons.append("repeated production writes accumulate fleet-level drift")
    elif mutating and normalized.target_environment == UNKNOWN:
        risk, effect = 0.55, UNKNOWN
        reasons.append("mutating class with unknown environment: effect unknown")
    elif mutating:
        risk, effect = 0.30, "local"
        reasons.append("non-production mutation: local standing-policy effect")
    else:
        risk, effect = 0.20, "local"
        reasons.append("low-impact class: local standing-policy effect")

    # ── Repetition modifiers ────────────────────────────────────────────────
    if repeated and mutating:
        risk = max(risk, 0.55)
        reasons.append(f"mutating action repeated {count} times")
    if count > FLOOD_THRESHOLD and mutating:
        risk = max(risk, 0.75)
        reasons.append(f"similar mutating action seen {count} times (> {FLOOD_THRESHOLD})")
        if effect in ("local", "tenant"):
            effect = "tenant" if effect == "local" else "systemic"
    if critical and repeated:
        risk = max(risk, 0.85)
        effect = "systemic"
        reasons.append("critical-tier action repeated: systemic standing-policy risk")
    if repeated and mutating and normalized.target_environment == UNKNOWN:
        risk = max(risk, 0.80)
        effect = "systemic" if effect != UNKNOWN else UNKNOWN
        reasons.append("repeated mutation with unknown environment")

    standing_policy_safe = risk < 0.50 and effect in ("none", "local")

    counterfactual = (
        f"If REMORA ACCEPTed every '{action}' action of this class as standing "
        f"policy (seen {count} similar case(s)), the fleet-level effect would be "
        f"'{effect}' with generalization risk {min(risk, 1.0):.2f}."
    )

    return PolicyGeneralizationAssessment(
        policy_generalization_risk=round(min(risk, 1.0), 4),
        similar_action_seen_count=count,
        repeated_action_pattern=repeated,
        fleet_level_effect=effect,
        standing_policy_safe=standing_policy_safe,
        generalized_counterfactual=counterfactual,
        reasons=tuple(reasons),
    )
