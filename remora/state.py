# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Engine session state for REMORA.

Extracted from remora.engine (2026-07-29 maintainability refactor) so that
remora.reporting (and future orchestration-adjacent modules) can depend on
the state contract without importing the full engine. Behaviour unchanged;
``from remora.engine import RemoraState`` remains the supported import path
via re-export.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from remora.canonical import CanonicalVerdict
from remora.lyapunov import LyapunovController, LyapunovParams
from remora.core import OracleResponse


@dataclass
class RemoraState:
    question: str
    iteration: int = 0
    candidates: dict[str, CanonicalVerdict] = field(default_factory=dict)
    candidate_support: dict[str, float] = field(default_factory=dict)
    falsified: set[str] = field(default_factory=set)
    cumulative_cost: float = 0.0
    allow_exploration: bool = False
    controller: LyapunovController = field(default_factory=lambda: LyapunovController.init(LyapunovParams()))
    oracle_log: list[OracleResponse] = field(default_factory=list)
    consensus_log: list[dict] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    require_rag: bool = False
    refuse_parametric_verdict: bool = False
    evidence_request_reason: str | None = None
    last_thermo: object = None
    # Enterprise request context (filled by caller via run())
    domain: str | None = None
    risk_tier: str | None = None
    action_type: str | None = None
    target_environment: str | None = None
    external_evidence: list[dict] = field(default_factory=list)
    # v0.9 governance context — caller-supplied; engine populates what it can detect
    session_id: str | None = None
    session_action_count: int | None = None
    session_cumulative_risk: float | None = None
    fleet_level_effect: str | None = None
    policy_generalization_risk: float | None = None
    similar_action_seen_count: int | None = None
    environment_confidence: float | None = None
    model_misspecification_risk: float | None = None
    classification_confidence: float | None = None
    coercion_detected: bool = False
    # Cached admission-firewall result. run() sets it exactly once; None means
    # the state was built outside run() and report() computes it on demand.
    adversarial_detected: bool | None = None
