# Author: Stian Skogbrott
# License: Apache-2.0
"""Trap Avoidance — classify proposed actions by irreversibility and impact.

A "trap" is an action that, if executed incorrectly, is difficult or impossible
to reverse and may cause significant harm.  The trap score combines:

- **Action-type base score:** inherent irreversibility of the operation class.
- **Domain penalty:** sensitivity of the operational domain.
- **Environment boost:** extra weight when targeting production systems.

Policy
------
``trap_score`` range | Gate outcome
-------------------- | -------------------------
0.00 – 0.29          | No additional gate (normal policy)
0.30 – 0.69          | VERIFY
0.70 – 1.00          | ESCALATE

The trap gate runs after the existing structural hard blocks and the minimax
gate, acting as a general safety net for well-known irreversible-action patterns
not already captured by the production-write matrix.

Relationship to existing gates
-------------------------------
``RemoraDecisionEngine._production_write_outcome`` handles ``destructive_write``
and ``delete`` in production at ``critical``/``high`` risk tiers.  The trap gate
generalises this to a wider action vocabulary (``disable_security``,
``dns_change``, ``bulk_email``, etc.) and lower risk tiers.  Both gates may
fire; the engine applies the first matching ESCALATE.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.policy.observation import PolicyObservation

# ---------------------------------------------------------------------------
# Scoring tables
# ---------------------------------------------------------------------------

# Base trap score per action type.
# 0.0 = fully reversible / low impact; 1.0 = maximum trap.
_ACTION_TRAP_SCORES: dict[str, float] = {
    # Destructive / irreversible data operations
    "delete":               0.90,
    "bulk_delete":          0.92,
    "destructive_write":    0.85,
    "emergency_write":      0.80,
    "financial_write":      0.92,
    "production_write":     0.75,
    "execute_transfer":     0.88,
    "wipe":                 0.95,
    # Security / access control
    "disable_security":     0.95,
    "unlock_access":        0.85,
    "revoke_permission":    0.70,
    "grant_permission":     0.58,
    # Configuration / infrastructure
    "config_overwrite":     0.78,
    "dns_change":           0.80,
    "firewall_change":      0.85,
    "network_config":       0.72,
    # Shell / code execution
    "shell_execute":        0.72,
    "script_execute":       0.68,
    "code_execute":         0.65,
    # Communication / external publish
    "bulk_email":           0.55,
    "external_publish":     0.50,
    "webhook_trigger":      0.45,
}

# Domain-specific sensitivity penalties (added to action base score).
_DOMAIN_TRAP_PENALTIES: dict[str, float] = {
    "financial":       0.12,
    "database":        0.10,
    "infrastructure":  0.10,
    "medical":         0.12,
    "security":        0.10,
    "shell":           0.08,
    "network":         0.07,
    "agentic":         0.08,
    "well_engineering": 0.10,
    "energy":          0.10,
    "industrial":      0.08,
}

# Production environment names.
_PROD_ENVIRONMENTS: frozenset[str] = frozenset({"prod", "production", "live"})

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

TRAP_ESCALATE_THRESHOLD: float = 0.70
TRAP_VERIFY_THRESHOLD:   float = 0.30


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score(obs: PolicyObservation) -> float:
    """Return a trap score in ``[0, 1]`` for the proposed action.

    Parameters
    ----------
    obs:
        The governance observation describing the proposed action.

    Returns
    -------
    float
        0.0 = fully reversible / benign; 1.0 = maximum trap.
        Scores are additive: action base + domain penalty + environment boost.

    Examples
    --------
    Low-risk read in staging::

        obs = PolicyObservation("query users", action_type="read",
                                domain="database", target_environment="staging")
        assert score(obs) == 0.0

    High-risk delete in production financial domain::

        obs = PolicyObservation("delete all", action_type="delete",
                                domain="financial", target_environment="prod")
        assert score(obs) == min(1.0, 0.90 + 0.12 + 0.15)  # 1.0
    """
    action = (obs.action_type       or "").strip().lower()
    domain = (obs.domain            or "").strip().lower()
    env    = (obs.target_environment or "").strip().lower()

    base         = _ACTION_TRAP_SCORES.get(action, 0.0)
    domain_boost = _DOMAIN_TRAP_PENALTIES.get(domain, 0.0)
    env_boost    = 0.15 if env in _PROD_ENVIRONMENTS else 0.0

    return min(1.0, base + domain_boost + env_boost)


def classify(obs: PolicyObservation) -> str:
    """Return a human-readable trap classification label.

    Returns one of ``"SAFE"``, ``"CAUTION"``, ``"TRAP"``.
    """
    s = score(obs)
    if s >= TRAP_ESCALATE_THRESHOLD:
        return "TRAP"
    if s >= TRAP_VERIFY_THRESHOLD:
        return "CAUTION"
    return "SAFE"
