from __future__ import annotations

from typing import Any

from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason, DecisionReport


def enrich_then_decide(obs: PolicyObservation, **kwargs: Any):
    """Optional Governance Intelligence path: enrich *obs*, then decide.

    Lazy delegate to :func:`remora.governance_intelligence.enrichment.enrich_then_decide`
    (lazy to avoid an import cycle). ``RemoraDecisionEngine.decide()`` itself is
    unchanged; this helper is opt-in and backwards compatible.
    """
    from remora.governance_intelligence.enrichment import (
        enrich_then_decide as _impl,
    )
    return _impl(obs, **kwargs)


__all__ = [
    "DecisionAction",
    "DecisionReason",
    "DecisionReport",
    "PolicyObservation",
    "RemoraDecisionEngine",
    "enrich_then_decide",
]
