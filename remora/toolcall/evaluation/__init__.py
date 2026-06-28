# Author: Stian Skogbrott
# License: Apache-2.0
"""Evaluator-only sub-package for remora.toolcall.

ARCHITECTURAL BOUNDARY (REM-016): This package MUST NOT be imported from
runtime/policy packages. Policy gates receive only CandidateAction (no labels).

Allowed callers: tests/, experiments/, scoring scripts, evaluation harnesses.
Blocked callers: remora.toolcall.remora_gate, remora.policy.*, remora.governance.*

Enforcement layers:
  1. Import-time guard (this file) — raises ImportError on boundary violation
  2. AST leakage detector (scripts/check_no_evaluation_leakage.py) — CI gate
  3. Mutation tests (tests/test_m1_leakage_absent.py) — regression guard
"""
from __future__ import annotations

import inspect as _inspect

# Modules that constitute the "runtime" layer and must not import evaluation labels.
_BLOCKED_RUNTIME_MODULES = frozenset({
    "remora.toolcall.remora_gate",
    "remora.toolcall.live_execution",
    "remora.toolcall.simulators",
    "remora.toolcall.splits_v2",
    "remora.toolcall.runtime",
    "remora.policy.decision_engine",
    "remora.policy.observation",
    "remora.policy.risk_engine",
    "remora.governance.envelope",
    "remora.governance.audit",
    "remora.shadow.replay",
})


def _check_import_boundary() -> None:
    """Raise ImportError if called from a runtime module (REM-016)."""
    stack = _inspect.stack()
    for frame_info in stack[1:8]:
        caller_module = frame_info.frame.f_globals.get("__name__", "")
        if caller_module in _BLOCKED_RUNTIME_MODULES:
            raise ImportError(
                f"ARCHITECTURAL BOUNDARY VIOLATION (REM-016): "
                f"remora.toolcall.evaluation imported from runtime module "
                f"'{caller_module}'. Policy gates must not access evaluation "
                f"labels. See docs/assurance/remediation_register.yaml REM-016."
            )


_check_import_boundary()

# Re-export the blinded v3 evaluation API
from remora.toolcall.benchmark_blind_v3 import (  # noqa: E402
    CandidateActionV3,
    EvaluationTruthV3,
    load_candidate_actions_v3,
    load_evaluation_truths_v3,
    score_blinded_v3,
)

__all__ = [
    "CandidateActionV3",
    "EvaluationTruthV3",
    "load_candidate_actions_v3",
    "load_evaluation_truths_v3",
    "score_blinded_v3",
]
