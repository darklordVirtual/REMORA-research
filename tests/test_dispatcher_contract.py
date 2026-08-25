# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The full DispatchResult contract, per refusal branch of dispatch().

Round three of the mutation triage (docs/assurance/mutation_testing_v1.md,
issue #280): ``GovernedToolDispatcher.dispatch`` carried the largest
survivor cluster (157 on covered lines), for the same reason the gate did —
suites assert ``executed`` and stop, so mutants rewriting a refusal reason,
dropping ``proposal_id`` from a result or flipping ``dispatch_began``
survive. All three fields are load-bearing: the reason is routed to metric
families, the proposal id is the lifecycle join key (issue #45), and
``dispatch_began`` is the one field that keeps "never started" distinct
from "started and unknown" at settlement.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from remora.enforcement.lease import (GovernedToolDispatcher,
                                      ToolExecutionStateUnknown)
from remora.execution.dispatch import issue_execution_lease

NOW = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
BUNDLE = "bundle-contract-1"
SEMANTIC = {"tool_contract_bundle_hash": "tc-1", "intent_authority_hash": "ia-1"}


def _call(tool: str = "wo_close", args: dict | None = None,
          target: str = "staging"):
    return SimpleNamespace(tool_name=tool,
                           arguments=args if args is not None else {"id": "WO-1"},
                           target_environment=target)


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "dispatch-contract-key")


def _lease(call=None, tenant: str = "acme", principal: str = "agent-1"):
    return issue_execution_lease(
        tenant=tenant, principal=principal, tool_call=call or _call(),
        semantic=SEMANTIC, now=NOW, policy_bundle_hash=BUNDLE,
        proposal_id="prop-dc-1", grant_jti="jti-dc-1",
    )


def _dispatcher(tool: str = "wo_close", fn=None) -> GovernedToolDispatcher:
    d = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE)
    d.register(tool, fn or (lambda args: {"ok": True}))
    return d


def _shape(r) -> tuple:
    return (r.executed, r.refusal_reason, r.dispatch_began, r.proposal_id)


# ── pre-lease refusals: no identity exists to report ───────────────────────


def test_missing_lease_refuses_with_no_identity() -> None:
    r = _dispatcher().dispatch(None, "wo_close", {"id": "WO-1"},
                               tenant_id="acme", now=NOW.isoformat())
    assert _shape(r) == (False, "missing_lease", False, "")


def test_unknown_tool_refuses_but_reports_the_lease_identity() -> None:
    r = _dispatcher("other_tool").dispatch(
        _lease(), "wo_close", {"id": "WO-1"},
        tenant_id="acme", target_environment="staging",
        actor_identity="agent-1", now=NOW.isoformat())
    assert _shape(r) == (False, "unknown_tool", False, "prop-dc-1")


def test_a_raising_spec_resolver_refuses_rather_than_falling_through() -> None:
    """'I could not check' must never become 'there was nothing to check'."""
    d = _dispatcher()

    def broken(_tool):
        raise RuntimeError("bundle store down")

    d.bind_toolspec_identity(broken)
    r = d.dispatch(_lease(), "wo_close", {"id": "WO-1"},
                   tenant_id="acme", target_environment="staging",
                   actor_identity="agent-1", now=NOW.isoformat())
    assert _shape(r) == (False, "toolspec_unresolvable", False, "prop-dc-1")


# ── binding refusals: every axis of the exact-call lease ───────────────────


@pytest.mark.parametrize("mutation, expected_reason", [
    (dict(args={"id": "WO-2"}), "tool_args_hash_mismatch"),
    (dict(tenant="globex"), "tenant_mismatch"),
    (dict(target="prod"), "target_environment_mismatch"),
], ids=["arguments", "tenant", "target-environment"])
def test_each_binding_axis_refuses_with_its_named_reason(
    mutation, expected_reason
) -> None:
    """The lease binds one exact call; a call differing on any axis is a
    different call, and the reason NAMES the axis -- an operator routing on
    reasons must be able to tell tampered arguments from a tenant leak."""
    lease = _lease()
    call_args = mutation.get("args", {"id": "WO-1"})
    r = _dispatcher().dispatch(
        lease, "wo_close", call_args,
        tenant_id=mutation.get("tenant", "acme"),
        target_environment=mutation.get("target", "staging"),
        actor_identity="agent-1", now=NOW.isoformat())
    assert _shape(r) == (False, expected_reason, False, "prop-dc-1")


