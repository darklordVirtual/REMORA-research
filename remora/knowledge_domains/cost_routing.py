# Author: Stian Skogbrott
# License: Apache-2.0
"""Cost-aware routing: the cheapest model that still clears each request's floor.

REMORA calls models (embeddings, rerankers, generation) for oracle-backed modes;
it should not send every request to the most expensive one. Given a price/quality
table and per-request quality floors, route each request to the cheapest eligible
model and measure the saving versus an always-premium baseline — while proving no
request is served below its floor. The price table, quality scores and workload
are SYNTHETIC and fixed: this shows the policy and its guarantees, not real
prices or real model quality.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    name: str
    cost_per_1k: float
    quality: float


@dataclass(frozen=True)
class Request:
    rid: str
    tokens: int
    min_quality: float


MODELS: tuple[Model, ...] = (
    Model("nano", 0.05, 0.55),
    Model("small", 0.15, 0.72),
    Model("mid", 0.50, 0.85),
    Model("premium", 2.00, 0.97),
)

WORKLOAD: tuple[Request, ...] = (
    Request("r1", 1000, 0.50),
    Request("r2", 2000, 0.70),
    Request("r3", 500, 0.80),
    Request("r4", 4000, 0.60),
    Request("r5", 1500, 0.95),
    Request("r6", 3000, 0.70),
    Request("r7", 800, 0.55),
    Request("r8", 2500, 0.84),
)


def cheapest_meeting(models: tuple[Model, ...], floor: float) -> Model | None:
    eligible = [m for m in models if m.quality >= floor]
    return min(eligible, key=lambda m: m.cost_per_1k) if eligible else None


def _round(x: float) -> float:
    return round(x, 4)


def route(
    models: tuple[Model, ...], workload: tuple[Request, ...]
) -> dict[str, object]:
    premium = max(models, key=lambda m: m.quality)
    routed_cost = baseline_cost = 0.0
    violations = 0
    decisions: list[dict] = []
    for req in workload:
        chosen = cheapest_meeting(models, req.min_quality)
        if chosen is None:
            violations += 1
            chosen = premium
        if chosen.quality < req.min_quality:
            violations += 1
        routed_cost += chosen.cost_per_1k * req.tokens / 1000
        baseline_cost += premium.cost_per_1k * req.tokens / 1000
        decisions.append({"rid": req.rid, "model": chosen.name})
    savings_ratio = (1 - routed_cost / baseline_cost) if baseline_cost else 0.0
    return {
        "n_models": len(models),
        "n_requests": len(workload),
        "routed_cost": _round(routed_cost),
        "baseline_cost": _round(baseline_cost),
        "savings_ratio": _round(savings_ratio),
        "quality_violations": violations,
        "decisions": decisions,
    }
