# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The ACCEPT execution contract (issue #36 / AAE Gate B).

Until now an ACCEPT decision returned a signed single-use execution token
that the REST API had no way to redeem: ``/v1/execution/execute`` requires
an approved review item, so the ACCEPT branch had no governed dispatch
path and the SDK documented that as a boundary.

``POST /v1/execution/execute-accepted`` closes it. The token IS the
authorization — it is bound to the exact tool call at assess time — so
redemption re-presents the full payload, verifies the binding, consumes
the grant once, and dispatches through the same governed dispatcher the
review path uses. Everything the review path enforces still applies:
exact-payload binding, one-time consumption, lease-bound dispatch,
outbox intent, audit records.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.enforcement.outbox import OutboxState  # noqa: E402

READ_CALL = {
    "tool_name": "read_telemetry",
    "arguments": {"asset": "P-1"},
    "target_environment": "staging",
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "accept-contract-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "operator"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "agent-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(
        strict=True, audience=exec_mod.PEP_AUDIENCE
    )
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    return TestClient(api_mod.app)


def _accepted(client, call=None):
    """An assessment that produced an execution token, or skip honestly."""
    payload = call or READ_CALL
    r = client.post("/v1/execution/assess", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("execution_token") is None:
        pytest.skip(
            "no ACCEPT under this profile; the contract is exercised by the "
            "token-level tests below"
        )
    return body


def _mint_token(client, call=None, principal="agent-1"):
    """Mint an ACCEPT token directly for the given call.

    The research profile deliberately refuses probabilistic ACCEPT without
    server-side evidence, so a governed end-to-end ACCEPT is not reachable
    from /assess here. The token is what the endpoint consumes, so minting
    one is the honest way to exercise redemption — the same PDP issuance
    the assess ACCEPT branch performs.
    """
    from datetime import UTC, datetime, timedelta

    import servers.execution_api as exec_mod
    from remora.enforcement.token import PolicyDecisionToken
    from remora.policy.observation import canonical_tool_call_hash

    payload = call or READ_CALL
    registry = exec_mod.TOOL_REGISTRY.get(payload["tool_name"], {})
    target = str(registry.get("target_environment",
                              payload.get("target_environment", "prod")))
    call_hash = canonical_tool_call_hash(
        name=payload["tool_name"], arguments=payload["arguments"],
        tenant="acme", target=target,
    )
    now = datetime.now(UTC)
    # The conditions the decision is made under are signed in, exactly as the
    # assess ACCEPT branch does. A token minted without them is refused at
    # redemption rather than assumed to match (RMR-001).
    from remora.execution.service import authorization_context

    _obs, semantic = exec_mod._observation_with_context(
        exec_mod.ToolCallRequest(**payload), "acme"
    )
    token = PolicyDecisionToken.issue(
        action="accept",
        observation_hash=call_hash,
        request_id="p-accept-1",
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=300)).isoformat(),
        audience=exec_mod.PEP_AUDIENCE,
        context=authorization_context(
            tenant="acme", principal=principal, semantic=semantic,
            target_environment=payload.get("target_environment", "") or "",
            policy_bundle_hash=exec_mod._current_policy_bundle_hash(),
            toolspec_hash=str(exec_mod._resolve_toolspec(
                payload["tool_name"], payload["arguments"],
                payload.get("target_environment", "") or "")["hash"]),
        ),
    )
    return token.to_dict()


def _mod():
    import servers.execution_api as exec_mod

    return exec_mod


# ── The happy path ─────────────────────────────────────────────────────────

