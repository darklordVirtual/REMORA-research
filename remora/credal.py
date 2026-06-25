# Author: Stian Skogbrott
# License: Apache-2.0
"""Credal Risk Envelope — interval-valued harm and utility estimates for REMORA.

Instead of a single point-estimate ``risk_estimate``, a ``CredalEnvelope``
represents the *set* of plausible probability distributions over harm outcomes
derived from oracle disagreement, thermodynamic observables, and operational
context.

The envelope feeds two governance gates inside ``RemoraDecisionEngine``:

* **Minimax gate:** ``worst_case_loss >= MINIMAX_ESCALATE_THRESHOLD`` → ESCALATE.
  Prevents ACCEPT when any plausible harm scenario is catastrophic, regardless
  of the mean trust signal.

* **Ambiguity penalty:** ``adjusted_trust = trust_score - AMBIGUITY_ALPHA *
  ambiguity_width``.  High oracle disagreement reduces effective trust in the
  ``ordered_high_trust`` accept path, making the engine more conservative when
  the oracle swarm is uncertain.

Infra-Bayesian inspiration
--------------------------
Rather than assuming one world model, REMORA treats multi-oracle output as
evidence about a *range* of plausible environments.  The credal interval
``[p_harm_lower, p_harm_upper]`` spans this range.  Acting on ``p_harm_upper``
(worst-case) yields robustly conservative decisions; narrowing the interval
via strong evidence reduces unnecessary friction.

This module does NOT implement full infra-Bayesian decision theory.  The interval
is a calibrated heuristic derived from observable signals (H, D, phase), not a
frequentist coverage guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.policy.observation import PolicyObservation

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Penalty applied to trust_score per unit of ambiguity_width.
# Tune down to make the engine less sensitive to disagreement.
AMBIGUITY_ALPHA: float = 0.30

# worst_case_loss threshold above which the minimax gate escalates.
MINIMAX_ESCALATE_THRESHOLD: float = 0.80

# Phase multipliers on the raw disagreement spread.
_PHASE_SPREAD_FACTOR: dict[str, float] = {
    "ordered":    0.60,   # oracles agree — tight interval
    "critical":   1.00,   # nominal spread
    "disordered": 1.60,   # oracles disagree — wide interval
}

# Operational severity: cost if the action turns out harmful.
_TIER_SEVERITY: dict[str, float] = {
    "low":      0.05,
    "medium":   0.15,
    "high":     0.40,
    "critical": 0.70,
}

# Actions that are largely irreversible; carry a higher worst-case-loss weight.
_IRREVERSIBLE_ACTIONS: frozenset[str] = frozenset({
    "delete",
    "destructive_write",
    "emergency_write",
    "financial_write",
    "production_write",
    "execute_transfer",
    "disable_security",
    "config_overwrite",
    "bulk_delete",
    "wipe",
})


# ---------------------------------------------------------------------------
# CredalEnvelope
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CredalEnvelope:
    """Interval-valued harm and utility estimates for one governance decision.

    Parameters
    ----------
    p_harm_lower:
        Lower bound of the credal interval over P(harm). In the most optimistic
        plausible world, harm probability is at least this high.
    p_harm_upper:
        Upper bound. In the worst plausible world, harm probability reaches this
        value. Used by the minimax gate and for ``worst_case_loss``.
    utility_lower:
        Lower bound on expected utility (worst plausible outcome after severity
        penalty for the risk tier).
    utility_upper:
        Upper bound on expected utility (best plausible outcome).
    ambiguity_width:
        ``p_harm_upper - p_harm_lower``.  High ambiguity → engine is more
        conservative in the ``ordered_high_trust`` accept path.
    worst_case_loss:
        ``p_harm_upper × (1 + irreversibility × severity × 2)``, clamped to
        ``[0, 1]``.  Irreversible actions (delete, financial_write, …) carry a
        higher multiplier than reversible ones.
    adjusted_trust:
        ``trust_score - AMBIGUITY_ALPHA × ambiguity_width``, clamped to
        ``[0, 1]``.  Used instead of raw ``trust_score`` in the
        ``ordered_high_trust`` accept path.  ``None`` when the observation
        carries no ``trust_score``.
    """

    p_harm_lower:    float
    p_harm_upper:    float
    utility_lower:   float
    utility_upper:   float
    ambiguity_width: float
    worst_case_loss: float
    adjusted_trust:  float | None = None

    # ------------------------------------------------------------------
    # Gate helpers
    # ------------------------------------------------------------------

    def minimax_should_escalate(
        self,
        threshold: float = MINIMAX_ESCALATE_THRESHOLD,
    ) -> bool:
        """Return True when worst-case loss exceeds the minimax threshold."""
        return self.worst_case_loss >= threshold

    def decision_recommendation(
        self,
        *,
        escalate_threshold: float = MINIMAX_ESCALATE_THRESHOLD,
        verify_threshold: float = 0.50,
    ) -> str:
        """Lightweight recommendation from the credal envelope alone.

        Returns one of ``"ACCEPT"``, ``"VERIFY"``, ``"ABSTAIN"``, ``"ESCALATE"``.
        This is informational — the policy engine makes the authoritative decision.
        """
        if self.worst_case_loss >= escalate_threshold:
            return "ESCALATE"
        if self.p_harm_upper >= verify_threshold or self.ambiguity_width >= 0.40:
            return "VERIFY"
        if self.p_harm_upper < 0.20 and self.ambiguity_width < 0.15:
            return "ACCEPT"
        return "ABSTAIN"

    def to_dict(self) -> dict[str, object]:
        return {
            "p_harm_lower":    round(self.p_harm_lower,    4),
            "p_harm_upper":    round(self.p_harm_upper,    4),
            "utility_lower":   round(self.utility_lower,   4),
            "utility_upper":   round(self.utility_upper,   4),
            "ambiguity_width": round(self.ambiguity_width, 4),
            "worst_case_loss": round(self.worst_case_loss, 4),
            "adjusted_trust":  (
                round(self.adjusted_trust, 4)
                if self.adjusted_trust is not None else None
            ),
        }


# ---------------------------------------------------------------------------
# compute_from_obs
# ---------------------------------------------------------------------------

def compute_from_obs(obs: PolicyObservation) -> CredalEnvelope:
    """Compute a ``CredalEnvelope`` from a ``PolicyObservation``.

    Algorithm
    ---------
    1. **Centre:** ``base_harm = 1 - trust_score``.  Conservative default 0.50
       when ``trust_score`` is absent.
    2. **Spread:** half-width from oracle disagreement — the larger of
       normalised H and D — scaled by a phase factor.
    3. **Credal interval:** ``[centre - half_width, centre + half_width]``,
       clamped to ``[0, 1]``.
    4. **Utility bounds:** inverse harm bounds minus the risk-tier severity
       penalty.
    5. **Worst-case loss:** ``p_harm_upper × (1 + irreversibility × severity × 2)``,
       clamped to ``[0, 1]``.  Irreversible actions carry a higher multiplier.
    6. **Adjusted trust:** ``trust_score - AMBIGUITY_ALPHA × ambiguity_width``,
       clamped to ``[0, 1]``.
    """
    # ── 1. Centre ───────────────────────────────────────────────────────────
    trust = obs.trust_score if obs.trust_score is not None else 0.50
    trust = max(0.0, min(1.0, float(trust)))
    centre = 1.0 - trust

    # ── 2. Spread ───────────────────────────────────────────────────────────
    # H is Shannon entropy in bits; 1.0 bit is maximum for a binary split.
    H_norm = min(1.0, float(obs.final_H or 0.0))
    D_norm = min(1.0, max(0.0, float(obs.final_D or 0.0)))
    disagreement = max(H_norm, D_norm)

    phase_factor = _PHASE_SPREAD_FACTOR.get(obs.phase or "disordered", 1.20)
    half_width = min(0.45, disagreement * 0.50 * phase_factor)

    # ── 3. Credal interval ───────────────────────────────────────────────────
    p_harm_lower = max(0.0, centre - half_width)
    p_harm_upper = min(1.0, centre + half_width)
    ambiguity_width = round(p_harm_upper - p_harm_lower, 4)

    # ── 4. Utility bounds ────────────────────────────────────────────────────
    severity = _TIER_SEVERITY.get((obs.risk_tier or "medium").strip().lower(), 0.20)
    utility_upper = max(0.0, 1.0 - p_harm_lower)
    utility_lower = max(0.0, 1.0 - p_harm_upper - severity)

    # ── 5. Worst-case loss ───────────────────────────────────────────────────
    action = (obs.action_type or "").strip().lower()
    irreversibility = 1.0 if action in _IRREVERSIBLE_ACTIONS else 0.30
    worst_case_loss = min(1.0, p_harm_upper * (1.0 + irreversibility * severity * 2.0))

    # ── 6. Adjusted trust ────────────────────────────────────────────────────
    adjusted_trust: float | None = None
    if obs.trust_score is not None:
        adjusted_trust = max(0.0, min(1.0, obs.trust_score - AMBIGUITY_ALPHA * ambiguity_width))

    return CredalEnvelope(
        p_harm_lower=round(p_harm_lower,    4),
        p_harm_upper=round(p_harm_upper,    4),
        utility_lower=round(utility_lower,   4),
        utility_upper=round(utility_upper,   4),
        ambiguity_width=ambiguity_width,
        worst_case_loss=round(worst_case_loss, 4),
        adjusted_trust=round(adjusted_trust, 4) if adjusted_trust is not None else None,
    )
