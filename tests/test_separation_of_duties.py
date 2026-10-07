# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-CR-004: an approver must be a different principal from the proposer.

Before: approval checked role membership only, and ``admin`` holds assess,
review and execute. One admin credential could propose a call, approve its
own escalation and execute it; the chain recorded a "human" approval. Probe
at b9ade2b: ReviewQueue.approve by the proposing principal succeeded.

After: under a strict profile (and wherever REMORA_REQUIRE_DISTINCT_APPROVER
is set) /v1/execution/approve refuses with 403 when the approver is the
principal named on the proposal's ``assessed`` event, whatever its role, and
refuses when the proposer cannot be established. The approval event records
both principals.
"""
from __future__ import annotations

import os

os.environ.setdefault("REMORA_ENV", "development")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PROD_WRITE = {
    "tool_name": "update_work_order",
    "arguments": {"order": "WO-1", "action": "reschedule"},
    "target_environment": "prod",
}


@pytest.fixture()
def caller(monkeypatch):
    """A client whose authenticated principal the test can switch."""
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "sod-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_REQUIRE_DISTINCT_APPROVER", "1")
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    who = {"principal": "agent-1"}
    # admin holds every capability: the rule must not depend on role.
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "admin"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: who["principal"])
    from remora.governance.tenant_chain import TenantAuditChain

    # Same reset as tests/test_execution_api.py's client fixture.
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    monkeypatch.setattr(exec_mod, "_CHAIN", TenantAuditChain())
    monkeypatch.setattr(exec_mod, "_GATE", exec_mod.EnforcementGate(
        strict=True, audience=exec_mod.PEP_AUDIENCE))
    exec_mod._reset_tool_dispatcher()
    client = TestClient(api_mod.app)
    return client, who


def _queue(client) -> tuple[str, str]:
    body = client.post("/v1/execution/assess", json=PROD_WRITE).json()
    assert body["decision"] == "verify", body
    return body["review_item_id"], body["proposal_id"]


def _approve(client, item_id):
    return client.post("/v1/execution/approve",
                       json={"item_id": item_id, "approval_ttl_seconds": 900})


def test_the_proposer_cannot_approve_its_own_call_even_as_admin(caller) -> None:
    client, who = caller
    item_id, _ = _queue(client)
    r = _approve(client, item_id)
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "approver_is_proposer"


def test_a_different_principal_can_approve_and_both_are_recorded(caller) -> None:
    import servers.execution_api as exec_mod

    client, who = caller
    item_id, proposal_id = _queue(client)
    who["principal"] = "human-reviewer-1"
    r = _approve(client, item_id)
    assert r.status_code == 200, r.text
    approved = [e.payload for e in exec_mod._CHAIN.entries("acme")
                if e.payload.get("event") == "approved"
                and e.payload.get("proposal_id") == proposal_id]
    assert len(approved) == 1
    assert approved[0]["actor"] == "human-reviewer-1"
    assert approved[0]["proposer"] == "agent-1"


def test_a_refused_self_approval_leaves_the_item_for_someone_else(caller) -> None:
    client, who = caller
    item_id, _ = _queue(client)
    assert _approve(client, item_id).status_code == 403
    who["principal"] = "human-reviewer-2"
    assert _approve(client, item_id).status_code == 200


def test_an_unknown_proposer_is_refused_not_assumed_distinct() -> None:
    from remora.execution.review_service import proposer_of

    class _Entry:
        def __init__(self, payload):
            self.payload = payload

    class _Chain:
        def __init__(self, payloads):
            self._e = [_Entry(p) for p in payloads]

        def entries(self, tenant):
            return tuple(self._e)

    assert proposer_of(_Chain([]), "t", "p") is None
    two = _Chain([{"event": "assessed", "proposal_id": "p", "actor": "a"},
                  {"event": "assessed", "proposal_id": "p", "actor": "b"}])
    assert proposer_of(two, "t", "p") is None
    one = _Chain([{"event": "assessed", "proposal_id": "p", "actor": "a"}])
    assert proposer_of(one, "t", "p") == "a"


@pytest.mark.parametrize(("profile", "flag", "expected"), [
    ("review", "", True), ("controlled_pilot", "", True),
    ("research", "", False), ("research", "1", True), ("development", "", False),
])
def test_strict_profiles_always_require_a_distinct_approver(
    monkeypatch, profile, flag, expected
) -> None:
    import servers.execution_api as exec_mod

    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", profile)
    monkeypatch.setenv("REMORA_REQUIRE_DISTINCT_APPROVER", flag)
    assert exec_mod._distinct_approver_required() is expected