def test_accepted_token_redeems_and_dispatches(client) -> None:
    token = _mint_token(client)
    r = client.post("/v1/execution/execute-accepted", json={
        "execution_token": token, "tool_call": READ_CALL,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "execute"
    assert body["proposal_id"] == "p-accept-1"
    assert body["tool_execution"]["executed"] is True
    assert body["audit"]["entry_hash"]


def test_redemption_records_a_dispatch_intent(client) -> None:
    """The ACCEPT path gets the same crash-consistency as the review path."""
    token = _mint_token(client)
    r = client.post("/v1/execution/execute-accepted", json={
        "execution_token": token, "tool_call": READ_CALL,
    })
    assert r.status_code == 200
    rows = _mod()._outbox().rows_for_proposal("acme", r.json()["proposal_id"])
    assert len(rows) == 1
    assert rows[0].state is OutboxState.SUCCEEDED


# ── The refusals that make it safe ─────────────────────────────────────────

def test_replayed_token_is_refused(client) -> None:
    """One-time means one time: the second redemption never dispatches."""
    token = _mint_token(client)
    first = client.post("/v1/execution/execute-accepted", json={
        "execution_token": token, "tool_call": READ_CALL,
    })
    assert first.status_code == 200
    second = client.post("/v1/execution/execute-accepted", json={
        "execution_token": token, "tool_call": READ_CALL,
    })
    assert second.status_code == 409, second.text
    detail = second.json()["detail"].lower()
    assert "replay" in detail or "consumed" in detail, detail


def test_mutated_payload_is_refused(client) -> None:
    """The token authorizes an exact call; anything else is a different act."""
    token = _mint_token(client)
    mutated = dict(READ_CALL, arguments={"asset": "P-999"})
    r = client.post("/v1/execution/execute-accepted", json={
        "execution_token": token, "tool_call": mutated,
    })
    assert r.status_code == 409, r.text
    assert "binding" in r.json()["detail"].lower()
    # And the refusal must not have burned the grant for the real call.
    ok = client.post("/v1/execution/execute-accepted", json={
        "execution_token": token, "tool_call": READ_CALL,
    })
    assert ok.status_code == 200, ok.text


def test_unsigned_or_forged_token_is_refused(client) -> None:
    token = _mint_token(client)
    forged = dict(token, signature="0" * 64)
    r = client.post("/v1/execution/execute-accepted", json={
        "execution_token": forged, "tool_call": READ_CALL,
    })
    assert r.status_code in (401, 403, 409), r.text


def test_expired_token_is_refused(client) -> None:
    from datetime import UTC, datetime, timedelta

    import servers.execution_api as exec_mod
    from remora.enforcement.token import PolicyDecisionToken
    from remora.policy.observation import canonical_tool_call_hash

    past = datetime.now(UTC) - timedelta(hours=2)
    token = PolicyDecisionToken.issue(
        action="accept",
        observation_hash=canonical_tool_call_hash(
            name="read_telemetry", arguments={"asset": "P-1"},
            tenant="acme", target="staging"),
        request_id="p-expired",
        issued_at=past.isoformat(),
        expires_at=(past + timedelta(seconds=60)).isoformat(),
        audience=exec_mod.PEP_AUDIENCE,
    ).to_dict()
    r = client.post("/v1/execution/execute-accepted", json={
        "execution_token": token, "tool_call": READ_CALL,
    })
    assert r.status_code == 409, r.text


def test_non_accept_token_cannot_redeem(client) -> None:
    """Only an ACCEPT authorizes autonomous execution."""
    from datetime import UTC, datetime, timedelta

    import servers.execution_api as exec_mod
    from remora.enforcement.token import PolicyDecisionToken
    from remora.policy.observation import canonical_tool_call_hash

    now = datetime.now(UTC)
    token = PolicyDecisionToken.issue(
        action="verify",
        observation_hash=canonical_tool_call_hash(
            name="read_telemetry", arguments={"asset": "P-1"},
            tenant="acme", target="staging"),
        request_id="p-verify",
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=300)).isoformat(),
        audience=exec_mod.PEP_AUDIENCE,
    ).to_dict()
    r = client.post("/v1/execution/execute-accepted", json={
        "execution_token": token, "tool_call": READ_CALL,
    })
    assert r.status_code == 409, r.text
