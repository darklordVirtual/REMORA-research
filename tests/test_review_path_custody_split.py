# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The human-approval path across the custody split (ADR-A).

The deployed split was verified on the ACCEPT path: assess reaches ACCEPT, the
authority signs, the executor dispatches. The REVIEW path -- VERIFY/ESCALATE,
a human approves, then the agent redeems -- was not exercised against the
deployment, because approving requires a role credential this session does not
hold.

That is exactly the gap that produced NEGATIVE_RESULTS §45 twice in one day:
both defects were invisible to a green suite and to the reading of the code,
and both were found only by running the other half. "It goes through the same
wrapper" is the reasoning that failed, so it is not relied on here.

These tests run the whole review path through the real API with the
authority/execution hop stubbed at the transport, so everything above the wire
is the production code: the queue, the approval, the freshness re-gate, the
one-time grant, lease issuance on the authority side, and the forward.

What they do NOT establish is that the deployed review path works. That
remains untested on the deployment and is recorded as such.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _security_extra import require_security_extra  # noqa: E402

from remora.enforcement import lease_signing as signing  # noqa: E402
from remora.execution import remote_dispatch as rd  # noqa: E402
from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402

# Skips locally without the 'security' extra; fails hard in CI.
require_security_extra()

from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402

WRITE = {
    "tool_name": "update_work_order",
    "arguments": {"work_order_id": "WO-42", "status": "closed"},
    "target_environment": "prod",
}


@pytest.fixture()
def authority(monkeypatch):
    """The API process configured as the AUTHORITY domain."""
    key = ed25519.Ed25519PrivateKey.generate()
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "review-split-token-key")
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE,
                       key.private_bytes_raw().hex())
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC,
                       key.public_key().public_bytes_raw().hex())
    monkeypatch.delenv(signing.ENV_HMAC, raising=False)
    monkeypatch.setenv(rd.ENDPOINT_ENV, "http://execution.internal")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE",
                       "tests.dispatcher_registry_fixture")

    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from tests import dispatcher_registry_fixture as registry

    registry.CALLS.clear()
    registry.RAISE["update_work_order"] = False
    monkeypatch.setattr(api_mod, "_authenticate",
                        lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role",
                        lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(
        strict=True, audience=exec_mod.PEP_AUDIENCE)
    exec_mod._reset_tool_dispatcher()
    return TestClient(api_mod.app), registry


def _approved(client) -> str:
    item_id = client.post("/v1/execution/assess", json=WRITE
                          ).json()["review_item_id"]
    client.post("/v1/execution/approve",
                json={"item_id": item_id, "approval_ttl_seconds": 900})
    return item_id


def test_the_review_path_forwards_to_the_execution_domain(authority,
                                                          monkeypatch):
    """A human-approved call is executed by the executor, not the authority."""
    client, registry = authority
    sent: list = []

    def capture(url, payload, timeout):
        sent.append(payload)
        return {"tool_execution": {"executed": True, "result": "closed"}}

    monkeypatch.setattr(rd, "_post", capture)

    body = client.post("/v1/execution/execute",
                       json={"item_id": _approved(client),
                             "tool_call": WRITE}).json()

    assert body["tool_execution"]["executed"] is True
    assert len(sent) == 1, "the approved call must cross the custody boundary"
    assert sent[0]["lease"]["sig_alg"] == signing.ALG_ED25519, (
        "the authority must sign the approved call with its private key")
    assert sent[0]["tool_call"]["arguments"] == WRITE["arguments"]
    assert registry.CALLS == [], (
        "the AUTHORITY holds no tool callables and must not have run the tool")


def test_the_approved_lease_binds_the_approved_call(authority, monkeypatch):
    """Approval authorises one act, and the lease that crosses says which.

    The forwarded lease must carry the proposal identity and the exact
    arguments, or the executor has nothing to check the call against and the
    approval becomes a general permission.
    """
    client, _registry = authority
    sent: list = []
    monkeypatch.setattr(rd, "_post", lambda u, p, t: sent.append(p) or {
        "tool_execution": {"executed": True}})

    client.post("/v1/execution/execute",
                json={"item_id": _approved(client), "tool_call": WRITE})

    lease = sent[0]["lease"]
    assert lease["tool_name"] == WRITE["tool_name"]
    assert lease["target_environment"] == WRITE["target_environment"]
    assert lease["tenant_id"] == "acme"
    assert lease["proposal_id"], "the lease must carry the proposal identity"
    assert lease["nonce"], "single-use is the executor's to enforce"


def test_an_unreachable_executor_leaves_the_review_item_unexecuted(
        authority, monkeypatch):
    """An outage on the hop must not report the approved work as done."""
    import urllib.error

    client, registry = authority
    monkeypatch.setattr(rd, "_post", lambda *a, **k: (_ for _ in ()).throw(
        urllib.error.URLError("execution domain down")))

    body = client.post("/v1/execution/execute",
                       json={"item_id": _approved(client),
                             "tool_call": WRITE}).json()

    assert body["tool_execution"]["executed"] is False
    assert body["tool_execution"]["refusal_reason"] == (
        "execution_domain_unreachable")
    assert registry.CALLS == []


def test_an_unapproved_item_never_reaches_the_execution_domain(authority,
                                                               monkeypatch):
    """The approval gate still runs on the authority, before the hop.

    If a refusal could reach the executor, the split would have moved the
    decision rather than the execution.
    """
    client, _registry = authority
    sent: list = []
    monkeypatch.setattr(rd, "_post", lambda u, p, t: sent.append(p) or {})

    item_id = client.post("/v1/execution/assess", json=WRITE
                          ).json()["review_item_id"]
    response = client.post("/v1/execution/execute",
                           json={"item_id": item_id, "tool_call": WRITE})

    assert response.status_code != 200 or (
        response.json()["tool_execution"]["executed"] is False)
    assert sent == [], "an unapproved item must not cross the boundary"


def test_a_mutated_call_never_reaches_the_execution_domain(authority,
                                                           monkeypatch):
    """Exact-call binding is checked before the hop, not only after it.

    The executor would refuse it anyway. Refusing here as well means a mutated
    call costs nothing on the far side and leaves no ambiguity about which
    domain rejected it.
    """
    client, _registry = authority
    sent: list = []
    monkeypatch.setattr(rd, "_post", lambda u, p, t: sent.append(p) or {})

    mutated = {**WRITE, "arguments": {"work_order_id": "WO-999",
                                      "status": "closed"}}
    response = client.post("/v1/execution/execute",
                           json={"item_id": _approved(client),
                                 "tool_call": mutated})
    body = response.json()

    # The refusal shape differs from a dispatch refusal: the binding check runs
    # before a lease exists, so the response carries no tool_execution at all.
    # Asserted as it is rather than forced into the dispatch shape.
    executed = (body.get("tool_execution") or {}).get("executed")
    assert executed is not True, f"a mutated call must not execute: {body}"
    assert sent == [], "a mutated call must not cross the boundary"
