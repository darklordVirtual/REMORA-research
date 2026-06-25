"""TSF forecasters: frozen baselines B1/B2/B3 + candidate slot.

Operates on synthetic traces only (see synthetic_trace_generator.py). No real
data, no claims.
"""
from __future__ import annotations

import random
from typing import Sequence


def b1_persistence(values: Sequence[float], h: int) -> float:
    """Predict the value h steps ahead equals the last observed value."""
    return values[-1] if values else 0.0


def b2_moving_average(values: Sequence[float], h: int, window: int = 5) -> float:
    if not values:
        return 0.0
    w = values[-window:]
    return sum(w) / len(w)


def b3_random(values: Sequence[float], h: int, seed: int = 0) -> float:
    return random.Random(seed + len(values)).random()


def destabilization_score(values: Sequence[float], h: int, method: str = "b1") -> float:
    """Return P(destabilization within h). Higher = more likely unstable.

    Heuristic: lower forecast value => more unstable. We map forecast in [0,1]
    to instability = 1 - forecast. Candidate forecasters would replace this.
    """
    if method == "b1":
        f = b1_persistence(values, h)
    elif method == "b2":
        f = b2_moving_average(values, h)
    elif method == "b3":
        f = b3_random(values, h)
    else:
        raise ValueError(f"unknown method: {method}")
    return max(0.0, min(1.0, 1.0 - f))
