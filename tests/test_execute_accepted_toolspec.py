# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The direct-ACCEPT path binds the ToolSpec it was assessed under.

``/execute-accepted`` resolved no spec at all. The lease it minted carried an
empty ``toolspec_hash`` while the dispatcher's resolver reported the live one,
so with ``REMORA_TOOLSPEC_BUNDLE`` configured every redemption refused with
``toolspec_hash_mismatch`` — and it refused AFTER the single-use grant had been
consumed, which made a retry impossible for a call the caller never got wrong.

Four properties, in the order they matter: a redemption under the assessed
spec executes; a spec that moved between assessment and redemption refuses;
that refusal happens before consumption, so the grant survives it; and the
authorization context binds the environment, the policy bundle and the spec
identity rather than three empty strings (RMR-001).

The research profile does not produce a probabilistic ACCEPT from ``/assess``,
so the token is minted the way the assess ACCEPT branch mints it — same
issuer, same context — which is what redemption consumes.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi")

from tests.test_toolspec_execution_wiring import (  # noqa: E402
    _bundle_file,
    _client,
    _mod,
    _spec,
)

READ_SPEC = dict(
    tool_id="read_telemetry",
    action_type="read",
    risk_tier="low",
    description="Read telemetry for one asset.",
    argument_schema={
        "type": "object",
        "properties": {"asset": {"type": "string"}},
        "required": ["asset"],
        "additionalProperties": False,
    },
    semantic_contract={
        "capability": "telemetry_read", "effect": "read",
        "resource_type": "telemetry", "mutation": False,
        "argument_roles": {"asset": "target_resource"},
    },
    credential_scope=["telemetry:read"],
    capabilities=["telemetry_read"],
)

CALL = {
    "tool_name": "read_telemetry",
    "arguments": {"asset": "P-1"},
    "target_environment": "prod",
    "schema_valid": True,
}
PRINCIPAL = "employee-1"


def _specs(read_version: int = 1) -> list[dict]:
    return [_spec(), _spec(**dict(READ_SPEC, version=read_version))]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    return _client(monkeypatch, tmp_path, bundle_path=_bundle_file(
        tmp_path, _specs(), name="accept-bundle.json"))


def _context(exec_mod, semantic, tool_call):
    """The conditions a decision on this call is made under, in this process.

    Built from the same three sources the assess ACCEPT branch uses: the
    call's target, the policy bundle in force and the resolved spec identity.
    """
    from remora.execution.service import authorization_context

    identity = exec_mod._resolve_toolspec(
        tool_call.tool_name, tool_call.arguments, tool_call.target_environment)
    return authorization_context(
        tenant="acme", principal=PRINCIPAL, semantic=semantic,
        target_environment=tool_call.target_environment or "",
        policy_bundle_hash=exec_mod._current_policy_bundle_hash(),
        toolspec_hash=str(identity["hash"]),
    )


def _mint(client, *, proposal_id: str = "p-accept-1") -> tuple[dict, str]:
    """An ACCEPT token for CALL, minted as the assess ACCEPT branch mints it."""
    from remora.enforcement.token import PolicyDecisionToken

    exec_mod = _mod()
    tool_call = exec_mod.ToolCallRequest(**CALL)
    obs, semantic = exec_mod._observation_with_context(tool_call, "acme")
    now = datetime.now(UTC)
    token = PolicyDecisionToken.issue(
        action="accept",
        observation_hash=obs.tool_call_hash or "",
        request_id=proposal_id,
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=300)).isoformat(),
        audience=exec_mod.PEP_AUDIENCE,
        context=_context(exec_mod, semantic, tool_call),
    )
    return token.to_dict(), str(obs.tool_call_hash or "")


