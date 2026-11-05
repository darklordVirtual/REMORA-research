# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for ExecutionLease + GovernedToolDispatcher (REM-024 groundwork).

Every non-accept decision must be technically unexecutable: no lease can be
issued for it, and the dispatcher refuses every call without a valid lease.
"""
from __future__ import annotations

import dataclasses

import pytest

from remora.enforcement.lease import (
    DEFAULT_LEASE_TTL_SECONDS,
    ExecutionLease,
    GovernedToolDispatcher,
    LeaseRefused,
    NonceLedger,
)
from remora.policy.observation import canonical_tool_call_hash

ISSUED_AT = "2026-07-20T12:00:00+00:00"
BEFORE_EXPIRY = "2026-07-20T12:01:00+00:00"
AFTER_EXPIRY = "2026-07-20T13:30:00+00:00"

TOOL = "unifi_set_vlan"
ARGS = {"site": "hq", "vlan_id": 42, "ports": ["eth0", "eth1"]}
TENANT = "luftfiber"
ACTOR = "agent-7"
TARGET = "production"
BUNDLE = "sha256:policybundle01"


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "unit-test-lease-key")


def _issue(**overrides) -> ExecutionLease:
    params = dict(
        decision="accept",
        tenant_id=TENANT,
        actor_identity="agent-7",
        tool_name=TOOL,
        arguments=ARGS,
        target_environment=TARGET,
        policy_bundle_hash=BUNDLE,
        issued_at=ISSUED_AT,
    )
    params.update(overrides)
    return ExecutionLease.issue(**params)


def _dispatcher(**kwargs) -> GovernedToolDispatcher:
    calls: list[dict] = []

    def tool_fn(arguments: dict) -> str:
        calls.append(arguments)
        return "vlan-configured"

    d = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE, **kwargs)
    d.register(TOOL, tool_fn)
    d._test_calls = calls  # type: ignore[attr-defined]
    return d


# ── Issuance is fail-closed ────────────────────────────────────────────────


@pytest.mark.parametrize("decision", ["verify", "abstain", "escalate", "", "ACCEPT-ish"])
def test_issue_refuses_every_non_accept_decision(decision: str) -> None:
    with pytest.raises(LeaseRefused):
        _issue(decision=decision)


def test_issue_rejects_ttl_out_of_bounds() -> None:
    with pytest.raises(ValueError):
        _issue(expires_at=ISSUED_AT)  # ttl == 0
    with pytest.raises(ValueError):
        _issue(expires_at="2026-07-22T12:00:00+00:00")  # > max ttl


def test_issue_defaults_to_short_ttl_and_unique_nonce() -> None:
    a, b = _issue(), _issue()
    assert a.nonce and b.nonce and a.nonce != b.nonce
    assert a.expires_at == "2026-07-20T12:02:00+00:00"  # 120 s default
    assert DEFAULT_LEASE_TTL_SECONDS == 120
    assert a.is_signed


# ── Happy path ─────────────────────────────────────────────────────────────


def test_valid_lease_dispatches_exactly_once() -> None:
    d = _dispatcher()
    lease = _issue()
    out = d.dispatch(
        lease, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET, now=BEFORE_EXPIRY,
        actor_identity=ACTOR,
    )
    assert out.executed is True
    assert out.refusal_reason is None
    assert out.result == "vlan-configured"
    assert d._test_calls == [ARGS]

    replay = d.dispatch(
        lease, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET, now=BEFORE_EXPIRY,
        actor_identity=ACTOR,
    )
    assert replay.executed is False
    assert replay.refusal_reason == "nonce_already_consumed"
    assert d._test_calls == [ARGS]  # not executed twice


# ── Refusals ───────────────────────────────────────────────────────────────


def test_missing_lease_refused() -> None:
    d = _dispatcher()
    out = d.dispatch(None, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET)
    assert out.executed is False
    assert out.refusal_reason == "missing_lease"
    assert d._test_calls == []


def test_expired_lease_refused() -> None:
    d = _dispatcher()
    out = d.dispatch(
        _issue(), TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET, now=AFTER_EXPIRY
    )
    assert out.executed is False
    assert out.refusal_reason == "lease_expired"


def test_future_dated_lease_is_not_yet_valid() -> None:
    """A future-dated issued_at must not extend the usable lifetime.

    Regression (2026-07-20 adversarial verify): without a not-before check,
    issue(issued_at=now+10h) minted a lease dispatchable immediately AND for
    ten more hours — the TTL cap bounded only (expires_at - issued_at)."""
    d = _dispatcher()
    future = _issue(issued_at="2026-07-20T22:00:00+00:00")  # 10 h ahead of 'now'
    out = d.dispatch(
        future, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET, now=BEFORE_EXPIRY,
        actor_identity=ACTOR,
    )
    assert out.executed is False
    assert out.refusal_reason == "lease_not_yet_valid"
    # Inside its declared window the same lease works.
    ok = d.dispatch(
        future, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET,
        now="2026-07-20T22:01:00+00:00", actor_identity=ACTOR,
    )
    assert ok.executed is True


def test_mutated_arguments_refused() -> None:
    """An accepted lease must not authorize different arguments."""
    d = _dispatcher()
    mutated = {**ARGS, "ports": ["eth0", "eth1", "uplink"]}
    out = d.dispatch(
        _issue(), TOOL, mutated, tenant_id=TENANT, target_environment=TARGET,
        now=BEFORE_EXPIRY, actor_identity=ACTOR,
    )
    assert out.executed is False
    assert out.refusal_reason == "tool_args_hash_mismatch"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"tenant_id": "other-tenant"}, "tenant_mismatch"),
        ({"target_environment": "staging"}, "target_environment_mismatch"),
    ],
)
def test_context_mismatch_refused(kwargs: dict, reason: str) -> None:
    d = _dispatcher()
    call = dict(
        tenant_id=TENANT, target_environment=TARGET, now=BEFORE_EXPIRY,
        actor_identity=ACTOR,
    )
    call.update(kwargs)
    out = d.dispatch(_issue(), TOOL, ARGS, **call)
    assert out.executed is False
    assert out.refusal_reason == reason


def test_unknown_tool_refused() -> None:
    d = _dispatcher()
    lease = _issue(tool_name="never_registered", arguments={})
    out = d.dispatch(
        lease, "never_registered", {}, tenant_id=TENANT, target_environment=TARGET,
        now=BEFORE_EXPIRY,
    )
    assert out.executed is False
    assert out.refusal_reason == "unknown_tool"


def test_policy_bundle_mismatch_refused() -> None:
    d = _dispatcher()
    stale = _issue(policy_bundle_hash="sha256:stale-bundle")
    out = d.dispatch(
        stale, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET, now=BEFORE_EXPIRY,
        actor_identity=ACTOR,
    )
    assert out.executed is False
    assert out.refusal_reason == "policy_bundle_mismatch"


def _verify(lease: ExecutionLease, **overrides):
    params = dict(
        tool_name=TOOL, arguments=ARGS, tenant_id=TENANT,
        target_environment=TARGET, now=BEFORE_EXPIRY, actor_identity=ACTOR,
    )
    params.update(overrides)
    return lease.verify(**params)


def test_verify_refuses_empty_lease_bundle_hash_when_binding_requested() -> None:
    # Issue #16: a lease carrying no bundle identity must not satisfy a
    # bundle-binding check, whatever the expected value is.
    lease = _issue(policy_bundle_hash="")
    out = _verify(lease, expected_policy_bundle_hash=BUNDLE)
    assert out.verified is False
    assert out.reason == "policy_bundle_missing"


def test_verify_refuses_empty_expected_matching_empty_lease_hash() -> None:
    # Regression for issue #16: "" == "" previously PASSED the binding check,
    # so an integration passing an unset config value got no protection.
    lease = _issue(policy_bundle_hash="")
    out = _verify(lease, expected_policy_bundle_hash="")
    assert out.verified is False
    assert out.reason == "policy_bundle_missing"


def test_verify_bundle_binding_still_accepts_match_and_names_mismatch() -> None:
    lease = _issue()
    assert _verify(lease, expected_policy_bundle_hash=BUNDLE).verified is True
    out = _verify(lease, expected_policy_bundle_hash="sha256:other")
    assert out.verified is False
    assert out.reason == "policy_bundle_mismatch"


def test_tampered_fields_invalidate_signature() -> None:
    d = _dispatcher()
    lease = _issue()
    tampers = {
        "decision": "accept",  # baseline sanity: replaced below per-field
        "tenant_id": "other",
        "actor_identity": "evil-agent",
        "tool_name": "delete_everything",
        "tool_args_hash": canonical_tool_call_hash(
            name=TOOL, arguments={"x": 1}, tenant=TENANT, target=TARGET
        ),
        "target_environment": "staging",
        "policy_bundle_hash": "sha256:forged",
        "expires_at": "2026-07-20T23:59:00+00:00",
        "nonce": "forged-nonce",
    }
    for field, forged_value in tampers.items():
        if field == "decision":
            continue
        forged = dataclasses.replace(lease, **{field: forged_value})
        # Present the forged lease with call parameters matching its claims,
        # so only the signature check can catch it.
        out = d.dispatch(
            forged,
            forged.tool_name,
            ARGS if field != "tool_args_hash" else {"x": 1},
            tenant_id=forged.tenant_id,
            target_environment=forged.target_environment,
            now=BEFORE_EXPIRY,
        )
        assert out.executed is False, f"tampered {field} must not execute"
        assert out.refusal_reason in {
            "signature_invalid",
            "unknown_tool",
            "policy_bundle_mismatch",
        }, f"tampered {field}: {out.refusal_reason}"
        # The signature itself must never verify after tampering.
        assert not forged.verify(
            tool_name=forged.tool_name,
            arguments=ARGS if field != "tool_args_hash" else {"x": 1},
            tenant_id=forged.tenant_id,
            target_environment=forged.target_environment,
            now=BEFORE_EXPIRY,
        ).verified


def test_unsigned_lease_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REMORA_LEASE_SIGNING_KEY", raising=False)
    monkeypatch.delenv("REMORA_PDP_SIGNING_KEY", raising=False)
    unsigned = _issue()
    assert unsigned.is_signed is False

    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "unit-test-lease-key")
    d = _dispatcher()
    out = d.dispatch(
        unsigned, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET, now=BEFORE_EXPIRY,
        actor_identity=ACTOR,
    )
    assert out.executed is False
    assert out.refusal_reason == "lease_not_signed"


def test_pdp_key_fallback_signs_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REMORA_LEASE_SIGNING_KEY", raising=False)
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "pdp-fallback-key")
    lease = _issue()
    assert lease.is_signed is True
    res = lease.verify(
        tool_name=TOOL, arguments=ARGS, tenant_id=TENANT,
        target_environment=TARGET, now=BEFORE_EXPIRY, actor_identity=ACTOR,
    )
    assert res.verified


def test_unparseable_expiry_fails_closed() -> None:
    lease = dataclasses.replace(_issue(), expires_at="not-a-timestamp")
    res = lease.verify(
        tool_name=TOOL, arguments=ARGS, tenant_id=TENANT,
        target_environment=TARGET, now=BEFORE_EXPIRY, actor_identity=ACTOR,
    )
    assert res.verified is False
    # Tampered expiry breaks the signature before expiry parsing is reached.
    assert res.reason in {"signature_invalid", "expiry_unparseable"}


# ── Actor binding (external review 2026-07-24, F-02) ──────────────────────


def test_stolen_lease_refused_for_different_actor() -> None:
    """A lease issued to actor-A must not execute for any other caller.

    Regression: actor_identity was signed but never enforced at dispatch,
    so a stolen lease worked for any caller with matching tenant/tool/args."""
    d = _dispatcher()
    out = d.dispatch(
        _issue(), TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET,
        now=BEFORE_EXPIRY, actor_identity="attacker-9",
    )
    assert out.executed is False
    assert out.refusal_reason == "actor_identity_mismatch"


def test_actor_bound_lease_requires_an_actor_identity() -> None:
    """Presenting an actor-bound lease with no authenticated identity fails
    closed — dispatch without actor context must never execute it."""
    d = _dispatcher()
    out = d.dispatch(
        _issue(), TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET,
        now=BEFORE_EXPIRY,
    )
    assert out.executed is False
    assert out.refusal_reason == "actor_identity_required"


def test_actorless_lease_dispatches_without_actor_context() -> None:
    """A lease issued with an empty actor_identity carries no actor binding;
    the remaining binding set (tenant, tool, args, environment) still holds."""
    d = _dispatcher()
    lease = _issue(actor_identity="")
    out = d.dispatch(
        lease, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET,
        now=BEFORE_EXPIRY,
    )
    assert out.executed is True


# ── Serialization ──────────────────────────────────────────────────────────


def test_round_trip_and_unknown_field_rejection() -> None:
    lease = _issue()
    restored = ExecutionLease.from_dict(lease.to_dict())
    assert restored == lease
    with pytest.raises(ValueError):
        ExecutionLease.from_dict({**lease.to_dict(), "extra": 1})


def test_replay_after_tool_failure_names_the_failed_execution() -> None:
    """A nonce burned by a raising tool is not a plain replay: the refusal
    must say the previous attempt failed with unknown state, and the ledger
    must expose the recorded failure reason for post-mortem — recording it
    write-only helps nobody."""
    lease = _issue()
    dispatcher = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE)

    def exploding(arguments: dict) -> str:
        raise RuntimeError("plc timeout")

    dispatcher.register(TOOL, exploding)
    with pytest.raises(RuntimeError):
        dispatcher.dispatch(lease, TOOL, ARGS, tenant_id=TENANT,
                            target_environment=TARGET, now=ISSUED_AT,
                            actor_identity=ACTOR)

    assert dispatcher._ledger.failure(lease.nonce) == "plc timeout"

    replay = dispatcher.dispatch(lease, TOOL, ARGS, tenant_id=TENANT,
                                 target_environment=TARGET, now=ISSUED_AT,
                                 actor_identity=ACTOR)
    assert replay.executed is False
    assert replay.refusal_reason == "nonce_consumed_by_failed_execution"


def test_the_durable_path_also_names_the_failed_execution(tmp_path) -> None:
    """The same distinction on the path a deployment actually runs.

    ``fail_consume`` is recorded in the in-process ledger on both paths, but
    the durable branch never consulted ``failure()``, so the refusal that
    tells an operator "the previous attempt ran and its outcome is unknown"
    was reachable only for a deployment with no durable nonce store. That is
    backwards: the deployments with a durable store are the ones where the
    retry arrives at a different worker.
    """
    from remora.enforcement.nonce_store import DurableNonceStore

    lease = _issue()
    store = DurableNonceStore(db_path=str(tmp_path / "nonces.sqlite3"))
    dispatcher = GovernedToolDispatcher(
        expected_policy_bundle_hash=BUNDLE, nonce_store=store
    )

    def exploding(arguments: dict) -> str:
        raise RuntimeError("plc timeout")

    dispatcher.register(TOOL, exploding)
    with pytest.raises(RuntimeError):
        dispatcher.dispatch(lease, TOOL, ARGS, tenant_id=TENANT,
                            target_environment=TARGET, now=ISSUED_AT,
                            actor_identity=ACTOR)

    replay = dispatcher.dispatch(lease, TOOL, ARGS, tenant_id=TENANT,
                                 target_environment=TARGET, now=ISSUED_AT,
                                 actor_identity=ACTOR)
    assert replay.executed is False
    assert replay.refusal_reason == "nonce_consumed_by_failed_execution"


def test_the_durable_path_still_reports_a_plain_replay_as_one(tmp_path) -> None:
    """The narrower reason must not swallow the ordinary case.

    A nonce spent by a SUCCESSFUL execution is a plain replay, and saying
    the previous attempt failed would send an operator looking for damage
    that is not there.
    """
    from remora.enforcement.nonce_store import DurableNonceStore

    lease = _issue()
    store = DurableNonceStore(db_path=str(tmp_path / "nonces.sqlite3"))
    dispatcher = GovernedToolDispatcher(
        expected_policy_bundle_hash=BUNDLE, nonce_store=store
    )
    dispatcher.register(TOOL, lambda arguments: "ok")

    assert dispatcher.dispatch(
        lease, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET,
        now=ISSUED_AT, actor_identity=ACTOR).executed is True

    replay = dispatcher.dispatch(lease, TOOL, ARGS, tenant_id=TENANT,
                                 target_environment=TARGET, now=ISSUED_AT,
                                 actor_identity=ACTOR)
    assert replay.refusal_reason == "nonce_already_consumed"


def test_nonce_ledger_is_atomic_single_use() -> None:
    ledger = NonceLedger()
    assert ledger.consume("n-1") is True
    assert ledger.consume("n-1") is False
    assert ledger.consume("n-2") is True


# ── IFC-06: invocation arguments (resolved flow handles) ───────────────────


def test_invocation_arguments_reach_the_tool_while_the_lease_binds_the_wire_form() -> None:
    d = _dispatcher()
    resolved = dict(ARGS, site="hq-resolved")
    res = d.dispatch(_issue(), TOOL, ARGS, tenant_id=TENANT,
                     target_environment=TARGET, now=BEFORE_EXPIRY,
                     actor_identity=ACTOR, invocation_arguments=resolved)
    assert res.executed is True
    assert d._test_calls == [resolved]  # type: ignore[attr-defined]


def test_a_lease_for_the_resolved_form_does_not_cover_the_wire_form() -> None:
    d = _dispatcher()
    wire = dict(ARGS, site="⟦h:AAAAAAAAAAAAAAAA⟧")
    res = d.dispatch(_issue(), TOOL, wire, tenant_id=TENANT,
                     target_environment=TARGET, now=BEFORE_EXPIRY,
                     actor_identity=ACTOR, invocation_arguments=ARGS)
    assert res.executed is False
    assert d._test_calls == []  # type: ignore[attr-defined]


def test_the_runtime_checks_also_judge_the_invocation_arguments(monkeypatch) -> None:
    """A handle must not carry a value the wire form could not name."""
    d = _dispatcher()
    seen: list[object] = []

    def capability(lease, tool_name, tenant_id, target, capability_set, now,
                   arguments=None):
        seen.append(arguments)
        return "capability_argument_refused" if arguments.get("site") == "dc-2" else None

    monkeypatch.setattr(d, "_capability_refusal", capability)
    res = d.dispatch(_issue(), TOOL, ARGS, tenant_id=TENANT,
                     target_environment=TARGET, now=BEFORE_EXPIRY,
                     actor_identity=ACTOR, invocation_arguments=dict(ARGS, site="dc-2"))
    assert res.executed is False
    assert res.refusal_reason == "capability_argument_refused"
    assert d._test_calls == []  # type: ignore[attr-defined]
    assert seen == [ARGS, dict(ARGS, site="dc-2")]


# ── IFC-06: the resolved call is signed into the lease ──────────────────────
#
# SDD unified capability execution v1.1, P0 item 6. The lease binds the wire
# form the approver saw; ``resolved_tool_call_hash`` binds the call with every
# flow handle resolved, which is what the tool receives. The dispatcher
# compares the invocation form against it before anything is spent.


def _resolved_hash(arguments) -> str:
    from remora.policy.observation import canonical_tool_call_hash

    return canonical_tool_call_hash(name=TOOL, arguments=arguments, tenant=TENANT, target=TARGET)


def test_a_lease_signs_the_flow_decision_only_when_it_carries_one() -> None:
    plain = _issue()
    assert "flow_epoch" not in plain._signed_fields()
    assert "resolved_tool_call_hash" not in plain._signed_fields()
    bound = _issue(flow_epoch=4, flow_digest="d" * 64, resolved_tool_call_hash="r" * 64)
    signed = bound._signed_fields()
    assert (signed["flow_epoch"], signed["flow_digest"]) == (4, "d" * 64)
    assert signed["resolved_tool_call_hash"] == "r" * 64
    assert ExecutionLease.from_dict(bound.to_dict()) == bound
    with pytest.raises(ValueError):
        _issue(flow_epoch=4)
    with pytest.raises(ValueError):
        _issue(flow_digest="d" * 64)


def test_an_epoch_without_its_digest_is_a_malformed_lease() -> None:
    lease = _issue()
    half = ExecutionLease.from_dict({**lease.to_dict(), "flow_epoch": 2})
    result = half.verify(tool_name=TOOL, arguments=ARGS, tenant_id=TENANT,
                         target_environment=TARGET, now=BEFORE_EXPIRY, actor_identity=ACTOR)
    assert result.reason == "signature_invalid"   # the epoch is signed whenever it is set


def test_the_tool_receives_only_the_resolved_call_the_authority_signed() -> None:
    d = _dispatcher()
    resolved = dict(ARGS, site="hq-resolved")
    lease = _issue(flow_epoch=1, flow_digest="d" * 64,
                   resolved_tool_call_hash=_resolved_hash(resolved))
    res = d.dispatch(lease, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET,
                     now=BEFORE_EXPIRY, actor_identity=ACTOR, invocation_arguments=resolved)
    assert res.executed is True
    assert d._test_calls == [resolved]  # type: ignore[attr-defined]


def test_a_resolution_the_authority_did_not_sign_is_refused_before_the_nonce(caplog) -> None:
    """The handle store handed the executor another value than the one the
    authority judged: the tool does not run and the lease stays unspent."""
    import logging

    d = _dispatcher()
    lease = _issue(flow_epoch=1, flow_digest="d" * 64, proposal_id="p-resolved",
                   grant_jti="jti-resolved",
                   resolved_tool_call_hash=_resolved_hash(dict(ARGS, site="hq-resolved")))
    with caplog.at_level(logging.WARNING, logger="remora.governance"):
        res = d.dispatch(lease, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET,
                         now=BEFORE_EXPIRY, actor_identity=ACTOR,
                         invocation_arguments=dict(ARGS, site="hq-other"))
    assert (res.executed, res.refusal_reason) == (False, "resolved_call_mismatch")
    assert res.proposal_id == lease.proposal_id == "p-resolved"
    assert d._test_calls == []  # type: ignore[attr-defined]
    # The operational record names the refusal and the lifecycle join keys.
    [event] = [r for r in caplog.records if r.name == "remora.governance"
               and r.getMessage().startswith("dispatch.refused ")]
    assert event.levelno == logging.WARNING
    assert event.remora == {  # type: ignore[attr-defined]
        "reason": "resolved_call_mismatch", "tenant_id": TENANT, "tool_name": TOOL,
        "proposal_id": lease.proposal_id, "grant_jti": lease.grant_jti}
    again = d.dispatch(lease, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET,
                       now=BEFORE_EXPIRY, actor_identity=ACTOR,
                       invocation_arguments=dict(ARGS, site="hq-resolved"))
    assert again.executed is True  # the nonce was not spent by the refusal


def test_a_signed_resolution_also_binds_a_call_with_no_handles() -> None:
    """Without handles the resolved call is the wire call; a lease signed over
    one call does not run another, even when the wire hash would be rechecked."""
    d = _dispatcher()
    lease = _issue(flow_epoch=1, flow_digest="d" * 64,
                   resolved_tool_call_hash=_resolved_hash(dict(ARGS, site="elsewhere")))
    res = d.dispatch(lease, TOOL, ARGS, tenant_id=TENANT, target_environment=TARGET,
                     now=BEFORE_EXPIRY, actor_identity=ACTOR)
    assert (res.executed, res.refusal_reason) == (False, "resolved_call_mismatch")


def test_a_resolved_call_signed_for_no_target_runs_with_no_target() -> None:
    """An absent target is the empty string in the resolved hash too, so a
    lease signed for one dispatches with the other."""
    from remora.policy.observation import canonical_tool_call_hash

    d = _dispatcher()
    resolved = dict(ARGS, site="hq-resolved")
    lease = _issue(flow_epoch=1, flow_digest="d" * 64, target_environment="",
                   resolved_tool_call_hash=canonical_tool_call_hash(
                       name=TOOL, arguments=resolved, tenant=TENANT, target=""))
    res = d.dispatch(lease, TOOL, ARGS, tenant_id=TENANT, target_environment=None,
                     now=BEFORE_EXPIRY, actor_identity=ACTOR, invocation_arguments=resolved)
    assert res.executed is True, res.refusal_reason
    assert d._test_calls == [resolved]  # type: ignore[attr-defined]
