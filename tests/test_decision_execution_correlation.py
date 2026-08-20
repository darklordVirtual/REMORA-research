# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The lease and the dispatch result close the last leg of the join (#45).

FT-01 already threaded ``proposal_id`` from assess through the tenant chain to
the execution grant's ``request_id``. Two legs were still missing, and they
were the ones nearest the side effect: the lease was bound to the *call shape*
and not to the decision that authorized it, and ``DispatchResult`` carried no
identity at all. An executed side effect could therefore only be joined back to
its decision by re-deriving hashes out of band.

Both identifiers are now signed into the lease, so this is a binding rather
than a label: tampering with either invalidates the signature, and a caller may
require a match at verification time.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from remora.enforcement.lease import (
    ExecutionLease,
    GovernedToolDispatcher,
    ToolExecutionStateUnknown,
)

ISSUED_AT = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC).isoformat()
TENANT = "acme"
ACTOR = "agent-7"
BUNDLE = "bundle-hash-1"
ARGS = {"setpoint": 42}
PID = "prop-0001"
JTI = "jti-0001"


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "k" * 32)


def _lease(**overrides) -> ExecutionLease:
    kwargs = dict(
        decision="accept",
        tenant_id=TENANT,
        actor_identity=ACTOR,
        tool_name="adjust_setpoint",
        arguments=ARGS,
        target_environment="prod",
        policy_bundle_hash=BUNDLE,
        issued_at=ISSUED_AT,
        proposal_id=PID,
        grant_jti=JTI,
    )
    kwargs.update(overrides)
    return ExecutionLease.issue(**kwargs)


def _verify(lease: ExecutionLease, **overrides):
    kwargs = dict(
        tool_name="adjust_setpoint",
        arguments=ARGS,
        tenant_id=TENANT,
        target_environment="prod",
        now=ISSUED_AT,
        actor_identity=ACTOR,
    )
    kwargs.update(overrides)
    return lease.verify(**kwargs)


# ── the lease carries the decision identity, and carries it signed ───────────

def test_the_lease_carries_the_proposal_and_grant_identity() -> None:
    lease = _lease()
    assert lease.proposal_id == PID
    assert lease.grant_jti == JTI


def test_the_identity_is_covered_by_the_signature() -> None:
    """A label can be edited; a binding cannot. This is the difference."""
    lease = _lease()
    assert _verify(lease).verified

    forged = replace(lease, proposal_id="prop-other")
    assert not _verify(forged).verified

    forged_jti = replace(lease, grant_jti="jti-other")
    assert not _verify(forged_jti).verified


def test_a_mismatched_proposal_is_refused_when_the_caller_requires_one() -> None:
    lease = _lease()
    assert _verify(lease, expected_proposal_id=PID).verified
    result = _verify(lease, expected_proposal_id="prop-other")
    assert not result.verified
    assert result.reason == "proposal_mismatch"


def test_an_absent_proposal_cannot_satisfy_a_binding_check() -> None:
    """Fail closed, same shape as the policy-bundle check: an unset value must
    not silently disable the protection (the issue #16 mistake)."""
    lease = _lease(proposal_id="")
    result = _verify(lease, expected_proposal_id=PID)
    assert not result.verified
    assert result.reason == "proposal_binding_missing"


def test_a_lease_without_an_identity_still_verifies_when_none_is_required() -> None:
    """Library and legacy callers mint no proposal; the field is carried, never
    invented, so their leases keep working."""
    assert _verify(_lease(proposal_id="", grant_jti="")).verified


def test_round_trip_preserves_the_identity() -> None:
    lease = _lease()
    assert ExecutionLease.from_dict(lease.to_dict()) == lease


# ── the dispatcher reports what it acted under ───────────────────────────────

def _dispatcher(fn=lambda a: {"ok": True}) -> GovernedToolDispatcher:
    dispatcher = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE)
    dispatcher.register("adjust_setpoint", fn)
    return dispatcher


def _dispatch(dispatcher, lease, **overrides):
    kwargs = dict(
        tenant_id=TENANT, target_environment="prod",
        now=ISSUED_AT, actor_identity=ACTOR,
    )
    kwargs.update(overrides)
    return dispatcher.dispatch(lease, "adjust_setpoint", ARGS, **kwargs)


