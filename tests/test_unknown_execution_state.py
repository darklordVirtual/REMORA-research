# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A dispatch that began and failed is UNKNOWN, not FAILED (RMR-003).

``schemas/execution_lifecycle_v1.yaml`` already drew the line:

    {from: DISPATCHING, to: FAILED,  on: tool_raised_pre_effect}
    {from: DISPATCHING, to: UNKNOWN, on: crash_or_timeout_after_possible_effect}

The code did not honour it. Settlement matched ``refusal_reason ==
"tool_failed_nonce_burned"`` and wrote a durable FAILED -- a reason whose own
docstring says *"the tool raised after its nonce was consumed: state at the
tool is unknown"*. The record asserted that no effect occurred on evidence that
only showed the call raised.

The invariant under test:

    REFUSED   REMORA observed that dispatch never began.
    FAILED    Trusted adapter evidence proves failure before the effect boundary.
    UNKNOWN   Dispatch began and absence of effect is not proven. Durable, and
              may later be superseded.

A dispatcher exception, a timeout, a lost response, or
``tool_failed_nonce_burned`` alone earns only UNKNOWN.

This follows from the equal-burden rule rather than being invented for it: a
durable FAILED is a negative claim asserting no effect occurred, and it was
being written on less evidence than SUCCEEDED requires.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.execution.outcome import (  # noqa: E402
    DispatchOutcome,
    PreEffectProof,
    classify_outcome,
)


def _result(**over):
    base = {"executed": False, "dispatch_began": False, "state_unknown": False}
    base.update(over)
    return base


# ── the three outcomes ──────────────────────────────────────────────────────

def test_a_confirmed_execution_succeeds():
    assert classify_outcome(_result(executed=True, dispatch_began=True)) is (
        DispatchOutcome.SUCCEEDED)


def test_a_dispatch_that_never_began_is_refused():
    """REMORA declined the call itself, so it observed the non-event.

    This is the one negative claim REMORA can make first-hand.
    """
    for reason in ("pep_denied", "unknown_tool", "nonce_already_consumed",
                   "policy_bundle_mismatch", "tool_args_hash_mismatch",
                   "lease_unavailable: no key"):
        outcome = classify_outcome(
            _result(refusal_reason=reason, dispatch_began=False))
        assert outcome is DispatchOutcome.REFUSED, reason
        assert outcome.asserts_no_effect


def test_possible_effect_then_exception_is_unknown():
    """The headline case. Previously FAILED.

    The call reached the tool; the exception says nothing about whether it
    committed first.
    """
    outcome = classify_outcome(_result(
        dispatch_began=True, state_unknown=True,
        refusal_reason="tool_failed_nonce_burned"))
    assert outcome is DispatchOutcome.UNKNOWN
    assert not outcome.asserts_no_effect
    assert outcome.may_be_superseded


def test_a_lost_response_is_unknown():
    """Sent, possibly executed, answer lost. Durably unknown."""
    outcome = classify_outcome(_result(
        state_unknown=True,
        refusal_reason="execution_domain_unreachable"))
    assert outcome is DispatchOutcome.UNKNOWN


def test_a_timeout_is_unknown_even_without_dispatch_began():
    """state_unknown alone is enough: not knowing whether it began is not
    the same as knowing it did not."""
    outcome = classify_outcome(_result(dispatch_began=False,
                                       state_unknown=True))
    assert outcome is DispatchOutcome.UNKNOWN


# ── FAILED needs proof, and there is none to be had yet ────────────────────

def test_failed_requires_adapter_evidence():
    began = _result(dispatch_began=True, state_unknown=True,
                    refusal_reason="tool_failed_nonce_burned")
    assert classify_outcome(began) is DispatchOutcome.UNKNOWN

    proven = classify_outcome(began, pre_effect_proof=PreEffectProof(
        source="sap-adapter", detail="rejected at transport, request not sent"))
    assert proven is DispatchOutcome.FAILED
    assert proven.asserts_no_effect


def test_a_caller_supplied_pre_effect_flag_is_not_proof():
    """The field a caller can set must not decide a negative claim.

    Accepting one would put the unproven assertion back, wearing a structured
    field instead of a string.
    """
    for forged in ({"pre_effect": True}, {"failed": True},
                   {"pre_effect_proof": True},
                   {"pre_effect_proof": {"source": "x", "detail": "y"}}):
        outcome = classify_outcome(_result(
            dispatch_began=True, state_unknown=True, **forged))
        assert outcome is DispatchOutcome.UNKNOWN, forged


def test_an_unattributed_proof_cannot_be_constructed():
    """A proof that does not say who observed what is an assertion."""
    for source, detail in (("", "x"), ("x", ""), ("", "")):
        with pytest.raises(ValueError):
            PreEffectProof(source=source, detail=detail)


def test_no_synchronous_path_produces_failed_today():
    """FAILED is unreachable from dispatch, deliberately.

    No adapter in this repository produces pre-effect evidence, so the honest
    terminal is UNKNOWN. If this test starts failing, an adapter has gained
    that capability and the claim it supports must be written down with it.
    """
    import inspect

    from remora.execution import dispatch, service

    for module in (dispatch, service):
        source = inspect.getsource(module)
        assert "PreEffectProof" not in source, (
            f"{module.__name__} constructs a pre-effect proof; FAILED is "
            "reachable from the synchronous path and CAP-013 must say so")


# ── the outcome is structural, not derived from prose ──────────────────────

