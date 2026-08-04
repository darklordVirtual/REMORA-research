# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The /v1/execution contract must be machine-readable.

External contract review (2026-08-05): most execution responses were untyped
free objects, the four execution operations carried no descriptions, and no
error statuses were documented — a client generated from the schema saw only
``Record<string, unknown>``. The typed models are documentation-only
(``responses={200: {"model": ...}}``): handlers keep returning plain dicts so
the wire format — including conditional keys that are ABSENT, never null —
stays byte-identical (pinned by tests/test_execution_api.py).
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import servers.api as api_mod  # noqa: E402

client = TestClient(api_mod.app)

EXECUTION_OPS = {
    "/v1/execution/assess": "post",
    "/v1/execution/approve": "post",
    "/v1/execution/execute": "post",
    "/v1/execution/audit/verify": "get",
}


def _openapi() -> dict:
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    return resp.json()


def test_execution_response_models_are_declared() -> None:
    schemas = _openapi().get("components", {}).get("schemas", {})
    for model in ("ExecutionAssessResponse", "ExecutionApproveResponse",
                  "ExecutionExecuteResponse", "ExecutionAuditVerifyResponse",
                  "ErrorDetail"):
        assert model in schemas, f"missing response model {model}"


def test_decision_and_outcome_are_closed_enums() -> None:
    schemas = _openapi()["components"]["schemas"]
    decision = schemas["ExecutionAssessResponse"]["properties"]["decision"]
    outcome = schemas["ExecutionExecuteResponse"]["properties"]["outcome"]
    # $ref or inline — resolve either way.
    def enum_of(prop: dict) -> list:
        if "$ref" in prop:
            name = prop["$ref"].rsplit("/", 1)[-1]
            return schemas[name].get("enum", [])
        return prop.get("enum", [])
    assert set(enum_of(decision)) == {"accept", "verify", "abstain", "escalate"}
    assert set(enum_of(outcome)) == {"execute", "approval_expired",
                                     "binding_refused", "approval_invalidated"}


def test_every_execution_operation_has_a_description() -> None:
    spec = _openapi()
    for path, method in EXECUTION_OPS.items():
        op = spec["paths"][path][method]
        text = (op.get("description") or "").strip()
        assert len(text) > 40, f"{method.upper()} {path} has no real description"


def test_error_statuses_are_documented() -> None:
    spec = _openapi()
    expected = {
        "/v1/execution/assess": {"401", "403"},
        "/v1/execution/approve": {"401", "403", "404", "409"},
        "/v1/execution/execute": {"401", "403", "404", "409"},
        "/v1/execution/audit/verify": {"401", "403"},
    }
    for path, statuses in expected.items():
        op = spec["paths"][path][EXECUTION_OPS[path]]
        documented = set(op.get("responses", {}))
        missing = statuses - documented
        assert not missing, f"{path} does not document {sorted(missing)}"
