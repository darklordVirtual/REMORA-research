"""Adaptive Policy Thresholds with Temporal Decay for REMORA.

Policies that auto-adjust based on outcome feedback:
- Tighten when recent outcomes show drift, false accepts, or safety violations
- Relax when track record is clean over a configurable window
- Exponential decay ensures recent outcomes matter more than old ones

This implements the "trust but verify" paradigm: an agent with a clean
track record earns looser governance, while incidents trigger automatic
tightening — no manual policy rewrite needed.

Design principles
-----------------
1. All threshold changes are bounded (min/max clamps)
2. Tightening is instant; relaxation is gradual (asymmetric response)
3. Every adjustment is logged with full provenance for audit
4. Manual overrides always take precedence
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class OutcomeType(str, Enum):
    """Outcome of a governed action."""

    CORRECT_ACCEPT = "correct_accept"     # action was right to accept
    CORRECT_BLOCK = "correct_block"       # action was right to block
    FALSE_ACCEPT = "false_accept"         # should have blocked but didn't
    FALSE_BLOCK = "false_block"           # should have accepted but blocked
    SAFETY_VIOLATION = "safety_violation"  # critical failure
    UNKNOWN = "unknown"                   # outcome not yet determined


@dataclass
class OutcomeRecord:
    """A single outcome observation."""

    timestamp: float
    outcome: OutcomeType
    domain: str
    risk_tier: str
    confidence_at_decision: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ThresholdState:
    """Current state of an adaptive threshold."""

    name: str
    base_value: float  # the configured baseline
    current_value: float  # the adapted value
    min_value: float
    max_value: float
    last_adjusted: float = 0.0
    adjustment_count: int = 0
    adjustment_history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def deviation_from_base(self) -> float:
        return self.current_value - self.base_value


@dataclass
class AdaptationReport:
    """Report produced after threshold adaptation."""

    thresholds_adjusted: int
    total_outcomes_considered: int
    effective_window_size: int
    false_accept_rate: float
    false_block_rate: float
    safety_violation_count: int
    adjustments: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AdaptiveThresholdEngine:
    """Engine that adapts governance thresholds based on outcome feedback.

    The engine maintains a sliding window of outcomes and adjusts
    thresholds using exponentially-weighted moving averages.

    Parameters
    ----------
    decay_half_life_hours : float
        Half-life for exponential decay. Outcomes older than this
        contribute half as much weight. Default 72h (3 days).
    tightening_rate : float
        How aggressively to tighten on bad outcomes. Default 0.15.
    relaxation_rate : float
        How gradually to relax on good outcomes. Default 0.03.
        (Asymmetric: tightening is 5x faster than relaxation.)
    max_window : int
        Maximum number of outcomes to keep in the window.
    """

    def __init__(
        self,
        *,
        decay_half_life_hours: float = 72.0,
        tightening_rate: float = 0.15,
        relaxation_rate: float = 0.03,
        max_window: int = 500,
    ) -> None:
        self._decay_lambda = math.log(2) / (decay_half_life_hours * 3600)
        self._tighten_rate = tightening_rate
        self._relax_rate = relaxation_rate
        self._max_window = max_window
        self._outcomes: list[OutcomeRecord] = []
        self._thresholds: dict[str, ThresholdState] = {}
        self._manual_locks: set[str] = set()  # manually locked thresholds

    def register_threshold(
        self,
        name: str,
        base_value: float,
        *,
        min_value: float = 0.0,
        max_value: float = 1.0,
    ) -> None:
        """Register a threshold for adaptive management."""
        self._thresholds[name] = ThresholdState(
            name=name,
            base_value=base_value,
            current_value=base_value,
            min_value=min_value,
            max_value=max_value,
        )

    def lock_threshold(self, name: str) -> None:
        """Lock a threshold against automatic adaptation."""
        self._manual_locks.add(name)

    def unlock_threshold(self, name: str) -> None:
        """Unlock a threshold for automatic adaptation."""
        self._manual_locks.discard(name)

    def record_outcome(self, outcome: OutcomeRecord) -> None:
        """Record an outcome for threshold adaptation."""
        self._outcomes.append(outcome)
        if len(self._outcomes) > self._max_window:
            self._outcomes = self._outcomes[-self._max_window:]

    def get_threshold(self, name: str) -> float:
        """Get the current adapted value of a threshold."""
        state = self._thresholds.get(name)
        return state.current_value if state else 0.0

    @property
    def thresholds(self) -> dict[str, ThresholdState]:
        return dict(self._thresholds)

    def _decay_weight(self, record_time: float, now: float) -> float:
        """Exponential decay weight for an outcome based on age."""
        age = max(0.0, now - record_time)
        return math.exp(-self._decay_lambda * age)

    def _compute_rates(self, now: float) -> tuple[float, float, int, float]:
        """Compute weighted false-accept rate, false-block rate, safety count, total weight."""
        total_weight = 0.0
        fa_weight = 0.0
        fb_weight = 0.0
        safety_count = 0

        for o in self._outcomes:
            w = self._decay_weight(o.timestamp, now)
            total_weight += w
            if o.outcome == OutcomeType.FALSE_ACCEPT:
                fa_weight += w
            elif o.outcome == OutcomeType.FALSE_BLOCK:
                fb_weight += w
            elif o.outcome == OutcomeType.SAFETY_VIOLATION:
                safety_count += 1
                fa_weight += w * 2.0  # safety violations count double

        if total_weight == 0:
            return 0.0, 0.0, 0, 0.0

        return fa_weight / total_weight, fb_weight / total_weight, safety_count, total_weight

    def adapt(self, *, domain: str | None = None) -> AdaptationReport:
        """Run one adaptation cycle across all registered thresholds.

        If domain is specified, only outcomes from that domain contribute.
        """
        now = time.time()
        relevant = self._outcomes
        if domain:
            relevant = [o for o in self._outcomes if o.domain == domain]

        if not relevant:
            return AdaptationReport(
                thresholds_adjusted=0,
                total_outcomes_considered=0,
                effective_window_size=0,
                false_accept_rate=0.0,
                false_block_rate=0.0,
                safety_violation_count=0,
            )

        # Compute decay-weighted rates
        total_weight = 0.0
        fa_weight = 0.0
        fb_weight = 0.0
        safety_count = 0

        for o in relevant:
            w = self._decay_weight(o.timestamp, now)
            total_weight += w
            if o.outcome == OutcomeType.FALSE_ACCEPT:
                fa_weight += w
            elif o.outcome == OutcomeType.FALSE_BLOCK:
                fb_weight += w
            elif o.outcome == OutcomeType.SAFETY_VIOLATION:
                safety_count += 1
                fa_weight += w * 2.0

        fa_rate = fa_weight / total_weight if total_weight else 0.0
        fb_rate = fb_weight / total_weight if total_weight else 0.0

        adjustments: list[dict[str, Any]] = []
        adjusted = 0

        for name, state in self._thresholds.items():
            if name in self._manual_locks:
                continue

            old_value = state.current_value

            # Tighten: raise thresholds when false accepts are high
            if fa_rate > 0.05 or safety_count > 0:
                delta = self._tighten_rate * fa_rate
                if safety_count > 0:
                    delta = max(delta, self._tighten_rate * 0.5)  # aggressive on safety
                state.current_value = min(state.max_value, state.current_value + delta)

            # Relax: lower thresholds when track record is clean
            elif fa_rate < 0.02 and fb_rate > 0.1:
                delta = self._relax_rate * fb_rate
                state.current_value = max(state.min_value, state.current_value - delta)

            # Gravity: gently pull back toward base when rates are normal
            elif abs(state.current_value - state.base_value) > 0.01:
                pull = self._relax_rate * 0.5
                if state.current_value > state.base_value:
                    state.current_value = max(state.base_value, state.current_value - pull)
                else:
                    state.current_value = min(state.base_value, state.current_value + pull)

            state.current_value = round(state.current_value, 4)

            if state.current_value != old_value:
                adjusted += 1
                state.last_adjusted = now
                state.adjustment_count += 1
                adj = {
                    "threshold": name,
                    "old": old_value,
                    "new": state.current_value,
                    "reason": "tighten" if state.current_value > old_value else "relax",
                    "fa_rate": round(fa_rate, 4),
                    "fb_rate": round(fb_rate, 4),
                }
                state.adjustment_history.append(adj)
                adjustments.append(adj)

        return AdaptationReport(
            thresholds_adjusted=adjusted,
            total_outcomes_considered=len(relevant),
            effective_window_size=len(relevant),
            false_accept_rate=round(fa_rate, 4),
            false_block_rate=round(fb_rate, 4),
            safety_violation_count=safety_count,
            adjustments=adjustments,
        )