def test_settlement_does_not_match_refusal_reason_strings():
    """The classifier must not regain a string dependency.

    Matching refusal_reason is how FAILED was decided before: every new
    refusal reason silently reclassified an outcome, and nothing announced it.
    """
    import inspect

    from remora.execution import outcome as outcome_module

    source = inspect.getsource(outcome_module.classify_outcome)
    # Strip the docstring: it explains WHY the reason is not read, and the
    # first version of this test failed on its own explanation.
    body = source.split('"""')[-1]
    assert "refusal_reason" not in body, (
        "classify_outcome reads refusal_reason; the settlement decision is "
        "string-derived again")


def test_an_unrecognised_refusal_reason_still_classifies():
    """A reason nobody has seen before must not fall through to a negative."""
    assert classify_outcome(_result(
        dispatch_began=True, state_unknown=True,
        refusal_reason="a_reason_added_next_year")) is DispatchOutcome.UNKNOWN


# ── durability, idempotency and supersession ───────────────────────────────

def _outbox(db):
    from remora.enforcement.outbox import SQLiteExecutionOutbox
    return SQLiteExecutionOutbox(db)


def _claimed_row(outbox, *, proposal="prop-1"):
    row = outbox.record_intent(
        proposal_id=proposal, tenant_id="acme", item_id="item-1",
        tool_name="wo_close", tool_call_hash="c" * 64, grant_jti="jti-1")
    return outbox.claim(row.outbox_id, worker_id="w1")


def test_unknown_survives_a_restart(tmp_path):
    """Durable, not merely returned.

    The response already said state_unknown; the durable record said REFUSED.
    A consumer reading the store after a restart got the opposite of the truth.
    """
    from remora.enforcement.outbox import OutboxState

    db = str(tmp_path / "outbox.db")
    outbox = _outbox(db)
    row = _claimed_row(outbox)
    outbox.settle(row.outbox_id, OutboxState.UNKNOWN,
                  detail="tool_failed_nonce_burned")

    reopened = _outbox(db)
    assert reopened.get(row.outbox_id).state is OutboxState.UNKNOWN


def test_settling_unknown_twice_is_refused_not_silently_overwritten(tmp_path):
    """Terminals are absorbing, and UNKNOWN is one of them.

    Idempotency here means a duplicate settlement cannot quietly change the
    record -- not that it is accepted twice.
    """
    from remora.enforcement.outbox import OutboxState

    outbox = _outbox(str(tmp_path / "outbox.db"))
    row = _claimed_row(outbox)
    outbox.settle(row.outbox_id, OutboxState.UNKNOWN, detail="first")

    with pytest.raises(ValueError, match="absorbing"):
        outbox.settle(row.outbox_id, OutboxState.UNKNOWN, detail="second")
    with pytest.raises(ValueError, match="absorbing"):
        outbox.settle(row.outbox_id, OutboxState.FAILED, detail="downgrade")


def test_unknown_is_never_retried(tmp_path):
    """Re-running a call that may already have taken effect is the one move
    the execution layer must never make."""
    from remora.enforcement.outbox import OutboxState

    outbox = _outbox(str(tmp_path / "outbox.db"))
    row = _claimed_row(outbox)
    outbox.settle(row.outbox_id, OutboxState.UNKNOWN, detail="lost response")

    assert outbox.get(row.outbox_id).is_terminal
    with pytest.raises(ValueError):
        outbox.claim(row.outbox_id, worker_id="w2")


def test_an_unknown_dispatch_can_still_be_verified_later():
    """UNKNOWN is durable but not the last word.

    The effect recorder accepts a receipt for a dispatch whose outcome is
    unknown -- a lost response does not mean nothing happened. Requiring a
    false SUCCEEDED first would be the opposite of what this model is for.
    """
    from datetime import UTC, datetime, timedelta

    from remora.governance.effect_receipt import verify_receipt
    from remora.governance.effect_verification import EffectStatus

    now = datetime.now(UTC)
    events = [{
        "event": "execution_result",
        "timestamp": (now - timedelta(seconds=10)).isoformat(),
        "payload": {"event": "execution_result", "proposal_id": "prop-1",
                    "tool_call_hash": "c" * 64, "grant_jti": "jti-1",
                    "tool_executed": False, "state_unknown": True},
    }]
    _lineage, status = verify_receipt(
        events=events, proposal_id="prop-1",
        claimed_status=EffectStatus.VERIFIED,
        tool_call_hash="c" * 64, grant_jti="jti-1",
        expected_sha256="d" * 64, observed_sha256="d" * 64,
        verified_at=now.isoformat(),
        verifier_identity="deployment-verifier", trusted_verifiers=())
    assert status is EffectStatus.VERIFIED


def test_succeeded_is_not_effect_verified():
    """Two different facts, kept apart.

    SUCCEEDED means the dispatcher confirmed the call returned. EFFECT_VERIFIED
    means the system of record was read back. The lifecycle model has no
    transition collapsing one into the other, and this pins that.
    """
    from remora.governance.lifecycle import ITEM_STATUS_STATE, IllegalTransition, check_transition

    assert ITEM_STATUS_STATE["executed"] == "SUCCEEDED"
    # SUCCEEDED reaches EFFECT_PENDING, and only an observation moves it on.
    assert check_transition("SUCCEEDED", "postcondition_declared") == (
        "EFFECT_PENDING")
    with pytest.raises(IllegalTransition):
        check_transition("SUCCEEDED", "declared_delta_observed")
