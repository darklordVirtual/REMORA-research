# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-001 and RMR-008: what a direct ACCEPT token authorizes, and to whom.

The signed token carried the action, a hash of the call, timestamps, a one-time
id and an audience. Tenant and target were covered transitively, because
``canonical_tool_call_hash`` takes them into its preimage. The principal the
decision was made for, the policy bundle it was decided under and the tool
contract it was decided against were not bound at all, and the redeeming path
deliberately does not re-run the engine.

Two consequences, both reproduced by the external review and both tested here:
a token minted for one principal was redeemable by another with the same
capability in the same tenant, and a call reclassified after issuance still
executed on the old authorization.

The response contract is the third case. ``outcome`` was set to EXECUTE before
dispatch and never revised, so a pre-dispatch refusal answered HTTP 200 saying
execute while the nested result said executed=false.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def client_and_mod(monkeypatch, tmp_path):
    """The same governed research profile the execute-accepted contract uses."""

    from fastapi.testclient import TestClient

    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "binding-contract-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)

    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "operator"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "agent-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE)
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    return TestClient(api_mod.app), exec_mod


def mint(exec_mod, *, principal: str, call: dict, tenant: str = "acme",
         semantic_override: dict | None = None):
    """Mint an ACCEPT token the way the assess ACCEPT branch does."""

    from remora.enforcement.token import PolicyDecisionToken
    from remora.execution.service import authorization_context

    _obs, semantic = exec_mod._observation_with_context(
        exec_mod.ToolCallRequest(**call), tenant
    )
    if semantic_override:
        semantic = {**semantic, **semantic_override}
    now = datetime.now(UTC)
    token = PolicyDecisionToken.issue(
        action="accept",
        # The observation's own hash, not a recomputed one: the payload binding
        # is what it is, and this test is about the authorization context.
        observation_hash=_obs.tool_call_hash or "",
        request_id="p-binding",
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=300)).isoformat(),
        audience=exec_mod.PEP_AUDIENCE,
        context=authorization_context(
            tenant=tenant, principal=principal, semantic=semantic
        ),
    )
    return token.to_dict()


class TestTokenBinding:
    """Unit level: the token itself, without the API."""

    def context(self, **overrides):
        from remora.enforcement.token import AuthorizationContext

        base = dict(
            tenant="acme",
            principal="agent-A",
            target_environment="prod",
            policy_bundle_hash="bundle-1",
            toolspec_hash="spec-1",
            intent_authority_hash="intent-1",
        )
        base.update(overrides)
        return AuthorizationContext(**base)

    def token(self, monkeypatch, context=None):
        from remora.enforcement.token import PolicyDecisionToken

        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "k" * 32)
        now = datetime.now(UTC)
        return PolicyDecisionToken.issue(
            action="accept",
            observation_hash="obs-hash",
            request_id="r-1",
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=300)).isoformat(),
            context=context if context is not None else self.context(),
        )

    def test_the_same_context_verifies(self, monkeypatch):
        token = self.token(monkeypatch)
        assert token.verify("obs-hash", context=self.context()).verified

    @pytest.mark.parametrize(
        "field,value",
        [
            ("principal", "agent-B"),
            ("policy_bundle_hash", "bundle-2"),
            ("toolspec_hash", "spec-2"),
            ("target_environment", "staging"),
            ("intent_authority_hash", "intent-2"),
            ("tenant", "other"),
        ],
    )
    def test_mutating_any_single_bound_field_refuses(self, monkeypatch, field, value):
        """One field at a time, which is the property test the review asked for."""

        token = self.token(monkeypatch)
        result = token.verify("obs-hash", context=self.context(**{field: value}))
        assert result.verified is False
        assert result.reason == "context_mismatch"

    def test_an_unbound_token_refuses_against_a_context(self, monkeypatch):
        """Unknown is not the same as matching."""

        from remora.enforcement.token import PolicyDecisionToken

        monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "k" * 32)
        now = datetime.now(UTC)
        legacy = PolicyDecisionToken.issue(
            action="accept",
            observation_hash="obs-hash",
            request_id="r-1",
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=300)).isoformat(),
        )
        assert legacy.verify("obs-hash").verified, "a token with no context still verifies alone"
        result = legacy.verify("obs-hash", context=self.context())
        assert result.verified is False
        assert result.reason == "context_unbound"

    def test_the_context_hash_cannot_be_stripped(self, monkeypatch):
        from dataclasses import replace

        token = self.token(monkeypatch)
        stripped = replace(token, context_hash="")
        assert stripped.verify("obs-hash").verified is False

    def test_the_context_hash_survives_serialisation(self, monkeypatch):
        from remora.enforcement.token import PolicyDecisionToken

        token = self.token(monkeypatch)
        assert PolicyDecisionToken.from_dict(token.to_dict()) == token

    def test_differences_names_the_field_that_moved(self):
        assert self.context().differences(self.context(principal="agent-B")) == ["principal"]


