# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""FT-13: AsyncRemoraClient mirrors the sync client's wire contract.

Same paths, same auth headers, same bodies, same typed-error mapping —
verified against a mock transport with ``asyncio.run`` (no async test
plugin needed, so no new CI dependency). The async client must never
drift from the sync one: both share the status→error mapping.
"""
from __future__ import annotations

import asyncio
import json

import pytest

httpx = pytest.importorskip("httpx")

from remora.sdk import (  # noqa: E402
    AsyncRemoraClient,
    AuthorizationError,
    RemoraUnavailableError,
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


def _client_for(handler) -> AsyncRemoraClient:
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://remora.test",
    )
    return AsyncRemoraClient(
        base_url="http://remora.test",
        token="operator-token",
        http_client=http_client,
    )


def test_async_assess_sends_contract_request_and_parses_response() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=ACCEPT_BODY)

    async def run():
        async with _client_for(handler) as client:
            return await client.assess(CALL)

    result = asyncio.run(run())
    assert seen["method"] == "POST"
    assert seen["path"] == "/v1/execution/assess"
    assert seen["auth"] == "Bearer operator-token"
    assert seen["body"]["tool_name"] == "read_telemetry"
    assert result.proposal_id == "p-1"
    assert result.action.value == "accept"


def test_async_error_mapping_matches_sync() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "role may not approve"})

    async def run():
        async with _client_for(handler) as client:
            await client.approve("item-1")

    with pytest.raises(AuthorizationError) as exc:
        asyncio.run(run())
    assert exc.value.code == "authorization_denied"


def test_async_transport_failure_maps_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async def run():
        async with _client_for(handler) as client:
            await client.verify_audit_chain()

    with pytest.raises(RemoraUnavailableError):
        asyncio.run(run())


def test_async_full_loop_against_inprocess_app(monkeypatch) -> None:
    """ASGITransport: the async client drives the real app in-process."""
    pytest.importorskip("fastapi")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "async-sdk-test-key")
    import servers.api as api_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "operator"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)

    async def run():
        transport = httpx.ASGITransport(app=api_mod.app)
        http_client = httpx.AsyncClient(
            transport=transport, base_url="http://demo",
        )
        async with AsyncRemoraClient(
            base_url="http://demo", token="t", http_client=http_client,
        ) as client:
            return await client.assess(CALL)

    result = asyncio.run(run())
    assert result.proposal_id
    assert result.action.name in {"ACCEPT", "VERIFY", "ABSTAIN", "ESCALATE"}
