# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Decision-trace value objects produced by ``RemoraDecisionEngine.explain``.

Extracted verbatim from ``remora/policy/decision_engine.py`` (2026-07-29).
These are pure output/audit structures — they do not affect which decision is
made. ``decision_engine.py`` re-exports both names so existing import paths
(``remora.policy.decision_engine.PolicyTrace`` via ``remora/__init__.py`` and
the test suite) keep working. This module is kept in the hashed policy bundle
(``remora/policy/versioning.py``) so no policy bytes leave hash coverage after
the move.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PolicyRuleEvaluation:
    """Evaluation record for one rule in the decision tree."""
    rule: str
    triggered: bool
    condition: str
    outcome: str | None = None


@dataclass(frozen=True)
class PolicyTrace:
    """Full decision audit trail produced by :meth:`RemoraDecisionEngine.explain`.

    Example::

        trace = engine.explain(obs)
        print(trace.decision_path)          # "ordered_high_trust → ACCEPT"
        for step in trace.rule_evaluations:
            marker = "✓" if step.triggered else "·"
            print(f"  {marker} {step.rule}: {step.condition}")
    """
    action: str
    reasons: tuple[str, ...]
    decision_path: str
    rule_evaluations: tuple[PolicyRuleEvaluation, ...]
    observation_summary: dict[str, Any]
    policy_version: str = "RemoraDecisionEngine-v3"
