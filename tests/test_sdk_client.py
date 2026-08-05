# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""FT-13 slice 1: RemoraClient wire behavior against a mock transport.

Verifies exactly what the client puts on the wire (paths, auth headers,
JSON bodies) and how HTTP failures map to the typed SDK error hierarchy —
SDK users must never have to interpret raw HTTP statuses.
"""
from __future__ import annotations

import json

import pytest

httpx = pytest.importorskip("httpx")

from remora.sdk import (  # noqa: E402
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    RateLimitedError,
    RemoraClient,
    RemoraUnavailableError,
    ServerError,
    ToolCall,
)

CALL = ToolCall(
    tool_name="read_telemetry",
    arguments={"asset": "P-1"},
    target_environment="staging",
)

ACCEPT_BODY = {
    "proposal_id": "p-1",
    "decision": "accept",
    "reasons": ["low_risk_read"],
    "tool_call_hash": "a" * 64,
    "semantic": {
        "tool_contract_bundle_hash": "",
        "state_hash": "",
        "intent_authority_hash": "",
        "tool_matches_goal": None,
        "expected_effect_matches": None,
    },
    "execution_token": {"jti": "j-1"},
    "audit": {"sequence_no": 0, "entry_hash": "d" * 64},
}


def _client_for(handler) -> RemoraClient:
    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://remora.test",
    )
    return RemoraClient(
        base_url="http://remora.test",
        token="operator-token",
        http_client=http_client,
    )


def test_assess_sends_contract_request_and_parses_response() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=ACCEPT_BODY)

    with _client_for(handler) as client:
        result = client.assess(CALL)

    assert seen["method"] == "POST"
    assert seen["path"] == "/v1/execution/assess"
    assert seen["auth"] == "Bearer operator-token"
    assert seen["body"] == {
        "tool_name": "read_telemetry",
        "arguments": {"asset": "P-1"},
        "target_environment": "staging",
    }
    assert result.proposal_id == "p-1"
    assert result.action.value == "accept"
    assert result.execution_token == {"jti": "j-1"}


def test_tenant_and_role_headers_are_sent_when_configured() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["tenant"] = request.headers.get("X-Remora-Tenant")
        seen["role"] = request.headers.get("X-Remora-Role")
        return httpx.Response(200, json=ACCEPT_BODY)

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://remora.test",
    )
    client = RemoraClient(
        base_url="http://remora.test",
        token="t",
        tenant="acme",
        role="operator",
        http_client=http_client,
    )
    client.assess(CALL)
    client.close()
    assert seen["tenant"] == "acme"
    assert seen["role"] == "operator"


def test_approve_sends_item_and_ttl() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "status": "approved",
            "proposal_id": "p-2",
            "item_id": "item-7",
            "expires_at": "2026-08-05T12:00:00+00:00",
            "audit": {"sequence_no": 4, "entry_hash": "e" * 64},
        })

    with _client_for(handler) as client:
        approval = client.approve("item-7", ttl_seconds=600,
                                  on_behalf_of="employee-1")

    assert seen["path"] == "/v1/execution/approve"
    assert seen["body"] == {
        "item_id": "item-7",
        "approval_ttl_seconds": 600,
        "on_behalf_of": "employee-1",
    }
    assert approval.status == "approved"
    assert approval.item_id == "item-7"
    assert approval.audit.sequence_no == 4


def test_execute_represents_full_payload() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "proposal_id": "p-2",
            "outcome": "execute",
            "detail": "executed",
            "audit": {"sequence_no": 5, "entry_hash": "f" * 64},
            "execution_grant": {"jti": "j-2"},
            "pep": {"allowed": True, "reason": "ok"},
            "tool_execution": {"executed": True},
        })

    with _client_for(handler) as client:
        outcome = client.execute("item-7", CALL)

    assert seen["path"] == "/v1/execution/execute"
    # Exact payload re-presentation: the server re-binds every argument.
    assert seen["body"] == {"item_id": "item-7", "tool_call": CALL.to_payload()}
    assert outcome.outcome == "execute"
    assert outcome.pep == {"allowed": True, "reason": "ok"}


def test_execute_conditional_keys_absent_map_to_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "proposal_id": "p-2",
            "outcome": "approval_expired",
            "detail": "approval expired",
            "audit": {"sequence_no": 6, "entry_hash": "a" * 64},
        })

    with _client_for(handler) as client:
        outcome = client.execute("item-7", CALL)

    assert outcome.outcome == "approval_expired"
    assert outcome.execution_grant is None
    assert outcome.pep is None
    assert outcome.tool_execution is None


def test_verify_audit_chain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/execution/audit/verify"
        assert request.method == "GET"
        return httpx.Response(200, json={
            "tenant": "acme", "valid": True, "problems": [],
            "records_checked": 6, "empty": False,
        })

    with _client_for(handler) as client:
        verification = client.verify_audit_chain()

    assert verification.valid is True
    assert verification.problems == ()
    assert verification.records_checked == 6


@pytest.mark.parametrize("status,detail,exc_type", [
    (401, "missing bearer token", AuthenticationError),
    (403, "capability not permitted", AuthorizationError),
    (404, "unknown review item", NotFoundError),
    (409, "item is not pending", ConflictError),
    (422, "validation error", InvalidRequestError),
])
def test_http_statuses_map_to_typed_errors(status, detail, exc_type) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": detail})

    with _client_for(handler) as client:
        with pytest.raises(exc_type) as excinfo:
            client.assess(CALL)

    assert detail in str(excinfo.value)
    assert excinfo.value.retryable is False


def test_rate_limit_maps_to_retryable_error_with_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "rate limit exceeded"},
                              headers={"Retry-After": "60"})

    with _client_for(handler) as client:
        with pytest.raises(RateLimitedError) as excinfo:
            client.assess(CALL)

    assert excinfo.value.retryable is True
    assert excinfo.value.retry_after == 60.0


def test_server_error_carries_correlation_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={
            "detail": "An internal error occurred.",
            "correlation_id": "c0ffee00",
        })

    with _client_for(handler) as client:
        with pytest.raises(ServerError) as excinfo:
            client.assess(CALL)

    assert excinfo.value.request_id == "c0ffee00"


def test_transport_failure_maps_to_retryable_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with _client_for(handler) as client:
        with pytest.raises(RemoraUnavailableError) as excinfo:
            client.assess(CALL)

    assert excinfo.value.retryable is True


def test_non_json_error_body_still_raises_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    with _client_for(handler) as client:
        with pytest.raises(ServerError):
            client.assess(CALL)
