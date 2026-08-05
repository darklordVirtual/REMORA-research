# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""FT-13 slice 1: RemoraClient end-to-end against the real ASGI app.

Runs the full governed loop through the SDK only — assess, approve,
execute, audit verify — against ``servers.api`` in-process. The SDK is
exercised exactly as a third party would use it: no internal imports
beyond the test fixture's auth shim.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402
from remora.sdk import DecisionAction, RemoraClient, ToolCall  # noqa: E402


@pytest.fixture()
def sdk_client(monkeypatch):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "sdk-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role",
                        lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE)
    exec_mod._reset_tool_dispatcher()
    # TestClient is an httpx.Client bound to the ASGI app; inject it so the
    # SDK talks to the real server stack in-process.
    client = RemoraClient(base_url="http://testserver", token="test-token",
                          http_client=TestClient(api_mod.app))
    yield client
    client.close()


def test_unknown_tool_abstains_with_neither_token_nor_review_item(sdk_client) -> None:
    # read_telemetry is not in the tool registry: the registry-only path
    # abstains (same expectation as test_execution_api.py's LOW_READ).
    # ABSTAIN is the "neither" branch of the contract — no execution token,
    # no review item, but still a proposal id and an audit chain entry.
    result = sdk_client.assess(ToolCall(
        tool_name="read_telemetry",
        arguments={"asset": "P-1"},
        target_environment="staging",
        schema_valid=True,
    ))
    assert result.action is DecisionAction.ABSTAIN
    assert result.execution_token is None
    assert result.review_item_id is None
    assert result.proposal_id
    assert result.audit.entry_hash


def test_production_write_review_loop_through_sdk_only(sdk_client) -> None:
    call = ToolCall(
        tool_name="update_work_order",
        arguments={"order": "WO-1", "action": "reschedule"},
        target_environment="prod",
        schema_valid=True,
        rollback_available=True,
    )
    assessment = sdk_client.assess(call)
    assert assessment.action in (DecisionAction.VERIFY, DecisionAction.ESCALATE)
    assert assessment.review_item_id is not None
    assert assessment.execution_token is None

    approval = sdk_client.approve(assessment.review_item_id,
                                  on_behalf_of="employee-1")
    assert approval.status == "approved"
    assert approval.proposal_id == assessment.proposal_id

    outcome = sdk_client.execute(assessment.review_item_id, call)
    assert outcome.proposal_id == assessment.proposal_id
    assert outcome.outcome == "execute"
    assert outcome.pep is not None and outcome.pep["allowed"] is True

    verification = sdk_client.verify_audit_chain()
    assert verification.valid is True
    assert verification.problems == ()
    assert verification.records_checked >= 3
