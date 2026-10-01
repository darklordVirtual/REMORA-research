# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Task identity in the lease and the A2A envelope (quality program Q7.2).

``AuthorizationContext`` has bound the task since the first half of
docs/design/task-bound-execution-authority-v1.md. The lease and the A2A
envelope did not, so the executor and the receiving agent had no way to tell
which task an authorization was granted under. These tests carry the design's
first two properties into both structures:

1. An authorization granted under task A refuses the identical call under
   task B, and says so as ``task_mismatch`` rather than a generic failure.
2. A structure with no task identity signs byte-identical bytes to one issued
   before the fields existed. ``TestUnboundBytesAreUnchanged`` is the
   regression guard: if it fails, every issued lease or envelope stops
   verifying.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher
from remora.enforcement.token import AuthorizationContext
from remora.execution.dispatch import dispatch_under_lease
from remora.governance.a2a_envelope import (
    A2AGovernanceEnvelope,
    AgentIdentity,
    DelegationLink,
)
from remora.governance.task_identity import (
    TaskIdentity,
    TaskIdentityMismatch,
    agreeing_task,
)

TASK_A = TaskIdentity(context_id="ctx-1", task_id="task-a")
TASK_B = TaskIdentity(context_id="ctx-1", task_id="task-b")
OTHER_CONTEXT = TaskIdentity(context_id="ctx-2", task_id="task-a")
BUNDLE = "bundle-1"
CALL: dict[str, Any] = {
    "tool_name": "wo_close",
    "arguments": {"id": "WO-1"},
    "tenant_id": "acme",
    "target_environment": "staging",
}
KEY = b"q7-2-a2a-key"
AUDIENCE = "control-plane://remora"


@pytest.fixture(autouse=True)
def _hmac_key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "q7-2-lease-key")
    for name in (
        "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
        "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC",
    ):
        monkeypatch.delenv(name, raising=False)


def _now() -> datetime:
    return datetime.now(UTC)


def _lease(task: TaskIdentity | None = None, **over: Any) -> ExecutionLease:
    kwargs: dict[str, Any] = {
        "decision": "accept",
        "actor_identity": "agent-1",
        "policy_bundle_hash": BUNDLE,
        "issued_at": _now().isoformat(),
        "task_identity": task,
        **CALL,
    }
    kwargs.update(over)
    return ExecutionLease.issue(**kwargs)


def _verify(lease: ExecutionLease, task: TaskIdentity | None = None) -> str:
    return lease.verify(actor_identity="agent-1", task_identity=task, **CALL).reason


def _dispatcher(**kwargs: Any) -> tuple[GovernedToolDispatcher, list[Any]]:
    calls: list[Any] = []
    dispatcher = GovernedToolDispatcher(BUNDLE, **kwargs)
    dispatcher.register("wo_close", lambda args: calls.append(args) or "closed")
    return dispatcher, calls


def _dispatch(dispatcher: GovernedToolDispatcher, lease: ExecutionLease,
              task: TaskIdentity | None = None):
    return dispatcher.dispatch(
        lease, CALL["tool_name"], CALL["arguments"], tenant_id=CALL["tenant_id"],
        target_environment=CALL["target_environment"], actor_identity="agent-1",
        task_identity=task,
    )


def _envelope(task: TaskIdentity | None = None) -> A2AGovernanceEnvelope:
    now = _now().isoformat()
    return A2AGovernanceEnvelope.issue(
        identity=AgentIdentity(
            agent_id="agent://planner", agent_version="1",
            issuer_org="org", responsible_org="org",
        ),
        delegation_chain=(
            DelegationLink(delegator="org", delegatee="agent://planner",
                           scope=("workorder:read",), issued_at=now),
        ),
        requested_scope=("workorder:read",),
        policy_version="v1",
        audience=AUDIENCE,
        signing_key=KEY,
        task_identity=task,
    )


def _envelope_failures(env: A2AGovernanceEnvelope,
                       expected: TaskIdentity | None = None) -> tuple[str, ...]:
    return env.verify(signing_key=KEY, strict=False,
                      expected_task_identity=expected).failures


