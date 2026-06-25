# Author: Stian Skogbrott
# License: Apache-2.0
"""Fail-closed normalisation of caller-supplied action metadata.

Design rule: **unknown is not safe**. Missing, empty, or unrecognised values
normalise to the explicit string ``"unknown"`` (never to ``"low"`` / ``"dev"``),
and the unknown-ness is surfaced in ``metadata_unknown_fields`` so downstream
gates and audit consumers can see exactly which labels were absent.

This module is deterministic and dependency-free.
"""
from __future__ import annotations

from remora.governance_intelligence.types import RISK_TIER_RANK, NormalizedMetadata

UNKNOWN = "unknown"

# ── Risk tier ────────────────────────────────────────────────────────────────

_KNOWN_RISK_TIERS: frozenset[str] = frozenset(RISK_TIER_RANK)

# ── Target environment ───────────────────────────────────────────────────────

_ENV_ALIASES: dict[str, str] = {
    "prod": "prod", "production": "prod", "live": "prod",
    "stage": "staging", "staging": "staging", "test": "staging",
    "dev": "dev", "local": "dev", "development": "dev",
}

# ── Action type ──────────────────────────────────────────────────────────────

# Aliases → canonical action types understood by the policy engine and the
# trap classifier. Unknown/missing → "unknown" (fail-closed; never "read").
_ACTION_ALIASES: dict[str, str] = {
    # read family
    "read": "read", "get": "read", "list": "read", "fetch": "read",
    "query": "read", "inspect": "read", "view": "read", "describe": "read",
    # write family
    "create": "write", "insert": "write", "write": "write",
    "update": "write", "patch": "write", "modify": "write",
    # destructive
    "delete": "destructive_write", "drop": "destructive_write",
    "truncate": "destructive_write", "wipe": "destructive_write",
    "destructive_write": "destructive_write",
    "irreversible_delete": "irreversible_delete",
    "bulk_delete": "bulk_delete",
    # shell
    "shell": "shell_execute", "exec": "shell_execute",
    "run_command": "shell_execute", "shell_execute": "shell_execute",
    "script_execute": "script_execute", "code_execute": "code_execute",
    # network / infrastructure
    "dns": "dns_change", "update_dns": "dns_change",
    "cloudflare_dns": "dns_change", "dns_change": "dns_change",
    "firewall": "firewall_change", "security_rule": "firewall_change",
    "firewall_change": "firewall_change", "network_change": "network_change",
    "network_config": "network_config", "config_change": "config_change",
    "config_overwrite": "config_overwrite",
    # permissions
    "grant_access": "grant_permission", "add_user": "grant_permission",
    "invite_user": "grant_permission", "grant_permission": "grant_permission",
    "revoke_access": "revoke_permission", "remove_user": "revoke_permission",
    "revoke_permission": "revoke_permission",
    "permission_change": "permission_change",
    "privilege_escalation": "privilege_escalation",
    # financial
    "transfer": "financial_write", "payment": "financial_write",
    "payout": "financial_write", "financial_write": "financial_write",
    "execute_transfer": "execute_transfer",
    # other canonical passthroughs
    "production_write": "production_write", "emergency_write": "emergency_write",
    "prod_deploy": "prod_deploy", "disable_security": "disable_security",
    "unlock_access": "unlock_access", "bulk_email": "bulk_email",
    "external_publish": "external_publish", "webhook_trigger": "webhook_trigger",
    "data_exfiltration": "data_exfiltration",
}

# Canonical action types that mutate state. Mirrors (and extends) the engine's
# _MUTATING_TYPES so the derived flags here are at least as conservative.
MUTATING_ACTION_TYPES: frozenset[str] = frozenset({
    "write", "shell_write", "delete", "destructive_write", "irreversible_delete",
    "bulk_delete", "permission_change", "config_change", "config_overwrite",
    "production_write", "emergency_write", "financial_write", "execute_transfer",
    "network_change", "network_config", "prod_deploy", "data_exfiltration",
    "shell_execute", "script_execute", "code_execute",
    "dns_change", "firewall_change", "disable_security", "unlock_access",
    "grant_permission", "revoke_permission", "privilege_escalation",
    "bulk_email", "external_publish", "webhook_trigger",
})

# Canonical action types that are destructive or practically irreversible.
DESTRUCTIVE_ACTION_TYPES: frozenset[str] = frozenset({
    "destructive_write", "irreversible_delete", "bulk_delete", "delete",
    "disable_security", "financial_write", "execute_transfer",
    "data_exfiltration", "emergency_write",
})

READ_ONLY_ACTION_TYPES: frozenset[str] = frozenset({"read"})


def normalize_risk_tier(value: str | None) -> str:
    """Normalise a risk tier; unrecognised / missing / typo → ``"unknown"``.

    Never maps an unknown value to ``"low"``.
    """
    if value is None:
        return UNKNOWN
    cleaned = value.strip().lower()
    return cleaned if cleaned in _KNOWN_RISK_TIERS else UNKNOWN


def normalize_environment(value: str | None) -> str:
    """Normalise a target environment; unrecognised / missing → ``"unknown"``."""
    if value is None:
        return UNKNOWN
    return _ENV_ALIASES.get(value.strip().lower(), UNKNOWN)


def normalize_action_type(value: str | None) -> str:
    """Normalise an action type via the alias map; unrecognised → ``"unknown"``."""
    if value is None:
        return UNKNOWN
    return _ACTION_ALIASES.get(value.strip().lower(), UNKNOWN)


def normalize_domain(value: str | None) -> str | None:
    """Lowercase/strip a domain label; absent stays ``None`` (domain is advisory)."""
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def normalize_tool_name(value: str | None) -> str | None:
    """Lowercase/strip a tool name; absent stays ``None``."""
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def normalize_metadata(
    *,
    risk_tier: str | None = None,
    action_type: str | None = None,
    target_environment: str | None = None,
    domain: str | None = None,
    tool_name: str | None = None,
) -> NormalizedMetadata:
    """Normalise all supplied metadata and derive fail-closed flags.

    Returns a :class:`NormalizedMetadata` where every unknown field is listed
    in ``metadata_unknown_fields`` so missing metadata stays a visible risk
    signal rather than a silent default.
    """
    norm_tier = normalize_risk_tier(risk_tier)
    norm_action = normalize_action_type(action_type)
    norm_env = normalize_environment(target_environment)

    unknown_fields: list[str] = []
    if norm_tier == UNKNOWN:
        unknown_fields.append("risk_tier")
    if norm_action == UNKNOWN:
        unknown_fields.append("action_type")
    if norm_env == UNKNOWN:
        unknown_fields.append("target_environment")

    return NormalizedMetadata(
        risk_tier=norm_tier,
        action_type=norm_action,
        target_environment=norm_env,
        domain=normalize_domain(domain),
        tool_name=normalize_tool_name(tool_name),
        metadata_complete=not unknown_fields,
        metadata_unknown_fields=tuple(unknown_fields),
        mutating_action=norm_action in MUTATING_ACTION_TYPES,
        production_like_environment=norm_env == "prod",
        destructive_or_irreversible=norm_action in DESTRUCTIVE_ACTION_TYPES,
        raw_risk_tier=risk_tier,
        raw_action_type=action_type,
        raw_target_environment=target_environment,
    )
