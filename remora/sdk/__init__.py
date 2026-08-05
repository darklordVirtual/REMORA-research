# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REMORA SDK — the small, stable entry point for third-party integrators.

External applications depend on this namespace and the versioned REST
contract (``schemas/openapi.json``), never on REMORA's internal modules
(``remora.policy``, ``remora.enforcement``, ...), which may change
without notice. This surface is snapshot-gated in CI
(``artifacts/sdk/public_api_v1.json``): a public symbol cannot be
removed without a deliberate, reviewed snapshot update.

Stability: this is the intended stable surface; pre-1.0 it may still
change in minor versions, with changes recorded in the CHANGELOG.

Typical use::

    from remora.sdk import RemoraClient, ToolCall, DecisionAction

    client = RemoraClient("https://remora.internal", token="...")
    result = client.assess(ToolCall(
        tool_name="set_valve_position",
        arguments={"valve": "V-18", "position_pct": 35},
        target_environment="production",
        intent_ref="WO-1204",
    ))
    if result.action is DecisionAction.ACCEPT:
        ...
"""
from __future__ import annotations

from remora.sdk.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    RateLimitedError,
    RemoraError,
    RemoraUnavailableError,
    ServerError,
)
from remora.sdk.models import (
    ApprovalResult,
    AssessmentResult,
    AuditRef,
    AuditVerification,
    DecisionAction,
    ExecutionResult,
    SemanticAssessment,
    ToolCall,
)

__all__ = [
    "ApprovalResult",
    "AssessmentResult",
    "AuditRef",
    "AuditVerification",
    "AuthenticationError",
    "AuthorizationError",
    "ConflictError",
    "DecisionAction",
    "ExecutionResult",
    "InvalidRequestError",
    "NotFoundError",
    "RateLimitedError",
    "RemoraClient",
    "RemoraError",
    "RemoraUnavailableError",
    "SemanticAssessment",
    "ServerError",
    "ToolCall",
]


def __getattr__(name: str) -> object:
    # RemoraClient needs httpx (the ``sdk`` extra); import lazily so the
    # models and errors stay importable in dependency-free environments.
    if name == "RemoraClient":
        from remora.sdk.client import RemoraClient

        return RemoraClient
    raise AttributeError(f"module 'remora.sdk' has no attribute {name!r}")