def test_a_lease_for_another_tool_is_a_tool_name_mismatch() -> None:
    lease = _lease(_call(tool="wo_open"))
    d = _dispatcher("wo_close")
    r = d.dispatch(lease, "wo_close", {"id": "WO-1"},
                   tenant_id="acme", target_environment="staging",
                   actor_identity="agent-1", now=NOW.isoformat())
    assert _shape(r) == (False, "tool_name_mismatch", False, "prop-dc-1")


def test_a_foreign_policy_bundle_refuses() -> None:
    d = GovernedToolDispatcher(expected_policy_bundle_hash="other-bundle")
    d.register("wo_close", lambda args: "ok")
    r = d.dispatch(_lease(), "wo_close", {"id": "WO-1"},
                   tenant_id="acme", target_environment="staging",
                   actor_identity="agent-1", now=NOW.isoformat())
    assert _shape(r) == (False, "policy_bundle_mismatch", False, "prop-dc-1")


def test_an_expired_lease_refuses_by_name() -> None:
    r = _dispatcher().dispatch(
        _lease(), "wo_close", {"id": "WO-1"},
        tenant_id="acme", target_environment="staging",
        now=datetime(2026, 8, 25, 14, 0, 0, tzinfo=UTC).isoformat())
    assert _shape(r) == (False, "lease_expired", False, "prop-dc-1")


def test_a_named_actor_lease_requires_the_authenticated_identity() -> None:
    """The actor check runs FIRST among the binding axes: authority issued
    to a named actor answers nothing until the transport says who calls."""
    r = _dispatcher().dispatch(
        _lease(), "wo_close", {"id": "WO-1"},
        tenant_id="acme", target_environment="staging", now=NOW.isoformat())
    assert _shape(r) == (False, "actor_identity_required", False, "prop-dc-1")


def test_a_different_authenticated_actor_is_refused_by_name() -> None:
    r = _dispatcher().dispatch(
        _lease(), "wo_close", {"id": "WO-1"},
        tenant_id="acme", target_environment="staging",
        actor_identity="agent-2", now=NOW.isoformat())
    assert _shape(r) == (False, "actor_identity_mismatch", False, "prop-dc-1")


# ── success and the two nonce postures ─────────────────────────────────────


def test_the_success_shape_carries_result_began_and_identity() -> None:
    r = _dispatcher().dispatch(
        _lease(), "wo_close", {"id": "WO-1"},
        tenant_id="acme", target_environment="staging",
        actor_identity="agent-1", now=NOW.isoformat())
    assert r.executed is True
    assert r.refusal_reason is None
    assert r.dispatch_began is True
    assert r.proposal_id == "prop-dc-1"
    assert r.result == {"ok": True}


def test_a_replayed_lease_refuses_as_plain_consumption() -> None:
    d = _dispatcher()
    lease = _lease()
    assert d.dispatch(lease, "wo_close", {"id": "WO-1"}, tenant_id="acme",
                      target_environment="staging", actor_identity="agent-1",
                      now=NOW.isoformat()).executed is True
    replay = d.dispatch(lease, "wo_close", {"id": "WO-1"}, tenant_id="acme",
                        target_environment="staging", actor_identity="agent-1",
                        now=NOW.isoformat())
    assert _shape(replay) == (
        False, "nonce_already_consumed", False, "prop-dc-1")


def test_a_raising_tool_burns_the_nonce_and_names_the_unknown_state() -> None:
    """The most alert-worthy path: the tool raised AFTER the nonce was
    consumed. The exception carries the lifecycle identity and the
    machine-readable taxonomy code, and a retry with the same lease learns
    the previous attempt FAILED -- not merely that the nonce was spent."""
    d = _dispatcher(fn=lambda args: (_ for _ in ()).throw(OSError("db down")))
    lease = _lease()
    with pytest.raises(ToolExecutionStateUnknown) as caught:
        d.dispatch(lease, "wo_close", {"id": "WO-1"}, tenant_id="acme",
                   target_environment="staging", actor_identity="agent-1",
                   now=NOW.isoformat())
    assert caught.value.proposal_id == "prop-dc-1"
    assert caught.value.tenant_id == "acme"
    assert caught.value.tool_name == "wo_close"
    assert caught.value.machine_readable()["code"] == "tool_execution_state_unknown"

    retry = d.dispatch(lease, "wo_close", {"id": "WO-1"}, tenant_id="acme",
                       target_environment="staging", actor_identity="agent-1",
                       now=NOW.isoformat())
    assert _shape(retry) == (
        False, "nonce_consumed_by_failed_execution", False, "prop-dc-1")