def _record_assessment(proposal_id: str) -> str:
    """The assessed record the drift comparison reads back from the chain."""
    exec_mod = _mod()
    identity = exec_mod._resolve_toolspec(
        CALL["tool_name"], CALL["arguments"], CALL["target_environment"])
    exec_mod._CHAIN.append("acme", {
        "event": "assessed",
        "proposal_id": proposal_id,
        "decision": "accept",
        "toolspec_hash": identity["hash"],
    })
    return str(identity["hash"])


def _redeploy(monkeypatch, tmp_path, *, version: int, name: str) -> None:
    monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE", str(_bundle_file(
        tmp_path, _specs(version), name=name)))
    _mod()._reset_toolspec_bundle()
    _mod()._reset_tool_dispatcher()


def _redeem(client, token):
    return client.post("/v1/execution/execute-accepted", json={
        "execution_token": token, "tool_call": CALL,
    })


def test_execute_accepted_succeeds_with_a_bundle_configured(client) -> None:
    token, _ = _mint(client)
    response = _redeem(client, token)
    assert response.status_code == 200, response.text
    execution = response.json()["tool_execution"]
    assert execution["executed"] is True, execution
    assert execution.get("refusal_reason") is None


def test_the_lease_binds_the_resolved_spec(client) -> None:
    """The identity the dispatcher checks is the one the redemption resolved."""
    token, _ = _mint(client)
    assert _redeem(client, token).status_code == 200
    events = [e.payload for e in _mod()._CHAIN.entries("acme")]
    authorized = [e for e in events if e["event"] == "execution_authorized"]
    assert authorized, events
    assert not any(e.get("tool_refusal_reason") == "toolspec_hash_mismatch"
                   for e in events)


def test_a_spec_that_moved_since_assessment_refuses(
    client, monkeypatch, tmp_path,
) -> None:
    token, _ = _mint(client)
    _record_assessment("p-accept-1")
    _redeploy(monkeypatch, tmp_path, version=2, name="accept-bundle2.json")

    response = _redeem(client, token)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == \
        "toolspec_changed_between_assess_and_dispatch"
    assert any(e.payload.get("event") == "execution_toolspec_changed"
               for e in _mod()._CHAIN.entries("acme"))


def test_a_refusal_before_consumption_leaves_no_authorization(
    client, monkeypatch, tmp_path,
) -> None:
    token, _ = _mint(client)
    _record_assessment("p-accept-1")
    _redeploy(monkeypatch, tmp_path, version=2, name="accept-bundle3.json")
    assert _redeem(client, token).status_code == 409

    assert not any(
        entry.payload.get("event") == "execution_authorized"
        for entry in _mod()._CHAIN.entries("acme")
    ), "a refused redemption must leave no authorization behind"


def test_a_pre_consumption_refusal_leaves_the_grant_redeemable(
    client, monkeypatch, tmp_path,
) -> None:
    token, _ = _mint(client)
    _record_assessment("p-accept-1")
    original = os.environ["REMORA_TOOLSPEC_BUNDLE"]
    _redeploy(monkeypatch, tmp_path, version=2, name="accept-bundle4.json")
    assert _redeem(client, token).status_code == 409

    # The deployment rolls the spec back; the untouched grant still works.
    monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE", original)
    _mod()._reset_toolspec_bundle()
    _mod()._reset_tool_dispatcher()
    retried = _redeem(client, token)
    assert retried.status_code == 200, retried.text
    assert retried.json()["tool_execution"]["executed"] is True


def test_the_authorization_context_binds_environment_bundle_and_spec(
    client,
) -> None:
    """RMR-001: three fields that were always the empty string."""
    exec_mod = _mod()
    tool_call = exec_mod.ToolCallRequest(**CALL)
    _obs, semantic = exec_mod._observation_with_context(tool_call, "acme")
    context = _context(exec_mod, semantic, tool_call)
    assert context.target_environment == "prod"
    assert context.policy_bundle_hash
    assert len(context.toolspec_hash) == 64
    assert context.toolspec_hash != semantic["tool_contract_bundle_hash"]