class TestRedemption:
    """API level: the two failures the review reproduced."""

    def test_another_principal_cannot_redeem_and_the_grant_survives(self, client_and_mod):
        client, exec_mod = client_and_mod
        call = {"tool_name": "read_telemetry", "arguments": {"asset": "P-1"}}
        token = mint(exec_mod, principal="agent-A", call=call)

        # The request authenticates as agent-1 (see the fixture), so this is the
        # A-to-B substitution: a different principal with the same capability.
        refused = client.post(
            "/v1/execution/execute-accepted",
            json={"execution_token": token, "tool_call": call},
        )
        assert refused.status_code == 409
        assert refused.json()["detail"] in {"context_mismatch", "context_unbound"}

        # The grant was not burned by the refusal: the principal it was issued
        # for can still use it.
        own = mint(exec_mod, principal="agent-1", call=call)
        accepted = client.post(
            "/v1/execution/execute-accepted",
            json={"execution_token": own, "tool_call": call},
        )
        assert accepted.status_code == 200

    def test_a_policy_bundle_that_moved_refuses(self, client_and_mod):
        client, exec_mod = client_and_mod
        call = {"tool_name": "read_telemetry", "arguments": {"asset": "P-1"}}
        token = mint(
            exec_mod,
            principal="agent-1",
            call=call,
            semantic_override={"policy_bundle_hash": "a-bundle-that-is-no-longer-current"},
        )
        result = client.post(
            "/v1/execution/execute-accepted",
            json={"execution_token": token, "tool_call": call},
        )
        assert result.status_code == 409
        assert result.json()["detail"] == "context_mismatch"

    def test_a_toolspec_that_moved_refuses(self, client_and_mod):
        client, exec_mod = client_and_mod
        call = {"tool_name": "read_telemetry", "arguments": {"asset": "P-1"}}
        token = mint(
            exec_mod,
            principal="agent-1",
            call=call,
            semantic_override={"tool_contract_bundle_hash": "a-spec-that-was-redeployed"},
        )
        result = client.post(
            "/v1/execution/execute-accepted",
            json={"execution_token": token, "tool_call": call},
        )
        assert result.status_code == 409
        assert result.json()["detail"] == "context_mismatch"

    def test_unchanged_context_executes_exactly_once(self, client_and_mod):
        client, exec_mod = client_and_mod
        call = {"tool_name": "read_telemetry", "arguments": {"asset": "P-1"}}
        token = mint(exec_mod, principal="agent-1", call=call)

        first = client.post(
            "/v1/execution/execute-accepted",
            json={"execution_token": token, "tool_call": call},
        )
        assert first.status_code == 200, first.text
        second = client.post(
            "/v1/execution/execute-accepted",
            json={"execution_token": token, "tool_call": call},
        )
        assert second.status_code == 409