def test_an_executed_dispatch_reports_the_proposal_it_ran_under() -> None:
    result = _dispatch(_dispatcher(), _lease())
    assert result.executed
    assert result.proposal_id == PID


def test_a_refused_dispatch_still_reports_the_proposal() -> None:
    """A refusal is exactly the case an operator needs to join back."""
    dispatcher = _dispatcher()
    lease = _lease()
    result = dispatcher.dispatch(
        lease, "adjust_setpoint", {"setpoint": 99},
        tenant_id=TENANT, target_environment="prod",
        now=ISSUED_AT, actor_identity=ACTOR,
    )
    assert not result.executed
    assert result.refusal_reason == "tool_args_hash_mismatch"
    assert result.proposal_id == PID


def test_a_missing_lease_reports_no_identity_rather_than_a_made_up_one() -> None:
    """There is nothing to read it from, and inventing one would be worse."""
    result = _dispatch(_dispatcher(), None)
    assert not result.executed
    assert result.refusal_reason == "missing_lease"
    assert result.proposal_id == ""


# ── the events carry it too, including the one that matters most ─────────────

def _events(caplog) -> list[tuple[str, dict]]:
    out = []
    for record in caplog.records:
        fields = getattr(record, "remora", None)
        if fields is not None:
            out.append((record.getMessage().split(" ", 1)[0], fields))
    return out


def test_dispatch_events_carry_the_proposal(caplog) -> None:
    with caplog.at_level(logging.INFO):
        _dispatch(_dispatcher(), _lease())
    executed = [f for name, f in _events(caplog) if name == "dispatch.executed"]
    assert executed, [n for n, _ in _events(caplog)]
    assert executed[0]["proposal_id"] == PID
    assert executed[0]["grant_jti"] == JTI


def test_a_burned_nonce_is_logged_at_error_with_the_proposal(caplog) -> None:
    """The single most alert-worthy condition in the system used to raise a
    bare RuntimeError with no log line and no distinct type."""
    def explode(_args):
        raise ValueError("downstream refused")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ToolExecutionStateUnknown) as excinfo:
            _dispatch(_dispatcher(explode), _lease())

    assert excinfo.value.proposal_id == PID
    assert excinfo.value.tool_name == "adjust_setpoint"
    assert isinstance(excinfo.value, RuntimeError), (
        "existing handlers catch RuntimeError; the new type must not break them"
    )
    unknown = [f for name, f in _events(caplog) if name == "dispatch.state_unknown"]
    assert unknown and unknown[0]["proposal_id"] == PID
    assert unknown[0]["nonce_burned"] is True


# ── end to end ───────────────────────────────────────────────────────────────

@pytest.fixture()
def api(monkeypatch):
    """Same wiring as tests/test_execution_api.py: authenticated principal,
    reset module state, PDP signing key present."""
    from fastapi.testclient import TestClient

    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "exec-api-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role", lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE)
    exec_mod._reset_tool_dispatcher()
    return TestClient(api_mod.app)


def test_the_executed_effect_joins_back_to_the_decision(api) -> None:
    """One id from proposal to dispatch, with no hash re-derivation.

    The assess response, the tenant-chain records, the execution grant and now
    the lease and the dispatch result all carry the same value.
    """
    import servers.execution_api as exec_mod

    payload = {
        "tool_name": "update_work_order",
        "arguments": {"order": "WO-1", "action": "reschedule"},
        "target_environment": "prod",
        "risk_tier": "high",
        "action_type": "production_write",
        "phase": "ordered",
        "trust_score": 0.86,
        "evidence_action": "verify",
        "evidence_confidence": 0.8,
        "schema_valid": True,
        "rollback_available": True,
    }
    assessed = api.post("/v1/execution/assess", json=payload).json()
    pid = assessed["proposal_id"]
    item_id = assessed["review_item_id"]
    api.post("/v1/execution/approve",
             json={"item_id": item_id, "approval_ttl_seconds": 900})
    executed = api.post("/v1/execution/execute",
                        json={"item_id": item_id, "tool_call": payload}).json()

    assert executed["proposal_id"] == pid
    assert executed["execution_grant"]["request_id"] == pid
    tool_execution = executed.get("tool_execution") or {}
    assert tool_execution.get("proposal_id") == pid, tool_execution
    payloads = [e.payload for e in exec_mod._CHAIN.entries("acme")]
    assert payloads and all(p.get("proposal_id") == pid for p in payloads)
