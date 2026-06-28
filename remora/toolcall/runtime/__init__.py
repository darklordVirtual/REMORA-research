# Author: Stian Skogbrott
# License: Apache-2.0
"""Runtime-safe sub-package for remora.toolcall.

Contains only types and functions that are safe for policy gates to use.
No evaluation labels, no ground-truth fields.

Architectural boundary (REM-016): code in this package must never import
from remora.toolcall.evaluation.
"""
from __future__ import annotations

from remora.toolcall.schema import (
    ToolCallDecision,
    ToolCallOutcome,
    ToolCallTask,
    VALID_ACTIONS,
    VALID_DOMAINS,
    VALID_SEVERITIES,
)
from remora.toolcall.remora_gate import RemoraToolCallGate

__all__ = [
    "ToolCallDecision",
    "ToolCallOutcome",
    "ToolCallTask",
    "VALID_ACTIONS",
    "VALID_DOMAINS",
    "VALID_SEVERITIES",
    "RemoraToolCallGate",
]
