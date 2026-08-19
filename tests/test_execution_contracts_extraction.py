# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Characterization for the #241 contracts extraction (slice 1).

The wire models moved verbatim to servers/execution_contracts.py. These tests
pin (a) aliasing — the API module re-exports the very same class objects, so
monkeypatching through either namespace stays equivalent; (b) layering — the
contracts module must stay pure wire models with no routing/persistence
imports; (c) the OpenAPI schema for /v1/execution/* is generated from the
extracted models (drift shows up in test_execution_openapi_contract.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CONTRACT_NAMES = [
    "GovernanceAction", "ExecutionOutcome", "ErrorDetail", "AuditRef",
    "SemanticAssessment", "ExecutionGrant", "PepResult",
    "ToolResultEnvelopeModel", "ToolExecutionResult",
    "ExecutionAssessResponse", "ExecutionApproveResponse",
    "ExecutionExecuteResponse", "ExecutionAuditVerifyResponse",
    "DerivationProposal", "ToolCallRequest", "ApproveRequest",
    "ExecuteRequest", "ExecuteAcceptedRequest", "RejectRequest",
    "EffectVerificationRequest",
]


def test_api_module_re_exports_identical_objects() -> None:
    import servers.execution_api as api
    import servers.execution_contracts as contracts

    for name in CONTRACT_NAMES:
        assert getattr(api, name) is getattr(contracts, name), name


def test_contracts_module_stays_pure_wire_layer() -> None:
    src = (
        Path(__file__).resolve().parents[1]
        / "servers" / "execution_contracts.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "fastapi", "APIRouter", "HTTPException",
        "TenantAuditChain", "ReviewQueue", "ExecutionOutbox",
        "EnforcementGate", "ExecutionLease", "sqlite3", "psycopg",
    ):
        assert forbidden not in src, (
            f"execution_contracts.py must stay wire-models-only; found {forbidden!r}"
        )


def test_request_models_still_validate() -> None:
    from servers.execution_contracts import RejectRequest, ToolCallRequest

    req = ToolCallRequest(tool_name="read_sensor", arguments={"sensor_id": "PT-101"})
    assert req.target_environment == "prod"

    import pytest as _pytest
    with _pytest.raises(Exception):
        RejectRequest(item_id="x", reason="")  # reason is mandatory, min_length=1
