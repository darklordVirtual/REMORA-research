# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Issue #40 decision (a): approval suffices, because the re-gate refuses.

The review asked whether a tainted CRITICAL production write could be approved
by a human and executed without the argument ever being sanitised. The answer
is no, and the reason is not the approval step: a tainted argument decides
ESCALATE, and the execution re-gate only lets ACCEPT or VERIFY through, so the
approval cannot be redeemed while the taint still stands.

That makes the decision recorded in
``docs/architecture/ADR-tainted-argument-approval.md`` load-bearing rather than
a preference, so it is pinned here. The residual is pinned too: clearing the
taint is a caller assertion REMORA cannot verify, which is exactly the
one-bit-taint limitation tracked as RF-02, and the last test states it plainly
rather than leaving it as an inference.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from remora.governance.review_queue import ExecutionDecision, ReviewQueue
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation, canonical_tool_call_hash
from remora.policy.report import DecisionAction, DecisionReason

T0 = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
ARGS = {"recipient": "acct-9931", "amount": "250000"}
HASH = canonical_tool_call_hash(name="transfer_funds", arguments=ARGS, target="prod")


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _obs(*, tainted: bool) -> PolicyObservation:
    """The same critical production write, tainted or not."""
    return PolicyObservation(
        question="transfer_funds(recipient=acct-9931)",
        proposed_tool_name="transfer_funds",
        risk_tier="critical",
        action_type="production_write",
        target_environment="prod",
        schema_valid=True,
        trust_score=0.9,
        phase="ordered",
        evidence_action="verify",
        evidence_confidence=0.85,
        rollback_available=True,
        argument_tainted=tainted,
        tool_call_hash=HASH,
    )


def test_a_tainted_critical_write_escalates_rather_than_accepts() -> None:
    """Untrusted content controlling a sensitive argument is authorising."""
    report = RemoraDecisionEngine().decide(_obs(tainted=True))
    assert report.action is DecisionAction.ESCALATE
    assert DecisionReason.TAINTED_ARGUMENT_ESCALATE in report.reasons


def test_an_approved_tainted_call_is_refused_at_the_re_gate() -> None:
    """The load-bearing half of decision (a).

    A human may approve the item, but the approval is redeemed against a fresh
    decision, and ESCALATE is not an executable outcome. No sanitisation step
    is needed to stop this call, because it never reaches dispatch.
    """
    queue = ReviewQueue(now_fn=_Clock())
    item = queue.enqueue(_obs(tainted=True), DecisionAction.ESCALATE)
    queue.approve(item.item_id, approver="ops@example", approval_ttl=timedelta(minutes=15))

    outcome = queue.execute(item.item_id, _obs(tainted=True))

    assert outcome.decision is not ExecutionDecision.EXECUTE, (
        "an approved tainted call must not be executable while the taint stands"
    )


def test_the_payload_binding_still_holds_for_a_tainted_item() -> None:
    """The taint refusal must not be the only thing standing between an
    approved item and a different payload."""
    queue = ReviewQueue(now_fn=_Clock())
    item = queue.enqueue(_obs(tainted=True), DecisionAction.ESCALATE)
    queue.approve(item.item_id, approver="ops@example", approval_ttl=timedelta(minutes=15))

    mutated = PolicyObservation(
        **{
            **{
                k: v
                for k, v in vars(_obs(tainted=False)).items()
                if not k.startswith("_")
            },
            "tool_call_hash": canonical_tool_call_hash(
                name="transfer_funds",
                arguments={**ARGS, "recipient": "acct-0000"},
                target="prod",
            ),
        }
    )
    outcome = queue.execute(item.item_id, mutated)
    assert outcome.decision is ExecutionDecision.BINDING_REFUSED


VERIFY_ARGS = {"order": "WO-1", "action": "reschedule"}
VERIFY_HASH = canonical_tool_call_hash(
    name="update_work_order", arguments=VERIFY_ARGS, target="prod"
)


