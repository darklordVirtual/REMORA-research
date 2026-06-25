# Author: Stian Skogbrott
# License: Apache-2.0
"""Causal-consequence *inspired* gating signals.

Estimates what executing a proposed action is expected to touch: blast radius,
irreversibility, downstream effects, and a coarse expected-loss score. This is
a deterministic governance heuristic — not full causal decision theory and not
a learned world model. Unknown environment + mutation yields ``blast_radius=
"unknown"`` with high causal uncertainty, because unknown is not safe.

Expected-loss bands (documented contract, asserted in tests):

- read-only:                                   <= 0.1
- tenant-scoped write:                          0.2 – 0.4
- production mutation:                          0.5 – 0.8
- destructive prod / security-disable / financial transfer: >= 0.8
"""
from __future__ import annotations

from remora.governance_intelligence.normalization import UNKNOWN
from remora.governance_intelligence.types import (
    ActionSemantics,
    CausalConsequenceAssessment,
    MisspecificationAssessment,
    NormalizedMetadata,
)

_INFRA_ACTIONS: frozenset[str] = frozenset({
    "dns_change", "firewall_change", "network_change", "network_config",
    "disable_security", "config_overwrite", "prod_deploy",
})

_EXTERNAL_ACTIONS: frozenset[str] = frozenset({
    "financial_write", "execute_transfer", "bulk_email", "external_publish",
    "webhook_trigger", "data_exfiltration",
})


def _effective_action(normalized: NormalizedMetadata, semantics: ActionSemantics) -> str:
    if normalized.action_type != UNKNOWN:
        return normalized.action_type
    return semantics.inferred_action_type


def assess_causal_consequence(
    normalized: NormalizedMetadata,
    semantics: ActionSemantics,
    misspecification: MisspecificationAssessment,
    *,
    tenant_id: str | None = None,
) -> CausalConsequenceAssessment:
    """Derive conservative blast-radius and expected-loss signals."""
    reasons: list[str] = []
    affected: list[str] = []
    downstream: list[str] = []

    action = _effective_action(normalized, semantics)
    mutating = normalized.mutating_action or semantics.mutating
    destructive = normalized.destructive_or_irreversible or semantics.destructive
    env = normalized.target_environment
    prod_like = normalized.production_like_environment or semantics.production_signal

    irreversible = semantics.irreversible or (
        destructive and misspecification.rollback_available is None
    )

    # ── Read-only fast path ─────────────────────────────────────────────────
    if not mutating and action in ("read", UNKNOWN) and not semantics.external_side_effect:
        if action == "read":
            blast = "none" if env in ("dev", "staging") else "local"
            uncertainty = 0.10
            loss = 0.05
            reasons.append("read-only action: no state change expected")
        else:
            # Unknown action with no detected mutation: unknown is not safe,
            # but absent any mutation signal the expected loss stays modest.
            blast = UNKNOWN
            uncertainty = 0.70
            loss = 0.30
            reasons.append("action semantics unknown: blast radius cannot be bounded")
        return CausalConsequenceAssessment(
            state_change_expected=False,
            affected_assets=(),
            blast_radius=blast,
            rollback_available=misspecification.rollback_available,
            irreversible=False,
            downstream_effects=(),
            causal_uncertainty=uncertainty,
            expected_loss=loss,
            if_executed="no state change expected; informational output only",
            if_blocked="information unavailable to the agent; no state impact",
            reasons=tuple(reasons),
        )

    # ── Mutating paths ──────────────────────────────────────────────────────
    uncertainty = 0.30
    if env == UNKNOWN:
        uncertainty = max(uncertainty, 0.80)
        reasons.append("environment unknown for mutating action: high causal uncertainty")
    if action == UNKNOWN:
        uncertainty = max(uncertainty, 0.70)
        reasons.append("action type unknown: consequence model is unreliable")
    if misspecification.model_misspecification_risk >= 0.65:
        uncertainty = max(uncertainty, 0.70)
        reasons.append("metadata/semantics disagreement raises causal uncertainty")

    # Blast radius — most severe matching category wins.
    if action in _EXTERNAL_ACTIONS or semantics.external_side_effect:
        blast = "external"
        affected.append("external recipients/counterparties")
        downstream.append("effects leave the organisation boundary and cannot be recalled")
        reasons.append("external side effect: blast radius external")
    elif destructive and (prod_like or env == UNKNOWN):
        blast = "production"
        affected.append("production data/services")
        downstream.append("dependent services and users of the affected data")
        reasons.append("destructive action with production (or unknown) environment")
    elif action in _INFRA_ACTIONS:
        blast = "production" if prod_like else "system"
        affected.append("shared network/security infrastructure")
        downstream.append("all tenants/services relying on the changed infrastructure")
        reasons.append("infrastructure mutation: system-wide reach")
    elif env == UNKNOWN:
        blast = UNKNOWN
        reasons.append("mutating action with unknown environment: blast radius unknown")
    elif prod_like:
        blast = "production"
        affected.append("production state")
        reasons.append("mutation targets a production-like environment")
    elif tenant_id is not None:
        blast = "tenant"
        affected.append(f"tenant {tenant_id}")
        reasons.append("mutation scoped to a single tenant")
    else:
        blast = "local"
        reasons.append("mutation with no production/tenant/external signals")

    if semantics.bulk_scope:
        # Bulk scope widens the radius one step (local→tenant, tenant→system).
        widen = {"local": "tenant", "tenant": "system", "system": "production"}
        blast = widen.get(blast, blast)
        downstream.append("bulk scope multiplies the number of affected assets")
        reasons.append("bulk scope widens blast radius")

    if action in ("dns_change", "firewall_change", "disable_security"):
        downstream.append("availability/security posture of dependent systems changes")
    if semantics.credential_or_secret_risk:
        downstream.append("credential exposure can enable follow-on unauthorized actions")
        affected.append("credential material")

    # ── Expected loss ───────────────────────────────────────────────────────
    if destructive and (prod_like or env == UNKNOWN):
        loss = 0.85
    elif action in ("disable_security", "financial_write", "execute_transfer",
                    "data_exfiltration"):
        loss = 0.85
    elif semantics.safety_critical:
        loss = 0.90
    elif blast in ("production",):
        loss = 0.65
    elif blast in ("system", "external", UNKNOWN):
        loss = 0.60
    elif blast == "tenant":
        loss = 0.35
    else:
        loss = 0.25

    if_executed = (
        f"state change with blast radius '{blast}'"
        + ("; not reversible with current knowledge" if irreversible else "")
    )
    if_blocked = (
        "action is deferred to review; intended effect is delayed but no state is lost"
    )

    return CausalConsequenceAssessment(
        state_change_expected=True,
        affected_assets=tuple(dict.fromkeys(affected)),
        blast_radius=blast,
        rollback_available=misspecification.rollback_available,
        irreversible=irreversible,
        downstream_effects=tuple(dict.fromkeys(downstream)),
        causal_uncertainty=round(uncertainty, 4),
        expected_loss=round(loss, 4),
        if_executed=if_executed,
        if_blocked=if_blocked,
        reasons=tuple(reasons),
    )
