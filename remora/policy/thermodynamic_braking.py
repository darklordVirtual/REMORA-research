# Author: Stian Skogbrott
# License: Apache-2.0
"""Thermodynamic Anti-Lock Braking System (ABS) for Agentic AI.

This module provides a dynamic risk penalizer that evaluates the running
derivative of the Lyapunov stability function (dV/dt). If an agent's
trajectory starts accelerating towards disorder (entropy and dissensus
are increasing rapidly across sequential tool calls), this applies a
"braking penalty" to the required trust threshold.

This prevents the "boiled frog" problem where individual tool calls might
just barely pass the 'ACCEPT' threshold, but the overarching session is
collapsing into chaos.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from remora.lyapunov import LyapunovState

@dataclass(frozen=True)
class BrakingResult:
    """The result of the thermodynamic ABS calculation."""
    is_braking: bool
    penalty: float            # Amount to subtract from Trust Score
    trajectory_delta: float   # The measured dV (positive means growing instability)
    reason: str

class ThermodynamicBrakingSystem:
    """Monitors Lyapunov trajectories to enforce thermodynamic braking.

    If the agent's V(t) grows faster than the acceptable tolerance, the
    braking system forces a trust penalty, shifting marginal ACCEPTs
    into VERIFY or ESCALATE.
    """
    def __init__(self,
                 sensitivity: float = 1.0,
                 activation_threshold: float = 0.05,
                 max_penalty: float = 0.40):
        self.sensitivity = sensitivity
        self.activation_threshold = activation_threshold
        self.max_penalty = max_penalty

    def calculate_braking(self, trajectory: Sequence[LyapunovState]) -> BrakingResult:
        """Calculate the required trust penalty based on trajectory momentum."""
        if len(trajectory) < 2:
            return BrakingResult(False, 0.0, 0.0, "Insufficient trajectory for momentum")

        # Get the most recent step and the one before it
        state_t = trajectory[-1]
        state_t_prev = trajectory[-2]

        # dV = V(t) - V(t-1)
        # If dV > 0, system is gaining entropy/dissensus
        delta_v = state_t.V - state_t_prev.V

        if delta_v <= self.activation_threshold:
            return BrakingResult(
                is_braking=False,
                penalty=0.0,
                trajectory_delta=delta_v,
                reason="Trajectory is stable or converging (dV <= threshold)"
            )

        # Braking force is proportional to the acceleration of chaos
        excess_v = delta_v - self.activation_threshold
        raw_penalty = excess_v * self.sensitivity

        # Cap the penalty
        applied_penalty = min(raw_penalty, self.max_penalty)

        return BrakingResult(
            is_braking=True,
            penalty=applied_penalty,
            trajectory_delta=delta_v,
            reason=f"Thermodynamic braking engaged: dV={delta_v:.3f} exceeds threshold. Trust penalized by {applied_penalty:.3f}"
        )