class TestUnboundBytesAreUnchanged:
    """Property 2. Nothing else in this module matters if these fail."""

    #: The lease's signed keys before Q7.2, written out rather than derived so
    #: that any change to an unbound lease's preimage fails here.
    PRE_Q72_LEASE_KEYS = {
        "decision", "tenant_id", "actor_identity", "tool_name", "tool_args_hash",
        "target_environment", "policy_bundle_hash", "nonce", "issued_at",
        "expires_at", "tool_contract_bundle_hash", "intent_authority_hash",
        "toolspec_hash", "toolspec_version", "proposal_id", "grant_jti",
        "runtime_identity_hash", "sig_alg", "kid",
    }
    #: The envelope's signed keys before Q7.2.
    PRE_Q72_ENVELOPE_KEYS = {
        "envelope_id", "protocol", "identity", "delegation_chain",
        "requested_scope", "policy_version", "decision_ref", "evidence_refs",
        "issued_at", "expires_at", "audience", "nonce", "tool_call_hash",
    }

    def test_an_unbound_lease_signs_the_pre_change_keys(self):
        assert set(_lease()._signed_fields()) == self.PRE_Q72_LEASE_KEYS
        assert "context_id" not in _lease().to_dict()

    def test_an_unbound_lease_dict_from_before_the_change_still_verifies(self):
        legacy = _lease().to_dict()
        assert ExecutionLease.from_dict(legacy).verify(
            actor_identity="agent-1", **CALL).verified

    def test_an_unbound_envelope_signs_the_pre_change_keys(self):
        payload = json.loads(_envelope()._signable_payload())
        assert set(payload) == self.PRE_Q72_ENVELOPE_KEYS
        assert "task_id" not in json.loads(_envelope().to_json())

    def test_an_envelope_serialised_before_the_change_still_verifies(self):
        raw = _envelope().to_json()
        assert "context_id" not in raw
        assert _envelope_failures(A2AGovernanceEnvelope.from_json(raw)) == ()

    def test_bound_structures_do_sign_the_task(self):
        assert _lease(TASK_A)._signed_fields()["task_id"] == "task-a"
        assert json.loads(_envelope(TASK_A)._signable_payload())["context_id"] == "ctx-1"


class TestTheLeaseCarriesTheTask:
    """Property 1 at the lease."""

    def test_the_granted_task_verifies(self):
        assert _verify(_lease(TASK_A), TASK_A) == "ok"

    @pytest.mark.parametrize("presented", [TASK_B, OTHER_CONTEXT])
    def test_another_task_is_a_task_mismatch(self, presented):
        assert _verify(_lease(TASK_A), presented) == "task_mismatch"

    def test_an_unbound_lease_checked_against_a_task_is_task_unbound(self):
        """Distinct from a mismatch: never bound is a configuration gap."""
        assert _verify(_lease(), TASK_A) == "task_unbound"

    def test_no_presented_task_leaves_the_task_unchecked(self):
        """The toolspec convention: the check runs when the caller supplies it."""
        assert _verify(_lease(TASK_A)) == "ok"

    @pytest.mark.parametrize("field", ["context_id", "task_id"])
    def test_stripping_the_task_breaks_the_signature(self, field):
        data = _lease(TASK_A).to_dict()
        data.pop(field)
        assert _verify(ExecutionLease.from_dict(data), TASK_A) == "signature_invalid"

    def test_rewriting_the_task_breaks_the_signature(self):
        data = {**_lease(TASK_A).to_dict(), "task_id": "task-b"}
        assert _verify(ExecutionLease.from_dict(data), TASK_B) == "signature_invalid"

    def test_a_half_bound_lease_is_malformed_even_when_correctly_signed(self):
        from remora.enforcement import lease_signing as _signing

        data = {**_lease().to_dict(), "task_id": "task-a"}
        half = ExecutionLease.from_dict(data)
        signature = _signing.sign_payload(
            ExecutionLease._canonical_payload(half._signed_fields()), alg=half.sig_alg)
        half = ExecutionLease.from_dict({**data, "signature": signature})
        assert _verify(half) == "task_identity_malformed"


class TestTheDispatcherChecksTheTask:
    def test_a_mismatch_refuses_without_running_the_tool(self):
        dispatcher, calls = _dispatcher()
        result = _dispatch(dispatcher, _lease(TASK_A), TASK_B)
        assert (result.executed, result.refusal_reason) == (False, "task_mismatch")
        assert calls == []

    def test_a_mismatch_does_not_burn_the_nonce(self):
        dispatcher, calls = _dispatcher()
        lease = _lease(TASK_A)
        assert not _dispatch(dispatcher, lease, TASK_B).executed
        assert _dispatch(dispatcher, lease, TASK_A).executed
        assert calls == [CALL["arguments"]]

    def test_required_task_refuses_a_call_that_presents_none(self):
        dispatcher, calls = _dispatcher(require_task_identity=True)
        result = _dispatch(dispatcher, _lease(TASK_A))
        assert result.refusal_reason == "task_identity_required"
        assert calls == []

    def test_required_task_refuses_an_unbound_lease(self):
        dispatcher, _ = _dispatcher(require_task_identity=True)
        assert _dispatch(dispatcher, _lease(), TASK_A).refusal_reason == "task_unbound"

    def test_default_dispatch_without_a_task_is_unchanged(self):
        dispatcher, calls = _dispatcher()
        assert _dispatch(dispatcher, _lease()).executed
        assert calls == [CALL["arguments"]]

    def test_a_bound_lease_run_unchecked_is_recorded(self, monkeypatch):
        import remora.enforcement.lease as lease_module

        events: list[str] = []
        real = lease_module.governance_event
        monkeypatch.setattr(lease_module, "governance_event",
                            lambda name, **kw: events.append(name) or real(name, **kw))
        dispatcher, _ = _dispatcher()
        assert _dispatch(dispatcher, _lease(TASK_A)).executed
        assert "dispatch.task_unchecked" in events