def _verify_obs(*, tainted: bool) -> PolicyObservation:
    """A production write whose only escalating factor is the taint.

    The critical transfer above escalates for a second, independent reason
    (``evidence_insufficient``), which is correct but hides the taint's own
    effect. This one isolates it: untainted it decides VERIFY, tainted it
    decides ESCALATE, and nothing else differs.
    """
    return PolicyObservation(
        question="update_work_order(order=WO-1)",
        proposed_tool_name="update_work_order",
        risk_tier="high",
        action_type="production_write",
        target_environment="prod",
        schema_valid=True,
        trust_score=0.86,
        phase="ordered",
        evidence_action="verify",
        evidence_confidence=0.8,
        rollback_available=True,
        argument_tainted=tainted,
        tool_call_hash=VERIFY_HASH,
    )


def test_below_critical_the_taint_is_a_verify_floor_not_an_escalation() -> None:
    """The rung decision (a) accepts, and the reason the residual exists.

    Escalating every tainted call would send a summary of an email to a human:
    friction with no decision to make. So below CRITICAL the taint holds a
    VERIFY floor instead, and VERIFY is an executable outcome.
    """
    engine = RemoraDecisionEngine()
    assert engine.decide(_verify_obs(tainted=False)).action is DecisionAction.VERIFY
    tainted = engine.decide(_verify_obs(tainted=True))
    assert tainted.action is DecisionAction.VERIFY
    assert DecisionReason.TAINTED_ARGUMENT_VERIFY in tainted.reasons


def test_a_second_escalating_factor_is_not_cleared_by_clearing_the_taint() -> None:
    """The critical transfer stays refused even untainted, on evidence grounds.

    Recorded so the contract is not misread as "clear the flag and it runs":
    the taint is one refusal among several, and the re-gate applies all of them.
    """
    queue = ReviewQueue(now_fn=_Clock())
    item = queue.enqueue(_obs(tainted=True), DecisionAction.ESCALATE)
    queue.approve(item.item_id, approver="ops@example", approval_ttl=timedelta(minutes=15))
    outcome = queue.execute(item.item_id, _obs(tainted=False))
    assert outcome.decision is not ExecutionDecision.EXECUTE
    assert outcome.fresh_action is DecisionAction.ESCALATE


def test_below_critical_an_approved_tainted_call_does_execute_unsanitised() -> None:
    """The residual of decision (a), pinned rather than described.

    This is the case option (b) would have closed: at HIGH risk the taint is a
    VERIFY floor, VERIFY is executable, so a reviewer's approval carries a
    still-tainted argument all the way to dispatch. Nothing sanitises it and
    nothing revalidates it.

    The test exists so the residual cannot be lost. If this ever starts
    failing because the call is refused, option (b) has effectively shipped and
    the ADR must be revisited rather than the test relaxed.
    """
    queue = ReviewQueue(now_fn=_Clock())
    item = queue.enqueue(_verify_obs(tainted=True), DecisionAction.VERIFY)
    queue.approve(item.item_id, approver="ops@example", approval_ttl=timedelta(minutes=15))

    outcome = queue.execute(item.item_id, _verify_obs(tainted=True))

    assert outcome.decision is ExecutionDecision.EXECUTE
    assert outcome.fresh_action is DecisionAction.VERIFY


def test_untrusted_control_of_a_sensitive_argument_escalates_at_any_tier() -> None:
    """The top rung, which is tier-independent: a caller-supplied "low" must
    not buy autonomy for an attacker-chosen recipient."""
    report = RemoraDecisionEngine().decide(
        PolicyObservation(
            question="transfer_funds(recipient=acct-9931)",
            proposed_tool_name="transfer_funds",
            risk_tier="low",
            action_type="production_write",
            target_environment="prod",
            schema_valid=True,
            trust_score=0.95,
            phase="ordered",
            evidence_action="accept",
            evidence_confidence=0.95,
            rollback_available=True,
            argument_tainted=True,
            untrusted_controlled_arguments=("recipient",),
            tool_call_hash=HASH,
        )
    )
    assert report.action is DecisionAction.ESCALATE
    assert DecisionReason.UNTRUSTED_CONTROLS_SENSITIVE_ARGUMENT in report.reasons
