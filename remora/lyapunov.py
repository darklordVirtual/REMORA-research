# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Lyapunov stability controller for REMORA consensus iteration."""
from __future__ import annotations
import math
from dataclasses import dataclass
from collections.abc import Sequence


@dataclass(frozen=True)
class LyapunovParams:
    """Immutable tuning parameters for the Lyapunov controller."""

    lambda_dissensus: float = 1.0
    mu_cost: float = 0.0
    epsilon_tolerance: float = 0.05
    min_window: int = 2
    # Issue #50 (M2): number of CONSECUTIVE over-threshold ΔV increases
    # required before should_abort() signals abort. The default of 1 preserves
    # the original greedy one-step behavior exactly; k > 1 tolerates a single
    # transient spike followed by recovery. Changing the default (or having a
    # call site pass a non-default value) changes accept/abort behavior on
    # live sessions and is a policy-version event that must be scheduled with
    # the rebenchmark round (docs/assurance/rebenchmark_protocol_v1.md).
    abort_window: int = 1


@dataclass(frozen=True)
class LyapunovState:
    """Snapshot of the Lyapunov function at one iteration step."""

    t: int
    H: float
    D: float
    cost: float
    V: float
    consensus_fp: str


def compute_entropy(weighted_support: dict[str, float]) -> float:
    """Return Shannon entropy (bits) of the weighted support distribution."""
    return sum(-p * math.log2(p) for p in weighted_support.values() if p > 0)


def lyapunov_value(weighted_support, cumulative_cost, params):
    """Return (V, H, D) for the current weighted support distribution."""
    if not weighted_support:
        return float("inf"), float("inf"), 1.0
    H = compute_entropy(weighted_support)
    D = max(0.0, 1.0 - max(weighted_support.values()))
    return H + params.lambda_dissensus * D + params.mu_cost * cumulative_cost, H, D


def state_from_consensus(t, consensus, weighted_distribution, cumulative_cost, params):
    """Build a LyapunovState from a WeightedConsensus result."""
    V, H, D = lyapunov_value(weighted_distribution, cumulative_cost, params)
    return LyapunovState(t=t, H=H, D=D, cost=cumulative_cost, V=V, consensus_fp=consensus.winning_fingerprint)


def summarize_v_trajectories(
    trajectories: Sequence[Sequence[float]],
    epsilon_tolerance: float = 0.0,
) -> dict[str, float | int]:
    """Aggregate V(t) trajectories without treating one run as canonical.

    The function is intentionally lightweight and deterministic. It supports
    review reports that cite means/fractions across repeated sessions instead
    of a single context-dependent Lyapunov value.
    """

    cleaned: list[list[float]] = [
        [float(v) for v in trajectory if math.isfinite(float(v))]
        for trajectory in trajectories
    ]
    cleaned = [trajectory for trajectory in cleaned if trajectory]

    if not cleaned:
        return {
            "n_trajectories": 0,
            "n_steps": 0,
            "mean_delta_v": 0.0,
            "max_delta_v": 0.0,
            "mean_total_reduction": 0.0,
            "fraction_monotone_nonincreasing": 0.0,
            "divergent_fraction": 0.0,
        }

    deltas: list[float] = []
    total_reductions: list[float] = []
    monotone_count = 0
    divergent_count = 0
    for trajectory in cleaned:
        step_deltas = [trajectory[index + 1] - trajectory[index] for index in range(len(trajectory) - 1)]
        deltas.extend(step_deltas)
        total_reductions.append(trajectory[0] - trajectory[-1])
        if all(delta <= epsilon_tolerance for delta in step_deltas):
            monotone_count += 1
        if any(delta > epsilon_tolerance for delta in step_deltas):
            divergent_count += 1

    n_steps = len(deltas)
    return {
        "n_trajectories": len(cleaned),
        "n_steps": n_steps,
        "mean_delta_v": sum(deltas) / n_steps if deltas else 0.0,
        "max_delta_v": max(deltas) if deltas else 0.0,
        "mean_total_reduction": sum(total_reductions) / len(total_reductions),
        "fraction_monotone_nonincreasing": monotone_count / len(cleaned),
        "divergent_fraction": divergent_count / len(cleaned),
    }


@dataclass
class LyapunovController:
    """Stateful controller that tracks V over time and signals abort when V increases."""

    params: LyapunovParams
    history: list[LyapunovState]

    @classmethod
    def init(cls, params):
        """Return a fresh LyapunovController with empty history."""
        return cls(params=params, history=[])

    def push(self, state):
        """Append a LyapunovState to the history."""
        self.history.append(state)

    def latest(self):
        """Return the most recent LyapunovState, or None."""
        return self.history[-1] if self.history else None

    def previous(self):
        """Return the second-most-recent LyapunovState, or None."""
        return self.history[-2] if len(self.history) >= 2 else None

    def should_abort(self, allow_exploration=False):
        """Return (abort: bool, reason: str) based on ΔV vs epsilon_tolerance.

        With ``params.abort_window`` k > 1 (issue #50 M2), abort requires the
        last k consecutive steps to EACH show an over-threshold ΔV increase
        (per-step threshold, evaluated pairwise) — a single spike followed by
        recovery does not abort. The default k = 1 preserves the original
        greedy one-step behavior exactly, including reason strings.
        """
        window = max(1, self.params.abort_window)
        if len(self.history) < max(window + 1, self.params.min_window):
            return False, "warming_up"
        latest = self.history[-1]
        prev = self.history[-2]
        if latest.V == float("inf"):
            return False, "uninformative"
        if prev.V == float("inf"):
            return False, "transition_from_unknown"
        delta_V = latest.V - prev.V
        threshold = abs(prev.V) * self.params.epsilon_tolerance + 1e-9
        if delta_V > threshold:
            # Latest step increased. For k > 1, the k-1 preceding steps must
            # each also be over-threshold increases before we abort.
            for back in range(2, window + 1):
                newer = self.history[-back]
                older = self.history[-back - 1]
                if older.V == float("inf") or newer.V == float("inf"):
                    return False, f"window_interrupted_by_unknown_at_-{back}"
                step_delta = newer.V - older.V
                step_threshold = abs(older.V) * self.params.epsilon_tolerance + 1e-9
                if step_delta <= step_threshold:
                    return False, (
                        f"single_spike_tolerated dV={delta_V:.4f} "
                        f"(abort_window={window} consecutive increases required)"
                    )
            if allow_exploration:
                return False, f"exploration_allowed_dV={delta_V:.4f}"
            return True, f"V_increased dV={delta_V:.4f} > eps={threshold:.4f}"
        return False, f"stable_or_decreasing dV={delta_V:.4f}"

    def trajectory(self):
        """Return the full V-trajectory as a list of dicts."""
        return [
            {"t": s.t, "V": s.V, "H": s.H, "D": s.D, "cost": s.cost, "consensus_fp": s.consensus_fp}
            for s in self.history
        ]

    def is_converging(self, last_k=3):
        """Return True when V is non-increasing over the last k steps."""
        if len(self.history) < last_k:
            return False
        vs = [s.V for s in self.history[-last_k:]]
        return all(vs[i] >= vs[i + 1] for i in range(len(vs) - 1))

    def total_reduction(self):
        """Return the total V reduction from first to last history entry."""
        if len(self.history) < 2:
            return 0.0
        v0, vT = self.history[0].V, self.history[-1].V
        return v0 - vT if v0 != float("inf") and vT != float("inf") else 0.0
