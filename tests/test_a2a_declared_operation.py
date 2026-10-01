# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Declared operation at the A2A hop: actual ⊆ declared ⊆ authorized.

Design property 3 of docs/design/task-bound-execution-authority-v1.md: a
declared operation outside the authorized scope refuses, and an absent
declaration never widens. Between the opaque ``requested_scope`` and the
exact ``tool_call_hash`` the envelope had nothing a receiving implementation
could check without knowing REMORA's canonical hash; the declaration is that
middle, and it can only narrow.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from remora.governance.a2a_envelope import (
    A2AGovernanceEnvelope,
    AgentIdentity,
    DeclaredOperation,
    DelegationLink,
)

KEY = b"declared-operation-key"
SCOPE = ("workorder:read", "workorder:close")


def _envelope(declared: DeclaredOperation | None = None,
              requested: tuple[str, ...] = SCOPE) -> A2AGovernanceEnvelope:
    now = datetime.now(UTC).isoformat()
    return A2AGovernanceEnvelope.issue(
        identity=AgentIdentity(agent_id="agent://planner", agent_version="1",
                               issuer_org="org", responsible_org="org"),
        delegation_chain=(DelegationLink(delegator="org", delegatee="agent://planner",
                                         scope=SCOPE, issued_at=now),),
        requested_scope=requested,
        policy_version="v1",
        audience="control-plane://remora",
        signing_key=KEY,
        declared_operation=declared,
    )


def _failures(env, actual=None) -> tuple[str, ...]:
    return env.verify(signing_key=KEY, strict=False, actual_operation=actual).failures


CLOSE_WO1 = DeclaredOperation(action="workorder:close", resources=("WO-1",))


class TestActualWithinDeclared:
    def test_the_declared_operation_verifies(self):
        assert _failures(_envelope(CLOSE_WO1), ("workorder:close", "WO-1")) == ()

    @pytest.mark.parametrize("actual", [
        ("workorder:close", "WO-2"),      # another resource
        ("workorder:read", "WO-1"),       # another action, still authorized
    ])
    def test_anything_outside_the_declaration_refuses(self, actual):
        assert "actual_operation_exceeds_declaration" in _failures(_envelope(CLOSE_WO1), actual)

    def test_a_declaration_with_no_resources_covers_none(self):
        env = _envelope(DeclaredOperation(action="workorder:close", resources=()))
        assert "actual_operation_exceeds_declaration" in _failures(
            env, ("workorder:close", "WO-1"))


class TestDeclaredWithinAuthorized:
    def test_a_declared_action_outside_the_requested_scope_refuses(self):
        env = _envelope(CLOSE_WO1, requested=("workorder:read",))
        assert "declared_operation_exceeds_authority" in _failures(env)

    def test_a_declared_action_outside_the_delegation_refuses(self):
        env = _envelope(DeclaredOperation(action="workorder:delete", resources=("WO-1",)))
        assert "declared_operation_exceeds_authority" in _failures(env)


class TestAbsentDeclarationNeverWidens:
    def test_an_authorized_action_verifies_without_a_declaration(self):
        assert _failures(_envelope(), ("workorder:read", "WO-1")) == ()

    def test_an_unauthorized_action_refuses_without_a_declaration(self):
        assert "actual_operation_exceeds_authority" in _failures(
            _envelope(), ("workorder:delete", "WO-1"))

    def test_an_action_delegated_but_not_requested_refuses(self):
        env = _envelope(requested=("workorder:read",))
        assert "actual_operation_exceeds_authority" in _failures(env, ("workorder:close", "WO-1"))


class TestSignedBytes:
    PRE_CHANGE_KEYS = {
        "envelope_id", "protocol", "identity", "delegation_chain",
        "requested_scope", "policy_version", "decision_ref", "evidence_refs",
        "issued_at", "expires_at", "audience", "nonce", "tool_call_hash",
    }

    def test_an_envelope_without_a_declaration_signs_the_pre_change_keys(self):
        assert set(json.loads(_envelope()._signable_payload())) == self.PRE_CHANGE_KEYS

    def test_a_declaration_is_signed_and_round_trips(self):
        env = _envelope(CLOSE_WO1)
        assert json.loads(env._signable_payload())["declared_operation"] == {
            "action": "workorder:close", "resources": ["WO-1"]}
        restored = A2AGovernanceEnvelope.from_json(env.to_json())
        assert restored.declared_operation == CLOSE_WO1
        assert _failures(restored, ("workorder:close", "WO-1")) == ()

    def test_widening_a_declaration_breaks_the_signature(self):
        data = json.loads(_envelope(CLOSE_WO1).to_json())
        data["declared_operation"]["resources"].append("WO-2")
        tampered = A2AGovernanceEnvelope.from_json(json.dumps(data))
        assert "signature_mismatch" in _failures(tampered, ("workorder:close", "WO-2"))

    def test_stripping_a_declaration_breaks_the_signature(self):
        data = json.loads(_envelope(CLOSE_WO1).to_json())
        data.pop("declared_operation")
        assert "signature_mismatch" in _failures(A2AGovernanceEnvelope.from_json(json.dumps(data)))

    @pytest.mark.parametrize("bad", [{"resources": ["WO-1"]}, {"action": "a", "resources": "WO-1"}, "x"])
    def test_a_malformed_declaration_is_rejected_at_parse(self, bad):
        data = {**json.loads(_envelope().to_json()), "declared_operation": bad}
        with pytest.raises(ValueError, match="malformed_envelope"):
            A2AGovernanceEnvelope.from_json(json.dumps(data))
