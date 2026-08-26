# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Issue #419 (RMR-CR-004): the stable SDK survives the async 202.

The external deep review reproduced ``KeyError: 'audit'`` from
``RemoraClient.execute()`` against a server running REMORA_ASYNC_DISPATCH:
every 2xx was parsed as a finished ExecutionResult. The wire contract is
now a discriminated union — 200 → ExecutionResult, 202 (``dispatch:
pending``) → PendingExecution — and these tests pin it at the FT-13 wire
level (MockTransport, same style as test_sdk_client.py).
"""
from __future__ import annotations

import json

import pytest

httpx = pytest.importorskip("httpx")

from remora.sdk import (PendingExecution, RemoraClient,  # noqa: E402
                        ToolCall)

PENDING_BODY = {
    "proposal_id": "prop-async-1",
    "outcome": "execute",
    "detail": "authorized; dispatch pending",
    "dispatch": "pending",
    "outbox_id": "ob-1",
    "toolspec": None,
}

DONE_BODY = {
    "proposal_id": "prop-sync-1",
    "outcome": "execute",
    "detail": "",
    "audit": {"sequence_no": 7, "entry_hash": "e" * 64},
    "tool_execution": {"executed": True},
}


def _client(status_code: int, body: dict) -> RemoraClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/execution/execute"
        return httpx.Response(status_code, json=body)

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://remora.test",
    )
    return RemoraClient(
        base_url="http://remora.test",
        token="operator-token",
        http_client=http_client,
    )


def _call() -> ToolCall:
    return ToolCall(tool_name="store_artifact",
                    arguments={"artifact_id": "a-1"},
                    target_environment="staging")


def test_a_202_returns_pending_execution_not_a_crash() -> None:
    client = _client(202, PENDING_BODY)
    result = client.execute("item-1", _call())
    assert isinstance(result, PendingExecution)
    assert result.proposal_id == "prop-async-1"
    assert result.outbox_id == "ob-1"
    assert result.outcome == "execute"
    client.close()


def test_a_200_still_returns_a_finished_execution_result() -> None:
    client = _client(200, DONE_BODY)
    result = client.execute("item-1", _call())
    assert not isinstance(result, PendingExecution)
    assert result.audit.sequence_no == 7
    assert result.tool_execution["executed"] is True
    client.close()


def test_the_real_202_body_parses_as_pending() -> None:
    """The wire body the server actually emits in async mode (captured
    shape from tests/test_dispatch_worker.py) must round-trip."""
    real = {
        "proposal_id": "p", "outcome": "execute", "detail": "",
        "dispatch": "pending", "outbox_id": "ob-x",
        "toolspec": {"enforced": False, "hash": "", "version": 0},
    }
    parsed = PendingExecution.from_payload(json.loads(json.dumps(real)))
    assert parsed.outbox_id == "ob-x"
    assert parsed.raw["dispatch"] == "pending"
