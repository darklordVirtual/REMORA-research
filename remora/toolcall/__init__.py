# SPDX-License-Identifier: BUSL-1.1
"""Tool-call gating: benchmarks, routing, and the runtime/evaluation split.

Orientation for readers — three benchmark generations live side by side
because superseded results are archived, never deleted:

- ``benchmark.py`` / ``benchmark_v2.py`` (+ ``baselines*``, ``scoring``,
  ``splits_v2``): the v1/v2 synthetic consensus benchmarks. Historical;
  their results are frozen artifacts (``results/toolcall_benchmark_v*``)
  and their claims live in the claim register with their caveats.
- ``benchmark_v3.py`` / ``benchmark_blind_v3.py`` / ``schema_v3.py`` /
  ``scoring_v3.py``: the current blind-evaluation round.
- ``routing/``: the active routing evaluation path (predicates, route
  table, admission, goal match, declared-effect consistency) — this is
  what the decision engine consumes.

Architectural boundary (REM-016): ``runtime/`` may never import from
``evaluation/``; policy gates never see ground-truth labels. Enforced by an
import-time guard, an AST leakage detector in CI, and mutation tests.
"""
from remora.toolcall.schema import (
    ToolCallDecision,
    ToolCallOutcome,
    ToolCallTask,
    VALID_ACTIONS,
    VALID_DOMAINS,
    VALID_SEVERITIES,
)
from remora.toolcall.live_execution import (
    LiveExecutionTrace,
    LiveToolSandboxExecutor,
    aggregate_execution_metrics,
)

__all__ = [
    "ToolCallDecision",
    "ToolCallOutcome",
    "ToolCallTask",
    "VALID_ACTIONS",
    "VALID_DOMAINS",
    "VALID_SEVERITIES",
    "LiveExecutionTrace",
    "LiveToolSandboxExecutor",
    "aggregate_execution_metrics",
]