class TestDispatchUnderLeaseCarriesTheTask:
    """The library entry point the execution API uses."""

    TOOL_CALL = SimpleNamespace(tool_name=CALL["tool_name"], arguments=CALL["arguments"],
                                target_environment=CALL["target_environment"])
    SEMANTIC = {"tool_contract_bundle_hash": "", "intent_authority_hash": ""}

    def _run(self, dispatcher, **kwargs):
        return dispatch_under_lease(
            tenant=CALL["tenant_id"], principal="agent-1", tool_call=self.TOOL_CALL,
            semantic=self.SEMANTIC, now=_now(), dispatcher=dispatcher,
            policy_bundle_hash=BUNDLE, **kwargs,
        )

    def test_a_locally_minted_lease_is_bound_and_checked(self):
        dispatcher, calls = _dispatcher(require_task_identity=True)
        assert self._run(dispatcher, task_identity=TASK_A)["executed"] is True
        assert calls == [CALL["arguments"]]

    def test_a_presented_lease_from_another_task_refuses(self):
        dispatcher, calls = _dispatcher()
        result = self._run(dispatcher, task_identity=TASK_B,
                           presented_lease=_lease(TASK_A))
        assert result["refusal_reason"] == "task_mismatch"
        assert calls == []


class TestTheEnvelopeCarriesTheTask:
    def test_the_granted_task_verifies(self):
        assert _envelope_failures(_envelope(TASK_A), TASK_A) == ()

    def test_another_task_is_a_task_mismatch(self):
        assert "task_mismatch" in _envelope_failures(_envelope(TASK_A), TASK_B)

    def test_an_unbound_envelope_checked_against_a_task_is_task_unbound(self):
        assert "task_unbound" in _envelope_failures(_envelope(), TASK_A)

    def test_a_bound_envelope_round_trips_through_json(self):
        restored = A2AGovernanceEnvelope.from_json(_envelope(TASK_A).to_json())
        assert restored.task_identity() == TASK_A
        assert _envelope_failures(restored, TASK_A) == ()

    def test_adding_a_task_to_an_unbound_envelope_breaks_its_signature(self):
        data = json.loads(_envelope().to_json())
        data.update(context_id="ctx-1", task_id="task-a")
        tampered = A2AGovernanceEnvelope.from_json(json.dumps(data))
        assert "signature_mismatch" in _envelope_failures(tampered, TASK_A)

    def test_a_half_bound_envelope_is_malformed(self):
        data = {**json.loads(_envelope().to_json()), "task_id": "task-a"}
        failures = _envelope_failures(A2AGovernanceEnvelope.from_json(json.dumps(data)))
        assert "malformed_task_identity" in failures

    def test_a_non_string_task_is_rejected_at_parse(self):
        data = {**json.loads(_envelope().to_json()), "task_id": 7}
        with pytest.raises(ValueError, match="malformed_envelope"):
            A2AGovernanceEnvelope.from_json(json.dumps(data))


class TestTheThreeStructuresAgree:
    """The token context, the lease and the envelope name one task or refuse."""

    def _context(self, task: TaskIdentity) -> AuthorizationContext:
        return AuthorizationContext(tenant="acme", context_id=task.context_id,
                                    task_id=task.task_id)

    def test_agreement_returns_the_task(self):
        found = agreeing_task(self._context(TASK_A).task_identity(),
                              _lease(TASK_A).task_identity(),
                              _envelope(TASK_A).task_identity())
        assert found == TASK_A

    def test_one_disagreeing_structure_raises_and_names_the_half(self):
        with pytest.raises(TaskIdentityMismatch, match="task_id"):
            agreeing_task(self._context(TASK_A).task_identity(),
                          _lease(TASK_A).task_identity(),
                          _envelope(TASK_B).task_identity())

    def test_unbound_structures_are_skipped(self):
        assert agreeing_task(None, _lease(TASK_A).task_identity(), None) == TASK_A
        assert agreeing_task(None, None) is None
