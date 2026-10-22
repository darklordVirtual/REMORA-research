# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Assess use-case orchestration (issue #241, slice 7).

Moved from servers/execution_api.py with the module ambients as explicit
parameters. Route concerns stay in the route: authentication, capability
check, idempotency cache, the FT-02 lazy reconcile sweep and metrics.
Everything here is remora-internal — no HTTP types, no wire models beyond a
duck-typed proposal carrying tool_name/arguments/target_environment.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, NoReturn
from uuid import uuid4

from remora.enforcement.outbox import OutboxState
from remora.enforcement.token import AuthorizationContext, PolicyDecisionToken
from remora.errors import RemoraError
from remora.execution.outcome import DispatchOutcome, classify_outcome
from remora.execution.ports import (
    AuditChainPort,
    DispatchOutboxPort,
    EnforcementGatePort,
    PolicyDecisionTokenPort,
    PolicyEnginePort,
    ToolCallPort,
    TransactionalAppendPort,
    Ws1AdmissionPort,
    Ws1GatePort,
    Ws1OutcomePort,
    appender,
    audit_ref,
)
from remora.execution.request_ref import RequestRef, request_ref_of
from remora.governance.audit_outbox import encode_key
from remora.governance.delegation import delegated_executor_of
from remora.governance.execution_identity import (
    ExecutionContextProvider,
    ExecutionContextRefused,
    ExecutionContextV1,
    historical_context,
    observation_binding,
)
from remora.governance.proposal_lineage import derive_lineage, lineage_key_for
from remora.governance.review_queue import ExecutionDecision
from remora.governance.task_identity import TaskIdentity
from remora.policy.report import DecisionAction, DecisionReason, DecisionReport
from remora.toolcall.toolspec import ToolSpecRefused

logger = logging.getLogger(__name__)



def _refuse_minting_on_a_redeemer() -> None:
    """Refuse a flow that mints a decision grant in a verify-only process."""
    from remora.enforcement.token import GrantMintingRefused, verify_only

    if verify_only():
        raise GrantMintingRefused(
            "this process holds only REMORA_PDP_VERIFY_KEYS_ED25519: it redeems "
            "decision grants and cannot mint them; route this request to the PDP "
            "(RMR-CR-002)")

def _bind_execution_context(
    obs: Any, semantic: dict[str, Any], context: ExecutionContextV1 | None,
    *, proposal_id: str, tenant: str, principal: str,
) -> Any:
    if context is None:
        return obs
    context.check_binding(
        proposal_id=proposal_id, tenant=tenant, principal=principal,
        tool_call_hash=obs.tool_call_hash or "")
    semantic["execution_context_hash"] = context.digest()
    semantic["execution_context_canonical"] = context.canonical_bytes().decode("utf-8")
    return dataclasses.replace(
        obs, proposal_id=proposal_id, execution_context_hash=context.digest())


#: The outbox state each outcome settles as. A table rather than a chain of
#: conditionals, so a new outcome is a compile-time gap instead of a silent
#: fall-through to the last else.
_OUTBOX_STATE = {
    DispatchOutcome.SUCCEEDED: OutboxState.SUCCEEDED,
    DispatchOutcome.REFUSED: OutboxState.REFUSED,
    DispatchOutcome.FAILED: OutboxState.FAILED,
    DispatchOutcome.UNKNOWN: OutboxState.UNKNOWN,
}


#: What a dispatch that never happened looks like, because this worker lost the
#: exclusive claim on the intent.
#:
#: ``dispatch_began`` is False and ``state_unknown`` is False, so
#: ``classify_outcome`` reads REFUSED: this worker observed itself not act, the
#: one negative claim it can make first-hand. It is deliberately NOT settled
#: into the outbox and NOT recorded as the item's terminal state -- the winning
#: worker owns both, and the effect it produces is the real one.
_CLAIM_LOST = "outbox_claim_lost"


def _claim_or_none(
    outbox_factory: Callable[[], Any],
    intent: Any,
    *,
    worker_id: str,
) -> bool:
    """Claim the intent exclusively, or report that another worker holds it.

    Returns True when this worker may dispatch. The return value of ``claim``
    used to be discarded at both call sites under a comment reading "claim the
    intent before anything can take effect (exclusive)". A lost race returns
    None, so both workers went on to dispatch the same intent and the second
    settled over the first's row. The exclusivity the outbox exists to provide
    was documented, not enforced.
    """
    if intent is None:
        return True
    return outbox_factory().claim(intent.outbox_id, worker_id=worker_id) is not None


def _settle_reported(
    outbox_factory: Callable[[], Any],
    outbox_id: str,
    state: Any,
    *,
    detail: str | None,
    projection_json: str | None,
) -> tuple[Any, bool]:
    """Settle the claimed row, or keep the terminal someone else already wrote.

    Returns the row and whether it was already terminal when this worker
    reported. That happens when the stale-dispatch sweep settles a claim as
    UNKNOWN while the worker is still inside the tool call: a tool slower
    than ``REMORA_OUTBOX_STALE_SECONDS``, or a sweeper whose clock runs
    ahead. Terminals are absorbing, so the UNKNOWN stands. The worker's
    outcome is still the authoritative observation the UNKNOWN is waiting
    for (``DispatchOutcome.UNKNOWN``: "a later authoritative observation may
    supersede it"), so the caller records it as a new record instead of
    failing the request and losing it. Any other refusal is re-raised.
    """
    try:
        return outbox_factory().settle(
            outbox_id, state, detail=detail,
            projection_json=projection_json), False
    except ValueError:
        row = outbox_factory().get(outbox_id)
        if not row.is_terminal:
            raise
        return row, True


def _mark_reported_after_terminal(record: dict[str, Any], row: Any) -> None:
    """Say on the result record that the outbox row was settled before it."""
    record["outbox_terminal_state"] = row.state.value
    record["reported_after_terminal"] = True


def _claim_lost_response(
    response: dict[str, Any],
    *,
    chain: AuditChainPort,
    tenant: str,
    principal: str,
    proposal_id: Any,
    item_id: str,
    tool_call_hash: str,
    grant_jti: str,
    intent_sequence_no: int | None,
) -> dict[str, Any]:
    """Record and return "another worker holds this intent".

    The chain gets a result record like any other dispatch, because the absence
    of a dispatch is itself an auditable outcome and a gap in the chain would
    read as a lost event rather than a refusal. What it does NOT do is settle
    the outbox row or drive the item to a terminal state: both belong to the
    worker that won the claim, and writing them here would overwrite the record
    of the execution that actually happens.

    On the review path the claim precedes the grant, so the loser passes an
    empty ``grant_jti`` and no ``intent_sequence_no``: it consumed nothing and
    appended no authorization for this record to point at.
    """
    tool_execution = {
        "executed": False,
        "dispatch_began": False,
        "state_unknown": False,
        "refusal_reason": _CLAIM_LOST,
    }
    entry = chain.append(tenant, {
        "event": "execution_result",
        "proposal_id": proposal_id,
        "actor": principal,
        "item_id": item_id,
        "tool_call_hash": tool_call_hash,
        "grant_jti": grant_jti,
        "intent_sequence_no": intent_sequence_no,
        "tool_executed": False,
        "state_unknown": False,
        "tool_refusal_reason": _CLAIM_LOST,
    })
    response["tool_execution"] = tool_execution
    response["audit"] = {
        "sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash,
    }
    return response


def _policy_bundle_hash(provider: Callable[[], str] | None) -> str:
    """The composite policy-bundle hash in force, or "" if none is wired.

    Deliberately not defaulted to a plausible-looking value: an authorization
    context that could not learn which bundle it was decided under says so,
    and the empty string is what an unbound field has always meant here.
    """

    return str(provider() or "") if provider is not None else ""


def assess_proposal(
    *,
    tenant: str,
    principal: str,
    proposal: ToolCallPort,
    engine: PolicyEnginePort,
    chain: AuditChainPort,
    transaction: Callable[[str], Any],
    item_tenant: dict[str, str],
    build_observation: Callable[[Any, str], tuple[Any, dict[str, Any]]],
    resolve_toolspec: Callable[[str, dict[str, Any], str], dict[str, Any]],
    lifecycle_guard: Callable[..., None],
    resolution_plan_for: Callable[..., dict[str, Any] | None],
    note_proposal_id: Callable[[Any], None],
    token_audience: str,
    token_ttl_seconds: int,
    policy_bundle_hash: Callable[[], str] | None = None,
    loop_safety: Any = None,
    capability_gate: Callable[[Any], dict[str, Any] | None] | None = None,
    semantic_shadow: Callable[[dict[str, Any]], None] | None = None,
    execution_context_provider: ExecutionContextProvider | None = None,
    require_execution_context: bool = False,
    ws1_gate: Ws1GatePort | None = None,
) -> dict[str, Any]:
    """Assess a proposed tool call — nothing executes here.

    Authoritative signals are derived server-side (registry/ToolSpec/
    semantic bundle); the proposal can only lower trust. ACCEPT mints a
    signed single-use execution token bound to the exact call; VERIFY/
    ESCALATE enqueue a review item inside the durable transaction (the
    item→tenant binding is part of the same durable write, or a restart
    leaves an item the API refuses as unknown — external review
    2026-07-27); ABSTAIN returns neither. Every assessment appends to the
    tenant audit chain.

    ``loop_safety`` (Q7.2) is a ``LoopSafetyMonitor``. For a proposal that
    names a task, the context's accumulated state is read first: when it has
    reached a limit, an ACCEPT becomes ESCALATE, so a context that has been
    probing does not keep acting autonomously. The downgrade never goes the
    other way. The decision is then recorded against the context. A store
    that cannot answer raises before anything is decided or recorded.

    ``capability_gate`` (Q8.2) returns the capability block for the proposal:
    the effective set it was checked against and whether the tool is in it.
    A tool outside the set is ABSTAIN with ``capability_not_allowed``, whatever
    the engine decided. None from the gate means no capability policy applies.

    ``semantic_shadow`` receives the proposal, the observation and both
    actions after the audit record is durable. It is shadow only: it runs
    after everything that decides, records or responds, its return value is
    ignored, and any exception it raises is swallowed. See
    ``servers/semantic_shadow.py``.

    ``ws1_gate`` (issue #953) runs the WS1 precondition loop and composition
    after every other component. In shadow mode its record is audited and
    nothing else changes. In enforce mode any WS1 cap makes the call ABSTAIN,
    and an ACCEPT carries the WS1 binding in its authorization context.
    """
    task = task_identity_of(proposal)
    request_ref = request_ref_of(proposal)
    prior_loop = (
        loop_safety.assess(tenant, task.context_id)
        if loop_safety is not None and task is not None else None
    )
    obs, semantic = build_observation(proposal, tenant)
    toolspec_identity = resolve_toolspec(
        proposal.tool_name, proposal.arguments, proposal.target_environment
    )
    # Popped, not recorded: the roles are spec data the lineage key needs,
    # and copying them into every audit record and response would grow
    # both without telling a reader anything the spec hash does not.
    argument_roles = toolspec_identity.pop("argument_roles", {})
    # FT-01: mint the canonical proposal identity here — every downstream
    # record, response and grant for this action carries it.
    proposal_id = str(uuid4())
    note_proposal_id(proposal_id)
    obs = dataclasses.replace(obs, proposal_id=proposal_id)
    if require_execution_context and execution_context_provider is None:
        raise ExecutionContextRefused("execution_context_provider_missing")
    context = None
    if execution_context_provider is not None:
        context = execution_context_provider.capture(
            proposal_id=proposal_id, tenant=tenant, principal=principal,
            tool_call_hash=obs.tool_call_hash or "")
        if not isinstance(context, ExecutionContextV1):
            raise ExecutionContextRefused("execution_context_capture_invalid")
    obs = _bind_execution_context(
        obs, semantic, context, proposal_id=proposal_id, tenant=tenant, principal=principal)
    capability = capability_gate(proposal) if capability_gate is not None else None

    def adjusted(report: DecisionReport) -> DecisionReport:
        """The engine's report under loop safety and the capability set."""
        if (prior_loop is not None and prior_loop.action == "escalate"
                and report.action is DecisionAction.ACCEPT):
            report = dataclasses.replace(
                report,
                action=DecisionAction.ESCALATE,
                reasons=(*report.reasons, DecisionReason.LOOP_SAFETY_ESCALATE),
                human_review_required=True,
            )
        if capability is not None and not capability.get("allowed"):
            report = dataclasses.replace(
                report,
                action=DecisionAction.ABSTAIN,
                reasons=(*report.reasons, DecisionReason.CAPABILITY_NOT_ALLOWED),
            )
        return report

    decided = engine.decide(obs)
    engine_action = decided.action
    report = adjusted(decided)
    ws1: Ws1OutcomePort | None = None
    if ws1_gate is not None:
        # Last, so it composes against every other component's decision. It
        # can only lower that decision (Ws1Outcome.apply), never raise it.
        ws1 = ws1_gate.evaluate(
            proposal_id=proposal_id, tenant=tenant, principal=principal,
            tool_name=proposal.tool_name, arguments=proposal.arguments,
            intent_authority_hash=str(semantic.get("intent_authority_hash") or ""),
            policy_bundle_hash=_policy_bundle_hash(policy_bundle_hash),
            toolspec_hash=str(toolspec_identity.get("hash") or ""),
            capability=capability, flow_digest=obs.flow_digest, flow_epoch=obs.flow_epoch,
            attempt_family_id=task.context_id if task is not None else None,
            base=report, task_id=_ws1_task_id(task),
            # Grounding from proofs: the ENGINE re-decides on the observation
            # plus the signals WS1's PROVED evidence established, under the
            # same loop-safety and capability adjustments. WS1 never raises a
            # decision itself, and its caps apply to the re-decided report.
            redecide=lambda facts: adjusted(engine.decide(dataclasses.replace(obs, **facts))))
        grounded = getattr(ws1, "grounded_report", None)
        if grounded is not None and ws1.mode == "enforce":
            report = _never_raised(grounded, ws1.apply(grounded))
        else:
            report = _never_raised(report, ws1.apply(report))
    now = datetime.now(UTC)

    # Derived from the chain, never from the request: a caller-declared
    # "this supersedes X" would be defeated by the one caller it exists to
    # catch. Read BEFORE any transaction opens — reading the chain inside
    # one deadlocks against SQLite's exclusive write lock.
    lineage_key = lineage_key_for(
        actor=principal,
        tool_name=proposal.tool_name,
        target_environment=proposal.target_environment or "",
        arguments=proposal.arguments,
        argument_roles=argument_roles,
    )
    lineage = derive_lineage(
        [{"timestamp": e.timestamp, "payload": e.payload}
         for e in chain.entries(tenant)],
        lineage_key, now=datetime.now(UTC).isoformat(),
    )

    record: dict[str, Any] = {
        "event": "assessed",
        "proposal_id": proposal_id,
        "actor": principal,
        "tool_name": proposal.tool_name,
        "tool_call_hash": obs.tool_call_hash,
        # Carried so a LATER derivation can match this proposal; without
        # them the lineage key could never be reconstructed from the chain.
        "target_environment": proposal.target_environment or "",
        "lineage_resource": lineage_key.resource,
        "superseded_proposal_id": lineage.superseded_proposal_id,
        "lineage": lineage.to_dict(),
        "decision": report.action.value,
        "reasons": [r.value for r in report.reasons],
        "policy_version": report.policy_version,
        # SHELF-020: empty strings mean "no bundle configured" — recorded,
        # never assumed away.
        "tool_contract_bundle_hash": semantic["tool_contract_bundle_hash"],
        "state_hash": semantic["state_hash"],
        "intent_authority_hash": semantic["intent_authority_hash"],
        "intent_resolution_status": obs.intent_resolution_status,
        "toolspec_hash": toolspec_identity["hash"],
        "toolspec_version": toolspec_identity["version"],
    }
    if task is not None:
        record["context_id"] = task.context_id
        record["task_id"] = task.task_id
    if request_ref is not None:
        record["request_ref"] = request_ref.to_dict()
        record["request_ref_hash"] = request_ref.digest()
    # RMR-AUD-001: the whole proposal, so execution can be refused for
    # presenting another one under this approval.
    record["proposal_envelope_hash"] = proposal_envelope_hash(proposal)
    delegate = delegated_executor_of(proposal)
    if delegate:
        # Admitted by the route before this function ran; recorded here so
        # the reviewer, the approval record and execution read one value.
        record["delegated_executor"] = delegate
    if context is not None:
        record["execution_context_hash"] = context.digest()
        record["execution_context_canonical"] = context.canonical_bytes().decode("utf-8")
        record["observation_binding_hash"] = observation_binding(obs)
    if capability is not None:
        record["capability"] = capability
    if ws1 is not None:
        record["ws1"] = ws1.audit_block()
    response: dict[str, Any] = {
        "proposal_id": proposal_id,
        "decision": report.action.value,
        "reasons": [r.value for r in report.reasons],
        "tool_call_hash": obs.tool_call_hash,
        "semantic": dict(semantic),
        "toolspec": dict(toolspec_identity),
    }
    if capability is not None:
        response["capability"] = capability
    if ws1 is not None:
        block = ws1.audit_block()
        response["ws1"] = {k: block[k] for k in ("mode", "status", "final_action")}
    # FT-01 conformance BEFORE anything is recorded.
    branch_event = {
        DecisionAction.ACCEPT: "direct_accept_token",
        DecisionAction.VERIFY: "verify_or_escalate",
        DecisionAction.ESCALATE: "verify_or_escalate",
        DecisionAction.ABSTAIN: "abstain_or_hard_refusal",
    }.get(report.action, "abstain_or_hard_refusal")
    lifecycle_guard("PROPOSED", "engine_decision", branch_event)

    if loop_safety is not None and task is not None:
        # Recorded before the token or review item exists, so a failure to
        # record refuses the whole assessment instead of issuing authority
        # the context's history does not show.
        after = loop_safety.observe(
            tenant, task, proposal.tool_name,
            denied=report.action is DecisionAction.ABSTAIN,
        )
        loop_summary = {
            "context_id": task.context_id,
            "action": after.action,
            "reached": list(after.reached),
            "escalated_by_loop_state": (
                DecisionReason.LOOP_SAFETY_ESCALATE in report.reasons),
        }
        record["loop_safety"] = loop_summary
        response["loop_safety"] = loop_summary

    item = None
    if report.action is DecisionAction.ACCEPT:
        _refuse_minting_on_a_redeemer()
        # This is the token a caller holds and later redeems at
        # /execute-accepted, which deliberately does not re-run the engine. The
        # conditions the decision was made under are therefore signed into it,
        # or redemption has nothing to check them against (RMR-001).
        grant_context = authorization_context(
            tenant=tenant, principal=principal, semantic=semantic,
            target_environment=proposal.target_environment or "",
            policy_bundle_hash=_policy_bundle_hash(policy_bundle_hash),
            toolspec_hash=str(toolspec_identity["hash"]),
            task=task,
            request_ref=request_ref,
            delegated_executor=delegate,
            ws1_binding_hash=(ws1.binding_hash
                              if ws1 is not None and ws1.mode == "enforce" else ""),
        )
        token = PolicyDecisionToken.issue(
            action="accept",
            observation_hash=observation_binding(obs),
            request_id=proposal_id,
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=token_ttl_seconds)).isoformat(),
            audience=token_audience,
            context=grant_context,
        )
        record["grant_jti"] = token.jti
        # The fields the grant's context_hash covers, so an exported grant can
        # be checked against them without re-deriving any of them.
        record["authorization_context"] = grant_context.to_dict()
        response["execution_token"] = token.to_dict()
    else:
        with transaction(tenant) as q:
            # REM-032 lazy sweep: overdue PENDING items resolve to ABSTAIN
            # before new work is considered.
            q.expire_due()
            item = q.enqueue(
                obs, report.action,
                reasons=[r.value for r in report.reasons],
            ) if report.action in (
                DecisionAction.VERIFY, DecisionAction.ESCALATE
            ) else None
            if item is not None:
                # Inside the transaction: the item→tenant binding is part
                # of the same durable write as the item itself.
                item_tenant[item.item_id] = tenant
        if item is not None:
            record["review_item_id"] = item.item_id
            response["review_item_id"] = item.item_id

    # Shadow only: the decision above was NOT influenced by this.
    response["lineage"] = lineage.to_dict()
    response["resolution_plan"] = resolution_plan_for(
        action=report.action, report=report, tenant=tenant,
        item=item if report.action is not DecisionAction.ACCEPT else None,
    )
    entry = chain.append(tenant, record)
    response["audit"] = {
        "sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash,
    }
    if semantic_shadow is not None:
        # Shadow only, after the record is durable: nothing below can change
        # the decision, the record or the response, and a fault is swallowed
        # so a sensor outage never becomes an assess failure.
        try:
            semantic_shadow({
                "tenant": tenant,
                "proposal_id": proposal_id,
                "proposal": proposal,
                "observation": obs,
                "engine_action": engine_action,
                "final_action": report.action,
            })
        except Exception as exc:
            # The semantic provider is shadow-only, so an outage must not
            # affect the governed decision. Record only the exception type to
            # avoid leaking provider payloads or credentials into logs.
            logger.warning("semantic shadow sensor failed: %s", type(exc).__name__)
    return response


class ToolSpecChanged(RemoraError):
    """The spec in force is not the one the approval was granted under
    (route maps to 409). Refused BEFORE authorizing - a refused call must
    leave no dispatch intent behind (handoff gate section 3)."""

    code = "toolspec_changed"
    category = "execution"
    #: Published reason code (schemas/tool_spec_v1.yaml); the wire detail.
    reason = "toolspec_changed_between_assess_and_dispatch"


class ApprovalContextRefused(RemoraError):
    """The approved item is presented by another actor or under another task
    than the proposal it was approved for (route maps to 409).

    ``reason`` is the wire detail and uses the ACCEPT path's vocabulary:
    ``context_mismatch`` when a bound field differs, ``context_unbound``
    when the proposal's assessment cannot be read back to compare against.
    """

    code = "approval_context_refused"
    category = "execution"

    def __init__(self, message: str, *, reason: str,
                 mismatched: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.reason = reason
        self.mismatched = mismatched


#: The AuthorizationContext fields the review path binds to the proposal.
#: The ACCEPT token binds all of its fields because nothing is decided again
#: at redemption. The review path re-decides on a fresh observation, so the
#: other fields are covered elsewhere: the target and arguments by the queue's
#: payload binding (tool_call_hash), the ToolSpec hash by FT-03, the policy
#: bundle by the fresh decision and the approval-policy hash, the reviewed risk
#: tier by ReviewQueue step 4b', and the execution context by the queue's own
#: binding. The intent authority is bound here (RMR-AUD-006): the fresh
#: decision re-reads it but does not compare it with the one approved, so an
#: item approved under one intent executed under another, and the new hash was
#: signed into the grant, the lease and the audit record.
_REVIEW_BOUND_FIELDS = ("principal", "context_id", "task_id", "delegated_executor",
                        "intent_authority_hash")


#: The proposal fields outside ``canonical_tool_call_hash``. The review path
#: binds them to the assessment (RMR-AUD-001). The hash covers only the tool,
#: arguments, tenant and target, which the queue's payload binding already
#: refuses as ``binding_refused``. The rest still decide: ``schema_valid``,
#: ``rollback_available`` and ``untrusted_context`` lower trust, ``intent_ref``
#: selects the intent authority, and ``derivations`` grounds argument values.
#: Unbound, a caller could get one decision approved and execute under another.
#: ``idempotency_key`` is exempt because it names a request, not the call.
#: tests/test_review_path_audit_r3.py pins this tuple to the wire model, so a
#: new field is bound or exempted on purpose.
PROPOSAL_ENVELOPE_FIELDS = (
    "schema_valid", "rollback_available", "intent_ref", "untrusted_context",
    "derivations", "context_id", "task_id", "plan", "task_type",
    "delegated_executor", "request_ref",
)


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def proposal_envelope_hash(tool_call: Any) -> str:
    """SHA-256 over the proposal fields outside the payload hash, as presented.

    Read by attribute, so the wire model and a duck-typed call hash alike;
    an absent field hashes as null.
    """
    envelope = {f: _plain(getattr(tool_call, f, None))
                for f in PROPOSAL_ENVELOPE_FIELDS}
    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                           default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def proposal_envelope_refusal(
    chain: AuditChainPort, tenant: str, proposal_id: str, tool_call: Any,
) -> ApprovalContextRefused | None:
    """The refusal for presenting ``tool_call`` against an approval of a
    different proposal, or None.

    The approved proposal is the hash the ``assessed`` record carries. A
    record without one (assessed before this binding) cannot be compared and
    is refused, so a pending item from before the upgrade must be proposed
    again rather than executed unbound.
    """
    record = _assessed_payload(chain, tenant, proposal_id)
    approved = str((record or {}).get("proposal_envelope_hash") or "")
    if approved and approved == proposal_envelope_hash(tool_call):
        return None
    return ApprovalContextRefused(
        "binding refused: the presented proposal differs from the one this "
        "item was approved for",
        reason="binding_refused",
        mismatched=("proposal_envelope",))


def _assessed_payload(
    chain: AuditChainPort, tenant: str, proposal_id: str
) -> dict[str, Any] | None:
    """The proposal's single ``assessed`` record, or None when there is not
    exactly one with an actor."""
    assessed = [
        e.payload for e in chain.entries(tenant)
        if e.payload.get("event") == "assessed"
        and e.payload.get("proposal_id") == proposal_id
    ] if proposal_id else []
    if len(assessed) != 1 or not str(assessed[0].get("actor") or ""):
        return None
    return dict(assessed[0])


def _acting_for(record: dict[str, Any] | None, executor: str) -> str:
    """The proposer ``executor`` acts for as its bound delegate, or "".

    Only the delegate the ``assessed`` record names qualifies; the proposer
    acting for itself is not a delegation.
    """
    if record is None:
        return ""
    delegate = str(record.get("delegated_executor") or "")
    proposer = str(record.get("actor") or "")
    if delegate and executor == delegate and executor != proposer:
        return proposer
    return ""


def approved_context_refusal(
    chain: AuditChainPort,
    tenant: str,
    proposal_id: str,
    current: AuthorizationContext,
) -> ApprovalContextRefused | None:
    """The refusal for presenting an approved item under ``current``, or None.

    The approved context is ``current`` with the bound fields replaced by
    what the proposal's ``assessed`` record says: the authenticated proposer
    and its task. Both sides are :class:`AuthorizationContext` values built by
    :func:`authorization_context` and compared by hash, the comparison the
    ACCEPT token makes at redemption.

    Same actor means the proposer, or the delegate the proposal named when it
    was assessed. The delegate is compared as the proposer it acts for, and
    the ``delegated_executor`` field itself is compared like the task, so a
    delegate added, swapped or stripped after approval is a mismatch. The
    agent is the attacker in the threat model, so another agent in the tenant
    is not this one's delegate unless the deployment declared it and the
    proposal named it. A proposal whose assessment is missing, or recorded
    more than once, is refused rather than compared with nothing.

    Read-only, and it reads the chain, so it runs before the execute
    transaction opens (see ``assessed_record``).
    """
    record = _assessed_payload(chain, tenant, proposal_id)
    if record is None:
        return ApprovalContextRefused(
            "the proposal this item was approved for cannot be read back",
            reason="context_unbound")
    proposer = str(record.get("actor") or "")
    approved = dataclasses.replace(
        current,
        principal=proposer,
        context_id=str(record.get("context_id") or ""),
        task_id=str(record.get("task_id") or ""),
        delegated_executor=str(record.get("delegated_executor") or ""),
        intent_authority_hash=str(record.get("intent_authority_hash") or ""),
    )
    acting_for = _acting_for(record, current.principal)
    presented = (dataclasses.replace(current, principal=acting_for)
                 if acting_for else current)
    if approved.hash() == presented.hash():
        return None
    return ApprovalContextRefused(
        "authorization context refused: this item was approved for a "
        "different actor, task or delegate than the one presented here",
        reason="context_mismatch",
        mismatched=tuple(f for f in _REVIEW_BOUND_FIELDS
                         if getattr(approved, f) != getattr(presented, f)))


def execute_approved_item(
    *,
    tenant: str,
    principal: str,
    item_id: str,
    tool_call: ToolCallPort,
    transaction: Callable[[str], Any],
    item_tenant: dict[str, str],
    chain: AuditChainPort,
    gate: EnforcementGatePort,
    outbox: Callable[[], DispatchOutboxPort],
    worker_id: str,
    build_observation: Callable[[Any, str], tuple[Any, dict[str, Any]]],
    resolve_toolspec: Callable[[str, dict[str, Any], str], dict[str, Any]],
    assessed_record: Callable[[str, str], tuple[str, str]],
    record_dispatch_intent: Callable[..., Any],
    dispatch_under_lease: Callable[..., dict[str, Any]],
    lifecycle_guard: Callable[..., None],
    note_proposal_id: Callable[[Any], None],
    not_found: type[Exception],
    conflict: type[Exception],
    token_audience: str,
    token_ttl_seconds: int,
    policy_coverage: Callable[[], dict[str, Any]] | None = None,
    policy_bundle_hash: Callable[[], str] | None = None,
    async_dispatch: bool = False,
    transactional_append: TransactionalAppendPort | None = None,
    require_execution_context: bool = False,
    approval_policy: Callable[[Any], str] | None = None,
    ws1_gate: Ws1GatePort | None = None,
    ws1_capability: Callable[[Any, str], Any] | None = None,
    ws1_admission: Ws1AdmissionPort | None = None,
    active_connection: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Execute a previously approved item under full re-gating.

    With ``async_dispatch`` (issue #82) the function returns after DURABLE
    AUTHORIZATION — the queue's EXECUTE outcome and the dispatch-intent row
    commit in one transaction, and the response says ``dispatch: pending``.
    No grant is minted and no PEP consumption happens here: both belong to
    the moment of honouring, which a separate worker performs via
    :func:`dispatch_pending_intent`. The synchronous default is unchanged.

    The complete payload is re-presented and freshly re-decided; a
    single-use grant is consumed atomically; dispatch goes through the
    governed dispatcher; authorization and result are separate chain
    records (authorized-for-execution and actually-executed are distinct
    states - external review 2026-07-27).

    ``approval_policy`` maps the fresh observation to the hash of the
    approval requirement in force for it now (the role its tier requires).
    The queue voids an approval granted under another requirement, or under
    none recorded. None leaves the requirement unchecked (library use).

    Under WS1 enforce (issue #953) the WS1 gate must reach ACCEPT again,
    with fresh lookups, before the queue is touched. An approval lifts the
    engine's route only; it never stands in for a WS1 precondition. A refusal
    leaves the approval standing, like a context refusal.
    """
    # RMR-CR-002: the review path mints and consumes in this process. A
    # redeemer holding only verify keys cannot do the first half, so it refuses
    # here, before anything is claimed, rather than halfway through.
    _refuse_minting_on_a_redeemer()
    # FT-03: the spec in force NOW, compared with the hash the assessment
    # recorded - an approval granted under one spec must never execute
    # under another. Refused BEFORE authorizing.
    toolspec_identity = resolve_toolspec(
        tool_call.tool_name, tool_call.arguments, tool_call.target_environment
    )
    toolspec_identity.pop("argument_roles", None)
    assessed_toolspec_hash, assessed_proposal_id = assessed_record(tenant, item_id)
    note_proposal_id(assessed_proposal_id)
    if (toolspec_identity["enforced"] and assessed_toolspec_hash
            and toolspec_identity["hash"] != assessed_toolspec_hash):
        chain.append(tenant, {
            "event": "execution_toolspec_changed",
            "proposal_id": assessed_proposal_id,
            "actor": principal,
            "item_id": item_id,
            "assessed_toolspec_hash": assessed_toolspec_hash,
            "current_toolspec_hash": toolspec_identity["hash"],
        })
        raise ToolSpecChanged(
            "toolspec_changed_between_assess_and_dispatch: the spec "
            "in force is not the one this approval was granted under"
        )

    fresh_obs, fresh_semantic = build_observation(tool_call, tenant)
    # The approval belongs to the proposal's actor and task, as an ACCEPT
    # token does. Read from the chain here, outside any transaction, for the
    # reason assessed_record gives; raised inside the transaction, after the
    # tenant check and before the queue is touched, so an unknown item still
    # answers not-found and a refused presentation neither consumes nor voids
    # the approval for the actor and task it was granted to.
    context_refusal = approved_context_refusal(
        chain, tenant, assessed_proposal_id,
        authorization_context(
            tenant=tenant, principal=principal, semantic=fresh_semantic,
            target_environment=tool_call.target_environment or "",
            policy_bundle_hash=_policy_bundle_hash(policy_bundle_hash),
            toolspec_hash=str(toolspec_identity["hash"]),
            task=task_identity_of(tool_call),
            delegated_executor=delegated_executor_of(tool_call),
        ))
    # Then the proposal itself (RMR-AUD-001): the fields outside the payload
    # hash must be the ones assessed, or a call approved as one decision could
    # be re-presented as another. Same placement, same non-consumption.
    context_refusal = context_refusal or proposal_envelope_refusal(
        chain, tenant, assessed_proposal_id, tool_call)
    acting_for = _acting_for(
        _assessed_payload(chain, tenant, assessed_proposal_id), principal)
    admitting = (ws1_admission is not None and ws1_gate is not None
                 and ws1_gate.mode == "enforce")
    epochs_before: dict[str, int] | None = None
    ws1: Any = None
    if context_refusal is None and admitting:
        assert ws1_admission is not None
        epochs_before, why = ws1_admission.before_regate(
            ws1_gate, tenant=tenant, tool_name=tool_call.tool_name)
        if epochs_before is None:
            context_refusal = ApprovalContextRefused(
                f"WS1-M4 admission refused: {why}", reason=why)
    if context_refusal is None:
        proposer = str((_assessed_payload(chain, tenant, assessed_proposal_id) or {})
                       .get("actor") or principal)
        ws1 = ws1_regate(
            ws1_gate, chain=chain, tenant=tenant, proposal_id=assessed_proposal_id,
            proposer=proposer, tool_call=tool_call, semantic=fresh_semantic,
            observation=fresh_obs, toolspec_hash=str(toolspec_identity["hash"]),
            policy_bundle_hash=_policy_bundle_hash(policy_bundle_hash),
            capability=(ws1_capability(tool_call, proposer)
                        if ws1_capability is not None else None),
            review_attestation=(stored_approval(transaction, tenant, item_id)
                                if ws1_gate is not None else None))
        ws1_binding_matches = _ws1_approval_binding_matches(
            chain, tenant, assessed_proposal_id, ws1)
        if not ws1_binding_matches or (
                ws1 is not None and ws1.final_action is not DecisionAction.ACCEPT):
            chain.append(tenant, {
                "event": "execution_ws1_refused",
                "proposal_id": assessed_proposal_id,
                "actor": principal,
                "item_id": item_id,
                "ws1": ws1.audit_block() if ws1 is not None else {"mode": "off_or_shadow"},
                "ws1_binding_matches": ws1_binding_matches,
            })
            context_refusal = ApprovalContextRefused(
                "WS1 re-gate refused: a precondition is not proved now",
                reason=WS1_REGATE_REFUSED)
    context = historical_context(
        chain, tenant, assessed_proposal_id, required=require_execution_context)
    fresh_obs = _bind_execution_context(
        fresh_obs, fresh_semantic, context, proposal_id=assessed_proposal_id,
        tenant=tenant, principal=principal)
    append = appender(chain, transactional_append)
    refusal_entry: Any = None
    refusal_key = ""
    try:
        # Tenant binding inside the transaction (review finding 2a); the
        # canonical proposal identity rides the QUEUED observation - the
        # re-presented payload never carries one the caller could assert.
        with transaction(tenant) as q:
            if item_tenant.get(item_id) != tenant:
                raise not_found(item_id)
            if context_refusal is not None:
                raise context_refusal
            q.expire_due()
            proposal_id = getattr(q.item(item_id).observation,
                                  "proposal_id", None)
            note_proposal_id(proposal_id)
            outcome = q.execute(
                item_id, fresh_obs,
                approval_policy_hash=(approval_policy(fresh_obs)
                                      if approval_policy is not None else None))
            if outcome.decision is not ExecutionDecision.EXECUTE:
                # REM-047: a re-gate refusal is a terminal state transition,
                # and its audit event now commits with it. Appended after the
                # commit, a crash in between left an item refused with no
                # record of the refusal.
                #
                # One key per attempt (RMR-AUD-005). A binding refusal leaves
                # the approval standing and an expiry returns the item to the
                # queue, so the same item can be refused again; a key naming
                # only the item dropped every refusal after the first. The
                # append commits with this transaction, so a crash re-runs the
                # attempt rather than replaying this key.
                refusal_key = encode_key(
                    tenant, f"execution_{outcome.decision.value}", item_id,
                    uuid4().hex)
                refusal_entry = append(tenant, {
                    "event": f"execution_{outcome.decision.value}",
                    "proposal_id": proposal_id,
                    "actor": principal,
                    "item_id": item_id,
                    "tool_call_hash": fresh_obs.tool_call_hash,
                    "detail": outcome.detail,
                }, key=refusal_key)
            # FT-02: the dispatch intent is recorded in THIS transaction -
            # the one that authorizes the call. A refusal never gets here,
            # so a refused re-gate records no intent.
            intent = None
            if outcome.decision is ExecutionDecision.EXECUTE:
                intent = record_dispatch_intent(
                    proposal_id=str(proposal_id or item_id),
                    tenant=tenant,
                    item_id=item_id,
                    tool_name=tool_call.tool_name,
                    tool_call_hash=fresh_obs.tool_call_hash or "",
                    grant_jti="",
                    # Issue #82: the exact call material, so a separate
                    # worker can dispatch what THIS transaction authorized.
                    # The FULL wire model when available: the observation
                    # builder needs more than the three duck-typed fields
                    # (intent_ref, untrusted context, derivations).
                    tool_call_json=json.dumps(
                        tool_call.model_dump()
                        if hasattr(tool_call, "model_dump")
                        else {
                            "tool_name": tool_call.tool_name,
                            "arguments": tool_call.arguments,
                            "target_environment":
                                tool_call.target_environment,
                        },
                        sort_keys=True, default=str),
                    # Issue #418: the authorization's hard upper bound. The
                    # worker refuses rows past it, and a token minted at
                    # dispatch is capped at it — dispatch can never extend
                    # the original authorization's lifetime.
                    authorization_expires_at=(
                        datetime.now(UTC)
                        + timedelta(seconds=token_ttl_seconds)),
                    # Issue #420: the principal the authorization is FOR —
                    # the worker acts on their behalf and never substitutes
                    # its own identity for theirs.
                    requested_by=principal,
                )
    except ApprovalContextRefused as exc:
        # After the rollback, like the ACCEPT path's execution_context_refused
        # record: nothing in the queue changed, so nothing commits with it.
        chain.append(tenant, {
            "event": "execution_context_refused",
            "proposal_id": assessed_proposal_id or None,
            "actor": principal,
            "item_id": item_id,
            "detail": exc.reason,
            "mismatched": list(exc.mismatched),
        })
        raise
    except (KeyError, ValueError) as exc:
        raise conflict(str(exc)) from exc

    response: dict[str, Any] = {
        "proposal_id": proposal_id,
        "outcome": outcome.decision.value,
        "detail": outcome.detail,
        "toolspec": dict(toolspec_identity),
    }
    if outcome.decision is not ExecutionDecision.EXECUTE:
        # FT-01: every re-gate refusal is a declared move from AUTHORIZED.
        lifecycle_guard("AUTHORIZED", "regate_binding_or_freshness_refusal")
        response["audit"] = audit_ref(refusal_entry, key=refusal_key)
        return response

    if async_dispatch:
        # Issue #82: durable authorization is complete — the EXECUTE outcome
        # and the intent row committed together above. The dispatch half
        # (grant, PEP consumption, claim, governed dispatch, settlement)
        # belongs to the worker; answering now keeps the HTTP process out
        # of the side-effect window entirely.
        response["dispatch"] = "pending"
        if intent is not None:
            response["outbox_id"] = intent.outbox_id
        return response

    # FT-02: claim the intent before anything can take effect (exclusive).
    # A lost race means another worker holds this intent. Dispatching anyway
    # would execute the same side effect twice, which is the single failure the
    # outbox exists to prevent. The claim comes BEFORE the grant is minted and
    # consumed and before execution_authorized is appended, the order issue
    # #417 set for the worker path: the loser consumes and asserts nothing.
    # The re-gate only AUTHORIZED the call; EXECUTED is recorded separately
    # after the dispatcher reports what actually happened.
    now = datetime.now(UTC)

    def issue() -> tuple[Any, Any]:
        review_context = authorization_context(
            tenant=tenant, principal=principal, semantic=fresh_semantic,
            target_environment=tool_call.target_environment or "",
            policy_bundle_hash=_policy_bundle_hash(policy_bundle_hash),
            toolspec_hash=str(toolspec_identity["hash"]),
            task=task_identity_of(tool_call),
        )
        return PolicyDecisionToken.issue(
            action="accept",
            observation_hash=observation_binding(fresh_obs),
            # FT-01: the grant carries the canonical proposal identity; the
            # legacy composite only for pre-lifecycle items with no proposal.
            request_id=proposal_id or f"{tenant}:{item_id}",
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=token_ttl_seconds)).isoformat(),
            audience=token_audience,
            context=review_context,
        ), review_context

    admission_refusal_reason = ""
    if admitting and intent is not None:
        # WS1-M4 (M4.1c, owner decision): claim, evidence re-check and
        # consumption in one transaction, after the receipt and epoch checks.
        assert ws1_admission is not None and epochs_before is not None
        status, first, second = _admit_claim_atomically(
            ws1_admission, ws1, epochs_before, tenant=tenant, actor=principal,
            proposal_id=proposal_id, outbox_id=intent.outbox_id, worker_id=worker_id,
            outbox=outbox, issue=issue, binding=observation_binding(fresh_obs),
            gate=gate, transaction=transaction, active_connection=active_connection,
            transactional_append=transactional_append)
        if status == "lost" or (status == "refused" and not _claim_or_none(
                outbox, intent, worker_id=worker_id)):
            return _claim_lost_response(
                response, chain=chain, tenant=tenant, principal=principal,
                proposal_id=proposal_id, item_id=item_id,
                tool_call_hash=fresh_obs.tool_call_hash, grant_jti="",
                intent_sequence_no=None)
        if status == "admitted":
            token, gate_result = first, second
        else:
            # Nothing was spent. The grant is minted for the record only and
            # refused, so the row settles REFUSED through the usual path.
            admission_refusal_reason = str(first)
            token, _ = issue()
            gate_result = SimpleNamespace(allowed=False, reason=admission_refusal_reason)
    else:
        if not _claim_or_none(outbox, intent, worker_id=worker_id):
            return _claim_lost_response(
                response, chain=chain, tenant=tenant, principal=principal,
                proposal_id=proposal_id, item_id=item_id,
                tool_call_hash=fresh_obs.tool_call_hash, grant_jti="",
                intent_sequence_no=None)
        token, review_context = issue()
        # PEP consumption happens HERE: the grant is consumed atomically the
        # moment it is honoured - a re-presented token can never execute twice.
        gate_result = gate.check(
            token, observation_binding(fresh_obs), consume=True, context=review_context)
    response["execution_grant"] = token.to_dict()
    response["pep"] = {"allowed": gate_result.allowed,
                       "reason": gate_result.reason}

    # Resolved HERE, before authorization, so this value is the view the PDP
    # decided against. The closure record re-reads it after dispatch rather
    # than reusing this one: the join exists to detect the two disagreeing,
    # and copying the admission value forward would make every join succeed
    # by construction and prove nothing.
    #
    # None when the caller wired no provider (library and research use); the
    # key is then absent rather than an empty declaration, the same
    # distinction POST_V2_AUDIT_KEYS makes on the envelope.
    coverage = policy_coverage() if policy_coverage is not None else None

    # Durable INTENT record BEFORE the external side effect.
    intent_entry = chain.append(tenant, {
        "event": "execution_authorized",
        "proposal_id": proposal_id,
        "actor": principal,
        **({"acting_for": acting_for} if acting_for else {}),
        "item_id": item_id,
        "tool_call_hash": fresh_obs.tool_call_hash,
        "grant_jti": token.jti,
        "pep_allowed": gate_result.allowed,
        **({"execution_context_hash": fresh_obs.execution_context_hash,
            "observation_binding_hash": observation_binding(fresh_obs)}
           if fresh_obs.execution_context_hash else {}),
        "tool_contract_bundle_hash": fresh_semantic["tool_contract_bundle_hash"],
        "intent_authority_hash": fresh_semantic["intent_authority_hash"],
        # The trust base as THIS decision resolved it, per component, inside
        # the record the chain hashes. The closure record below carries the
        # same shape as it stood at dispatch, so "the authorization was
        # evaluated against the trust base in force at the enforcement point"
        # stops being an assumption and becomes a join between two entries.
        # A composite alone can say the views differed and never which
        # component, which is why this is not policy_bundle_hash again.
        "policy_components": coverage,
    })

    tool_execution = dispatch_under_lease(
        tenant=tenant,
        principal=principal,
        tool_call=tool_call,
        semantic=fresh_semantic,
        now=now,
        gate_allowed=gate_result.allowed,
        toolspec=toolspec_identity,
        proposal_id=str(proposal_id or item_id),
        grant_jti=token.jti,
        **_task_kwargs(tool_call),
        **_flow_kwargs(fresh_obs),
    )

    if admission_refusal_reason and not tool_execution.get("executed"):
        tool_execution["refusal_reason"] = admission_refusal_reason
    # FT-02: settle with what actually happened - derived, never assumed.
    #
    # The outcome is classified structurally. This used to match
    # refusal_reason == "tool_failed_nonce_burned" and settle FAILED, which
    # asserted "no effect occurred" on evidence that only showed the call
    # raised. A dispatch that began and then failed is UNKNOWN until something
    # proves otherwise (NEGATIVE_RESULTS section 48).
    outcome = classify_outcome(tool_execution)
    settled_before: Any = None
    if intent is not None:
        reason = tool_execution.get("refusal_reason")
        # Issue #416: the projection payload commits WITH the terminal
        # state, so a crash after this line strands nothing unrecoverable.
        settled_row, already = _settle_reported(
            outbox, intent.outbox_id, _OUTBOX_STATE[outcome], detail=reason,
            projection_json=_projection_payload(
                proposal_id=proposal_id, item_id=item_id, actor=principal,
                tool_call_hash=fresh_obs.tool_call_hash or "",
                grant_jti=token.jti, outcome=outcome,
                tool_execution=tool_execution,
                intent_sequence_no=intent_entry.sequence_no,
            ))
        if already:
            settled_before = settled_row

    # Persist the REAL outcome as the item's terminal state.
    with transaction(tenant) as q:
        q.record_execution_outcome(
            item_id,
            outcome=outcome,
            reason=tool_execution.get("refusal_reason"),
        )

    result_record: dict[str, Any] = {
        "event": "execution_result",
        "proposal_id": proposal_id,
        "actor": principal,
        "item_id": item_id,
        "tool_call_hash": fresh_obs.tool_call_hash,
        "grant_jti": token.jti,
        "intent_sequence_no": intent_entry.sequence_no,
        "tool_executed": tool_execution["executed"],
        # Whether the outcome is unknown, not merely unsuccessful. An effect
        # receipt may resolve an UNKNOWN dispatch -- a lost response does not
        # mean nothing happened -- so the chain has to carry the distinction.
        "state_unknown": bool(tool_execution.get("state_unknown")),
        # Re-read AFTER dispatch, not carried from above: the point of the
        # join is that these two can disagree. Copying the admission value
        # here would make every join succeed by construction and prove
        # nothing.
        "policy_components": (
            policy_coverage() if policy_coverage is not None else None
        ),
    }
    # The chain records the result's identity, never the result body.
    envelope_meta = tool_execution.get("result_envelope")
    if envelope_meta:
        result_record["result_sha256"] = envelope_meta["sha256"]
        result_record["result_size_bytes"] = envelope_meta["size_bytes"]
        result_record["result_truncated"] = envelope_meta["truncated"]
    if tool_execution.get("refusal_reason"):
        result_record["tool_refusal_reason"] = tool_execution["refusal_reason"]
    result_record.update(_nested_effects_fields(tool_execution))
    if settled_before is not None:
        _mark_reported_after_terminal(result_record, settled_before)
    # Idempotent by outbox id (issue #416): the in-line write claims the
    # same key the projector would replay under, so the record can land at
    # most once regardless of who finishes it.
    entry: Any = (chain.append_once(
        tenant, f"execution-result:{intent.outbox_id}", result_record)
        if intent is not None else chain.append(tenant, result_record))
    if intent is not None:
        outbox().mark_projected(intent.outbox_id)

    response["tool_execution"] = tool_execution
    if entry is not None:
        response["audit"] = {
            "sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash,
        }
    return response


def _nested_effects_fields(tool_execution: dict[str, Any]) -> dict[str, Any]:
    """The NTA-2 nested-effect summary an execution_result carries, when the
    dispatch reported one. Absent for dispatches that never reached the
    dispatcher, which report no nested effects because none could occur."""
    nested = tool_execution.get("nested_effects")
    fields = {"nested_effects": dict(nested)} if nested else {}
    for name in ("execution_context_hash", "execution_id", "dispatch_check"):
        if name in tool_execution:
            fields[name] = tool_execution[name]
    return fields


def _projection_payload(
    *,
    proposal_id: Any,
    item_id: str,
    actor: str,
    tool_call_hash: str,
    grant_jti: str,
    outcome: DispatchOutcome,
    tool_execution: dict[str, Any],
    intent_sequence_no: int | None,
    executed_by: str | None = None,
) -> str:
    """The complete downstream-projection payload, persisted ATOMICALLY
    with terminal settlement (issue #416 / RMR-CR-001): everything needed
    to rebuild the review-queue outcome and the execution_result chain
    record if the process dies right after settle()."""
    payload: dict[str, Any] = {
        "proposal_id": proposal_id,
        "item_id": item_id,
        "actor": actor,
        "tool_call_hash": tool_call_hash,
        "grant_jti": grant_jti,
        "outcome": outcome.value,
        "tool_executed": bool(tool_execution.get("executed")),
        "state_unknown": bool(tool_execution.get("state_unknown")),
        "refusal_reason": tool_execution.get("refusal_reason"),
        "intent_sequence_no": intent_sequence_no,
        **_nested_effects_fields(tool_execution),
    }
    if executed_by:
        payload["executed_by"] = executed_by
    envelope_meta = tool_execution.get("result_envelope")
    if envelope_meta:
        payload["result_sha256"] = envelope_meta["sha256"]
        payload["result_size_bytes"] = envelope_meta["size_bytes"]
        payload["result_truncated"] = envelope_meta["truncated"]
    return json.dumps(payload, sort_keys=True)


def _result_record_from_projection(p: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "event": "execution_result",
        "proposal_id": p.get("proposal_id"),
        "actor": p.get("actor"),
        "item_id": p.get("item_id"),
        "tool_call_hash": p.get("tool_call_hash"),
        "grant_jti": p.get("grant_jti"),
        "tool_executed": p.get("tool_executed"),
        "state_unknown": p.get("state_unknown"),
    }
    if p.get("executed_by"):
        record["executed_by"] = p["executed_by"]
    if p.get("intent_sequence_no") is not None:
        record["intent_sequence_no"] = p["intent_sequence_no"]
    if p.get("refusal_reason"):
        record["tool_refusal_reason"] = p["refusal_reason"]
    for key in ("execution_context_hash", "execution_id", "dispatch_check"):
        if key in p:
            record[key] = p[key]
    for key in ("result_sha256", "result_size_bytes", "result_truncated", "nested_effects"):
        if key in p:
            record[key] = p[key]
    return record


def project_terminal_intent(
    row: Any,
    *,
    tenant: str,
    transaction: Callable[[str], Any],
    chain: AuditChainPort,
    outbox: Callable[[], DispatchOutboxPort],
) -> dict[str, Any] | None:
    """Idempotently finish the downstream projection of one terminal row.

    Crash-matrix row 5 (issue #416): a row settled terminally whose
    review-queue outcome and/or execution_result record never landed. The
    persisted projection payload is replayed:

    * the queue outcome is re-applied; an item that already carries a
      terminal outcome (or no longer exists) is treated as done — the
      replay must converge, never fight the first write;
    * the chain record is appended via ``append_once`` keyed on the
      outbox id, so a projection can land at most once no matter how many
      sweeps run;
    * only then is the row marked projected.

    Terminal rows WITHOUT a payload (pre-#416 rows) are marked projected
    with nothing to replay — their downstream state is whatever the
    original process managed, and inventing records for them would be
    fabrication, not recovery.
    """
    if not row.is_terminal or row.projected_at is not None:
        return None
    if not row.projection_json:
        outbox().mark_projected(row.outbox_id)
        return {"outbox_id": row.outbox_id, "replayed": False,
                "reason": "no_projection_payload"}
    p = json.loads(row.projection_json)
    queue_replayed = False
    try:
        with transaction(tenant) as q:
            q.record_execution_outcome(
                p["item_id"],
                outcome=DispatchOutcome(p["outcome"]),
                reason=p.get("refusal_reason"),
            )
        queue_replayed = True
    except (KeyError, ValueError):
        # Already recorded, or the item is gone: converged either way.
        pass
    record = _result_record_from_projection(p)
    record["projection_replayed"] = True
    entry = chain.append_once(
        tenant, f"execution-result:{row.outbox_id}", record)
    outbox().mark_projected(row.outbox_id)
    return {
        "outbox_id": row.outbox_id,
        "replayed": True,
        "queue_outcome_written": queue_replayed,
        "chain_record_written": entry is not None,
    }


#: Worker refusal: the spec in force at dispatch is not the one the durable
#: authorization was granted under (published in schemas/tool_spec_v1.yaml).
TOOLSPEC_CHANGED_AT_DISPATCH = (
    "toolspec_changed_between_authorization_and_dispatch")
#: Worker refusal: the fresh observation, re-decided at dispatch, no longer
#: supports the approval the 202 honoured.
FRESH_REGATE_REFUSED = "fresh_regate_refused"


def _toolspec_at_dispatch(
    tool_call: Any,
    *,
    resolve_toolspec: Callable[[str, dict[str, Any], str], dict[str, Any]],
    authorized_hash: str,
) -> tuple[str | None, dict[str, Any] | None, dict[str, Any]]:
    """``(refusal, identity, detail)`` for the spec in force at dispatch.

    Fail closed: an empty authorized hash under an enforced bundle is a
    refusal, not a pass. "No bundle then, no bundle now" is the only case
    with nothing to compare, and its identity says ``enforced=False``.
    """
    try:
        identity = resolve_toolspec(
            tool_call.tool_name, tool_call.arguments,
            tool_call.target_environment)
    except ToolSpecRefused as exc:
        return exc.reason_code, None, {}
    identity.pop("argument_roles", None)
    current = str(identity.get("hash") or "")
    if not identity.get("enforced") and not authorized_hash:
        return None, identity, {}
    if (not current or not authorized_hash
            or not hmac.compare_digest(current, authorized_hash)):
        return TOOLSPEC_CHANGED_AT_DISPATCH, None, {
            "authorized_toolspec_hash": authorized_hash,
            "current_toolspec_hash": current,
            "current_toolspec_version": identity.get("version"),
            "current_toolspec_enforced": bool(identity.get("enforced")),
        }
    return None, identity, {}


def dispatch_pending_intent(
    row: Any,
    *,
    tenant: str,
    principal: str,
    transaction: Callable[[str], Any],
    chain: AuditChainPort,
    gate: EnforcementGatePort,
    outbox: Callable[[], DispatchOutboxPort],
    worker_id: str,
    build_observation: Callable[[Any, str], tuple[Any, dict[str, Any]]],
    dispatch_under_lease: Callable[..., dict[str, Any]],
    token_audience: str,
    token_ttl_seconds: int,
    resolve_toolspec: Callable[[str, dict[str, Any], str], dict[str, Any]] | None = None,
    policy_coverage: Callable[[], dict[str, Any]] | None = None,
    policy_bundle_hash: Callable[[], str] | None = None,
    rebuild_call: Callable[[dict[str, Any]], Any] | None = None,
    assessed_record: Callable[[str, str], tuple[str, str]] | None = None,
    require_execution_context: bool = False,
    approval_policy: Callable[[Any], str] | None = None,
    ws1_gate: Ws1GatePort | None = None,
    ws1_capability: Callable[[Any, str], Any] | None = None,
    ws1_admission: Ws1AdmissionPort | None = None,
    active_connection: Callable[[], Any] | None = None,
    transactional_append: Callable[..., Any] | None = None,
) -> dict[str, Any] | None:
    """Dispatch one DISPATCH_PENDING intent from a separate worker (issue #82).

    The dispatch half of :func:`execute_approved_item`'s async mode, with
    the SAME record shapes. Order (issue #417): the EXCLUSIVE claim comes
    first — a worker that loses the race consumes and asserts nothing —
    then the grant is minted and PEP-consumed at the moment of honouring,
    the ``execution_authorized`` chain entry lands, dispatch goes through
    the governed dispatcher, and the row settles with what ACTUALLY
    happened before the ``execution_result`` entry.

    Returns ``None`` for rows this worker must not touch: not
    DISPATCH_PENDING (another worker, or already settled), no persisted
    payload (pre-#82 rows and synchronous-path rows — the reconciler owns
    their fate, this worker cannot reconstruct the call), or a lost claim
    race. A payload that no longer hashes to the authorization's binding
    is refused and settled REFUSED — a worker must never dispatch a call
    other than the one that was authorized. A row that cannot name the
    principal it was granted for is refused as ``requester_identity_missing``;
    the worker identity passed as ``principal`` is never adopted as that actor.

    Two things can change between the 202 and the worker waking up, and
    both are decided again before anything is minted, consumed or claimed:

    * the ToolSpec. With ``resolve_toolspec`` wired, the spec in force now
      must have the hash the assessment recorded in the chain (read through
      ``assessed_record``), or the row refuses as
      ``toolspec_changed_between_authorization_and_dispatch``. A row whose
      item has no recorded hash refuses the same way when a bundle is now
      enforced: it cannot show which spec it was authorized under. Only
      "no bundle then, no bundle now" passes unchecked, the research path
      reported as ``enforced=False``. A spec the bundle itself refuses now
      settles under that published reason code.
    * the hard guards. The fresh observation is re-decided by the review
      queue's own engine (``ReviewQueue.regate_authorized``), under the
      same equal-or-safer rule the 202 applied. Anything else refuses as
      ``fresh_regate_refused``.

    Under WS1 enforce (issue #953) the WS1 gate must reach ACCEPT again with
    fresh lookups too, or the row refuses as ``ws1_regate_refused``.
    """
    _refuse_minting_on_a_redeemer()
    if row.state is not OutboxState.DISPATCH_PENDING:
        return None
    if not row.tool_call_json:
        return None
    refusal: str | None = None
    # Issue #418 (RMR-CR-003): freshness is bounded by the PERSISTED
    # authorization expiry, checked before anything else. A row without
    # one cannot prove its freshness and is refused — an old decision
    # must never gain a new lifetime by being picked up late.
    if row.authorization_expires_at is None:
        refusal = "authorization_expiry_missing"
    elif datetime.now(UTC) > row.authorization_expires_at:
        refusal = "authorization_expired"
    elif not (row.requested_by or "").strip():
        # The worker process identity is not an authorization. A legacy or
        # hand-built row with no requester would otherwise be honoured as
        # principal (the worker), which is the substitution issue #420 forbids.
        refusal = "requester_identity_missing"
    tool_call: Any = None
    if refusal is None:
        try:
            payload = json.loads(row.tool_call_json)
            if rebuild_call is not None:
                # The binder rebuilds the typed wire model — the observation
                # builder needs the full request, not the duck-typed triple.
                tool_call = rebuild_call(payload)
            else:
                tool_call = SimpleNamespace(
                    tool_name=row.tool_name,
                    arguments=payload.get("arguments", {}),
                    target_environment=payload.get("target_environment", ""),
                )
        except Exception:
            # Material that no longer parses or validates is refused and
            # settled — a broken row must never crash the worker loop, and
            # must never be dispatched on a guess.
            refusal = "payload_invalid"
    fresh_obs = fresh_semantic = None
    if refusal is None:
        fresh_obs, fresh_semantic = build_observation(tool_call, tenant)
        if (fresh_obs.tool_call_hash or "") != row.tool_call_hash:
            refusal = "payload_hash_mismatch"
    # The spec the authorization was granted under, compared with the spec in
    # force now. Read from the chain BEFORE any review-state transaction
    # opens: reading it inside one deadlocks SQLite (see assessed_record).
    toolspec_identity: dict[str, Any] | None = None
    refusal_detail: dict[str, Any] = {}
    if refusal is None and resolve_toolspec is not None:
        authorized_hash = (
            assessed_record(tenant, row.item_id)[0]
            if assessed_record is not None else "")
        refusal, toolspec_identity, refusal_detail = _toolspec_at_dispatch(
            tool_call, resolve_toolspec=resolve_toolspec,
            authorized_hash=authorized_hash)
    actor = (row.requested_by or "").strip()
    proposal_id = row.proposal_id
    # Outside any transaction, like historical_context below: a delegate the
    # proposal named is recorded with the proposer it acts for.
    acting_for = _acting_for(
        _assessed_payload(chain, tenant, str(proposal_id or "")), actor)
    if refusal is None:
        try:
            assert fresh_obs is not None and fresh_semantic is not None
            context = historical_context(
                chain, tenant, proposal_id, required=require_execution_context)
            fresh_obs = _bind_execution_context(
                fresh_obs, fresh_semantic, context, proposal_id=proposal_id,
                tenant=tenant, principal=actor)
            if context is not None or require_execution_context:
                with transaction(tenant) as q:
                    approved_hash = q.item(row.item_id).observation.execution_context_hash
                if approved_hash != fresh_obs.execution_context_hash:
                    raise ExecutionContextRefused("execution_context_mismatch")
        except ExecutionContextRefused as exc:
            refusal = exc.reason
    # The fresh observation used to be hashed and nothing more, so a hard
    # guard that fired after the 202 was wrapped in a new ACCEPT. Re-decide it
    # with the engine the 202 used, before the claim and before any grant.
    if refusal is None:
        assert fresh_obs is not None
        regate: Any = None
        try:
            with transaction(tenant) as q:
                regate = q.regate_authorized(
                    row.item_id, fresh_obs,
                    approval_policy_hash=(approval_policy(fresh_obs)
                                          if approval_policy is not None
                                          else None))
        except (KeyError, ValueError):
            # No AUTHORIZED item behind the row: nothing to honour.
            regate = None
        if regate is None or regate.decision is not ExecutionDecision.EXECUTE:
            refusal = FRESH_REGATE_REFUSED
            refusal_detail = {
                "regate_decision": (regate.decision.value
                                    if regate is not None else None),
                "fresh_action": (regate.fresh_action.value
                                 if regate is not None
                                 and regate.fresh_action is not None
                                 else None),
            }
    admitting = (ws1_admission is not None and ws1_gate is not None
                 and ws1_gate.mode == "enforce")
    epochs_before: dict[str, int] | None = None
    ws1 = None
    if refusal is None and admitting:
        assert ws1_admission is not None
        epochs_before, why = ws1_admission.before_regate(
            ws1_gate, tenant=tenant, tool_name=row.tool_name)
        if epochs_before is None:
            refusal, refusal_detail = why, {"admission": why}
    if refusal is None and fresh_semantic is not None:
        proposer = acting_for or actor
        ws1 = ws1_regate(
            ws1_gate, chain=chain, tenant=tenant, proposal_id=str(proposal_id or ""),
            proposer=proposer, tool_call=tool_call, semantic=fresh_semantic,
            observation=fresh_obs,
            toolspec_hash=str((toolspec_identity or {}).get("hash", "")),
            policy_bundle_hash=_policy_bundle_hash(policy_bundle_hash),
            capability=(ws1_capability(tool_call, proposer)
                        if ws1_capability is not None else None),
            review_attestation=(stored_approval(transaction, tenant, row.item_id)
                                if ws1_gate is not None else None))
        ws1_binding_matches = _ws1_approval_binding_matches(
            chain, tenant, str(proposal_id or ""), ws1)
        if not ws1_binding_matches or (
                ws1 is not None and ws1.final_action is not DecisionAction.ACCEPT):
            refusal = WS1_REGATE_REFUSED
            refusal_detail = {"ws1": ws1.audit_block() if ws1 is not None else {"mode": "off_or_shadow"},
                              "ws1_binding_matches": ws1_binding_matches}
    now = datetime.now(UTC)

    def issue() -> tuple[Any, Any]:
        # Issue #418: the freshly minted token is CAPPED at the persisted
        # authorization expiry; honouring late never extends the original
        # authorization's lifetime.
        assert fresh_obs is not None and fresh_semantic is not None
        token_expiry = now + timedelta(seconds=token_ttl_seconds)
        if row.authorization_expires_at is not None:
            token_expiry = min(token_expiry, row.authorization_expires_at)
        honour_context = authorization_context(
            tenant=tenant, principal=actor, semantic=fresh_semantic,
            target_environment=getattr(tool_call, "target_environment", "") or "",
            policy_bundle_hash=_policy_bundle_hash(policy_bundle_hash),
            toolspec_hash=str((toolspec_identity or {}).get("hash", "")),
            task=task_identity_of(tool_call),
        )
        return PolicyDecisionToken.issue(
            action="accept",
            observation_hash=observation_binding(fresh_obs),
            request_id=proposal_id or f"{tenant}:{row.item_id}",
            issued_at=now.isoformat(),
            expires_at=token_expiry.isoformat(),
            audience=token_audience,
            context=honour_context,
        ), honour_context

    # WS1-M4 (M4.1c): claim, evidence re-check and consumption in one
    # transaction. A refusal leaves the row pending, and the refusal path
    # below claims and settles it as refused with nothing spent.
    admitted: tuple[Any, Any] | None = None
    if refusal is None and admitting:
        assert ws1_admission is not None and epochs_before is not None
        assert fresh_obs is not None
        status, first, second = _admit_claim_atomically(
            ws1_admission, ws1, epochs_before, tenant=tenant, actor=actor,
            proposal_id=proposal_id, outbox_id=row.outbox_id, worker_id=worker_id,
            outbox=outbox, issue=issue, binding=observation_binding(fresh_obs),
            gate=gate, transaction=transaction, active_connection=active_connection,
            transactional_append=transactional_append)
        if status == "lost":
            return None
        if status == "refused":
            refusal, refusal_detail = str(first), {"admission": first}
        else:
            admitted = (first, second)
    # Issue #420 (RMR-CR-005): every record carries the principal the
    # authorization was granted FOR; the worker's own identity is reported
    # separately as executed_by and never substituted for the requester's.
    # ``principal`` remains the worker binder's process identity and is not
    # an actor fallback.
    if refusal is not None:
        try:
            if outbox().claim(row.outbox_id, worker_id=worker_id) is None:
                return None
        except ValueError:
            # Another worker settled the row since this one listed it; the
            # outcome is that worker's, and this one records nothing.
            return None
        refusal_execution = {"executed": False, "dispatch_began": False,
                             "state_unknown": False,
                             "refusal_reason": refusal}
        outbox().settle(
            row.outbox_id, OutboxState.REFUSED, detail=refusal,
            projection_json=_projection_payload(
                proposal_id=proposal_id, item_id=row.item_id,
                actor=actor, tool_call_hash=row.tool_call_hash,
                grant_jti="", outcome=DispatchOutcome.REFUSED,
                tool_execution=refusal_execution,
                intent_sequence_no=None, executed_by=worker_id,
            ))
        # Issue #421 (RMR-CR-006): the review item takes the SAME terminal
        # outcome as the outbox — a refused dispatch must never leave the
        # item AUTHORIZED forever. An item that is gone or no longer
        # AUTHORIZED has converged already; the refusal still settles.
        try:
            with transaction(tenant) as q:
                q.record_execution_outcome(
                    row.item_id, outcome=DispatchOutcome.REFUSED,
                    reason=refusal)
        except (KeyError, ValueError):
            pass
        refusal_record: dict[str, Any] = {
            "event": "execution_result",
            "proposal_id": proposal_id,
            "actor": actor,
            "executed_by": worker_id,
            "item_id": row.item_id,
            "tool_call_hash": row.tool_call_hash,
            "grant_jti": "",
            "tool_executed": False,
            "state_unknown": False,
            "tool_refusal_reason": refusal,
        }
        if refusal_detail:
            refusal_record["refusal_detail"] = refusal_detail
        entry = chain.append_once(
            tenant, f"execution-result:{row.outbox_id}", refusal_record)
        outbox().mark_projected(row.outbox_id)
        result: dict[str, Any] = {
            "proposal_id": proposal_id,
            "tool_execution": refusal_execution,
        }
        if entry is not None:
            result["audit"] = {"sequence_no": entry.sequence_no,
                               "entry_hash": entry.entry_hash}
        return result

    # Past the refusal gate both are populated; the split assignment above
    # is only for the refusal path. Narrowing for the type checker.
    assert fresh_obs is not None and fresh_semantic is not None

    if admitted is not None:
        token, gate_result = admitted
    else:
        # Issue #417 (RMR-CR-002): the EXCLUSIVE claim comes FIRST. Minting
        # and PEP-consuming a grant, and appending execution_authorized,
        # before the claim meant a lost race left a consumed grant and an
        # authorization event for a dispatch that never happened — evidence
        # claiming two honourings where there was one. The loser now walks
        # away having consumed and asserted nothing.
        if outbox().claim(row.outbox_id, worker_id=worker_id) is None:
            return None
        token, honour_context = issue()
        gate_result = gate.check(
            token, observation_binding(fresh_obs), consume=True, context=honour_context)
    coverage = policy_coverage() if policy_coverage is not None else None
    intent_entry = chain.append(tenant, {
        "event": "execution_authorized",
        "proposal_id": proposal_id,
        "actor": actor,
        **({"acting_for": acting_for} if acting_for else {}),
        "executed_by": worker_id,
        "item_id": row.item_id,
        "tool_call_hash": fresh_obs.tool_call_hash,
        "grant_jti": token.jti,
        "pep_allowed": gate_result.allowed,
        **({"execution_context_hash": fresh_obs.execution_context_hash,
            "observation_binding_hash": observation_binding(fresh_obs)}
           if fresh_obs.execution_context_hash else {}),
        "tool_contract_bundle_hash": fresh_semantic["tool_contract_bundle_hash"],
        "intent_authority_hash": fresh_semantic["intent_authority_hash"],
        "policy_components": coverage,
    })

    tool_execution = dispatch_under_lease(
        tenant=tenant,
        principal=actor,
        tool_call=tool_call,
        semantic=fresh_semantic,
        now=now,
        gate_allowed=gate_result.allowed,
        toolspec=toolspec_identity,
        proposal_id=str(proposal_id or row.item_id),
        grant_jti=token.jti,
        **_task_kwargs(tool_call),
        **_flow_kwargs(fresh_obs),
    )

    outcome = classify_outcome(tool_execution)
    # Issue #416: projection payload commits WITH the terminal state.
    settled_row, already = _settle_reported(
        outbox, row.outbox_id, _OUTBOX_STATE[outcome],
        detail=tool_execution.get("refusal_reason"),
        projection_json=_projection_payload(
            proposal_id=proposal_id, item_id=row.item_id, actor=actor,
            tool_call_hash=fresh_obs.tool_call_hash or "",
            grant_jti=token.jti, outcome=outcome,
            tool_execution=tool_execution,
            intent_sequence_no=intent_entry.sequence_no,
            executed_by=worker_id,
        ))
    with transaction(tenant) as q:
        q.record_execution_outcome(
            row.item_id,
            outcome=outcome,
            reason=tool_execution.get("refusal_reason"),
        )

    result_record: dict[str, Any] = {
        "event": "execution_result",
        "proposal_id": proposal_id,
        "actor": actor,
        "executed_by": worker_id,
        "item_id": row.item_id,
        "tool_call_hash": fresh_obs.tool_call_hash,
        "grant_jti": token.jti,
        "intent_sequence_no": intent_entry.sequence_no,
        "tool_executed": tool_execution["executed"],
        "state_unknown": bool(tool_execution.get("state_unknown")),
        "policy_components": (
            policy_coverage() if policy_coverage is not None else None
        ),
    }
    envelope_meta = tool_execution.get("result_envelope")
    if envelope_meta:
        result_record["result_sha256"] = envelope_meta["sha256"]
        result_record["result_size_bytes"] = envelope_meta["size_bytes"]
        result_record["result_truncated"] = envelope_meta["truncated"]
    if tool_execution.get("refusal_reason"):
        result_record["tool_refusal_reason"] = tool_execution["refusal_reason"]
    result_record.update(_nested_effects_fields(tool_execution))
    if already:
        _mark_reported_after_terminal(result_record, settled_row)
    # Idempotent by outbox id (issue #416): the same key the projector
    # replays under, so the record lands at most once.
    entry = chain.append_once(
        tenant, f"execution-result:{row.outbox_id}", result_record)
    outbox().mark_projected(row.outbox_id)

    result = {
        "proposal_id": proposal_id,
        "tool_execution": tool_execution,
    }
    if entry is not None:
        result["audit"] = {"sequence_no": entry.sequence_no,
                           "entry_hash": entry.entry_hash}
    return result


class TokenRefused(RemoraError):
    """The presented ACCEPT token does not authorize this call (route maps
    to 409). ``refusal`` is the bounded metric label."""

    code = "token_refused"
    category = "execution"

    def __init__(self, detail: str, refusal: str) -> None:
        super().__init__(detail)
        self.refusal = refusal


#: Wire detail when a WS1 re-gate refuses a dispatch path (issue #953).
WS1_REGATE_REFUSED = "ws1_regate_refused"


def _never_raised(before: DecisionReport, after: DecisionReport) -> DecisionReport:
    """``after`` when it keeps ``before``'s action, refuses outright, or sends
    an ACCEPT or VERIFY to review. A gate port returning anything else (a
    raised decision, or an ESCALATE out of a refusal) is ignored rather than
    trusted."""
    if after.action in (before.action, DecisionAction.ABSTAIN):
        return after
    # ESCALATE lowers ACCEPT or VERIFY onto a review route; it never turns
    # a refusal into one.
    if after.action is DecisionAction.ESCALATE and before.action in (
            DecisionAction.ACCEPT, DecisionAction.VERIFY):
        return after
    return before


def _ws1_task_id(task: TaskIdentity | None) -> str | None:
    """The task a WS1 budget is charged to: the call's own task identity."""
    return f"{task.context_id}/{task.task_id}" if task is not None else None


def _ws1_regate_base(observation: Any) -> DecisionReport:
    """The engine part of a re-gate on a dispatch path, already decided and
    bound by the grant or the approval: the WS1 gate composes against ACCEPT
    and must reach ACCEPT on its own preconditions."""
    return DecisionReport(
        action=DecisionAction.ACCEPT, reasons=(), risk_estimate=None, confidence=None,
        coverage_policy="ws1_regate", evidence_required=False,
        human_review_required=False, audit_root=None,
        explanation="WS1 re-gate before dispatch", raw_observation=observation)


def ws1_regate(
    gate: Ws1GatePort | None,
    *,
    chain: AuditChainPort,
    tenant: str,
    proposal_id: str,
    proposer: str,
    tool_call: Any,
    semantic: dict[str, Any],
    observation: Any,
    toolspec_hash: str,
    policy_bundle_hash: str,
    capability: Any,
    review_attestation: tuple[str, str] | None = None,
) -> Ws1OutcomePort | None:
    """A fresh WS1 evaluation before a dispatch path consumes anything, or
    None when WS1 does not enforce. Fresh lookups, so evidence that expired,
    was revoked or now refutes stops the call (WS1-09). A monitor veto the
    assessment recorded stays a veto (A13). *review_attestation* is
    ``(approver, approver_role)`` of the approval the queue stored, on the
    review path only: it closes a REVIEW precondition of exactly that role
    and nothing else."""
    if gate is None or gate.mode != "enforce":
        return None
    assessed = _assessed_payload(chain, tenant, proposal_id) or {}
    prior = assessed.get("ws1") or {}
    return gate.evaluate(
        proposal_id=proposal_id, tenant=tenant, principal=proposer,
        tool_name=tool_call.tool_name, arguments=tool_call.arguments,
        intent_authority_hash=str(semantic.get("intent_authority_hash") or ""),
        policy_bundle_hash=policy_bundle_hash, toolspec_hash=toolspec_hash,
        capability=capability, flow_digest=getattr(observation, "flow_digest", None),
        flow_epoch=getattr(observation, "flow_epoch", None), attempt_family_id=None,
        base=_ws1_regate_base(observation),
        veto_on_record=bool(prior.get("monitor_veto")),
        review_attestation=review_attestation,
        task_id=_ws1_task_id(task_identity_of(tool_call)))



class _AdmissionRefusal(Exception):
    """Raised inside the admission transaction so it rolls back; never escapes."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _refuse_admission(chain: AuditChainPort, *, tenant: str, proposal_id: Any,
                      principal: str, grant_jti: str, reason: str) -> NoReturn:
    """Record an admission refusal after the rollback, and refuse the call.

    Nothing was spent and no intent exists, so the event is appended on its
    own, like the ACCEPT path's other pre-consumption refusals."""
    chain.append(tenant, {
        "event": "execution_admission_refused",
        "proposal_id": proposal_id,
        "actor": principal,
        "grant_jti": grant_jti,
        "detail": reason,
    })
    raise TokenRefused(f"WS1-M4 admission refused: {reason}", reason)


def _admit_atomically(
    admission: Ws1AdmissionPort, ws1: Any, epochs_before: dict[str, int], *,
    tenant: str, principal: str, proposal_id: Any, token: Any, obs: Any,
    tool_call: Any, context: Any, chain: AuditChainPort, gate: EnforcementGatePort,
    transaction: Callable[[str], Any] | None,
    active_connection: Callable[[], Any] | None,
    transactional_append: Callable[..., Any] | None,
    record_dispatch_intent: Callable[..., Any],
) -> tuple[Any, Any]:
    """INV-M4-01 on the ACCEPT path: one transaction or none (M4.1c).

    Order inside, as the topology ADR fixes it: database time and epochs
    under lock, receipt checks, grant consumption on the same connection,
    dispatch intent, admission event; then commit. Any refusal raises inside
    so the transaction rolls back, and the grant stays unspent. A backend
    that cannot open the transaction refuses: nothing is dispatched on a
    guess (M4-T13).
    """
    if transaction is None or active_connection is None or transactional_append is None:
        _refuse_admission(chain, tenant=tenant, proposal_id=proposal_id,
                          principal=principal, grant_jti=token.jti,
                          reason="admission_backend_unavailable")
    assert transaction is not None and active_connection is not None
    assert transactional_append is not None
    try:
        with transaction(tenant):
            connection = active_connection()
            reason, facts = admission.check(
                connection, tenant=tenant, outcome=ws1, epochs_before=epochs_before)
            if reason is not None:
                raise _AdmissionRefusal(reason)
            gate_result = gate.check(token, observation_binding(obs), consume=True,
                                     context=context, connection=connection)
            if not gate_result.allowed:
                # Nothing was written; the caller records the grant refusal
                # as it does without admission.
                return gate_result, None
            intent = record_dispatch_intent(
                proposal_id=str(proposal_id or token.jti), tenant=tenant,
                item_id=f"accept:{token.jti}", tool_name=tool_call.tool_name,
                tool_call_hash=obs.tool_call_hash or "", grant_jti=token.jti)
            transactional_append(tenant, {
                "event": "execution_admitted",
                "proposal_id": proposal_id,
                "actor": principal,
                "grant_jti": token.jti,
                "ws1_binding_hash": ws1.binding_hash,
                **facts,
            }, key=f"execution_admitted:{token.jti}")
    except _AdmissionRefusal as exc:
        _refuse_admission(chain, tenant=tenant, proposal_id=proposal_id,
                          principal=principal, grant_jti=token.jti, reason=exc.reason)
    except TokenRefused:
        raise
    except Exception as exc:  # the backend failed; refuse, never dispatch on a guess
        _refuse_admission(chain, tenant=tenant, proposal_id=proposal_id,
                          principal=principal, grant_jti=token.jti,
                          reason=f"admission_backend_unavailable:{type(exc).__name__}")
    return gate_result, intent


def _admit_claim_atomically(
    admission: Ws1AdmissionPort, ws1: Any, epochs_before: dict[str, int], *,
    tenant: str, actor: str, proposal_id: Any, outbox_id: str, worker_id: str,
    outbox: Callable[[], DispatchOutboxPort], issue: Callable[[], tuple[Any, Any]],
    binding: str, gate: EnforcementGatePort, transaction: Callable[[str], Any],
    active_connection: Callable[[], Any] | None,
    transactional_append: Callable[..., Any] | None,
) -> tuple[str, Any, Any]:
    """INV-M4-01 on the review and worker paths: claim and consume in one transaction.

    The intent was recorded when the approval was honoured; this is the
    moment the grant is minted and spent (the topology ADR's owner decision:
    the review path consumes in the same admission transaction as the
    claim). Inside: receipt and epoch checks at database time, the exclusive
    claim on the same connection, the grant minted by ``issue()`` and
    consumed there, and the admission event; then commit.

    Returns ``("admitted", token, gate_result)``, ``("lost", None, None)``
    when another worker holds the claim, or ``("refused", reason, None)``.
    A refusal rolls the claim back, so the row stays DISPATCH_PENDING for
    the caller to settle as refused, and no grant was spent.
    """
    if active_connection is None or transactional_append is None:
        return "refused", "admission_backend_unavailable", None
    try:
        with transaction(tenant):
            connection = active_connection()
            reason, facts = admission.check(
                connection, tenant=tenant, outcome=ws1, epochs_before=epochs_before)
            if reason is not None:
                raise _AdmissionRefusal(reason)
            try:
                claimed = outbox().claim_enlisted(connection, outbox_id, worker_id=worker_id)
            except ValueError:
                # Another worker claimed and settled the row since this one
                # listed it: a lost race, not a backend failure.
                return "lost", None, None
            if claimed is None:
                return "lost", None, None
            token, context = issue()
            gate_result = gate.check(token, binding, consume=True, context=context,
                                     connection=connection)
            if not gate_result.allowed:
                raise _AdmissionRefusal(str(gate_result.reason))
            transactional_append(tenant, {
                "event": "execution_admitted",
                "proposal_id": proposal_id,
                "actor": actor,
                "executed_by": worker_id,
                "outbox_id": outbox_id,
                "grant_jti": token.jti,
                "ws1_binding_hash": ws1.binding_hash,
                **facts,
            }, key=f"execution_admitted:{token.jti}")
    except _AdmissionRefusal as exc:
        return "refused", exc.reason, None
    except Exception as exc:  # the backend failed; refuse, never dispatch on a guess
        return "refused", f"admission_backend_unavailable:{type(exc).__name__}", None
    return "admitted", token, gate_result


def _ws1_approval_binding_matches(chain: AuditChainPort, tenant: str,
                                  proposal_id: str, outcome: Ws1OutcomePort | None) -> bool:
    """An approval closes only the WS1 requirement set/configuration assessed.

    Direct ACCEPT tokens bind this through AuthorizationContext. Review and
    worker paths must compare the same binding before consuming an approval.
    """
    prior = (_assessed_payload(chain, tenant, proposal_id) or {}).get("ws1") or {}
    if outcome is None:
        return prior.get("mode") != "enforce"
    expected = prior.get("binding_hash")
    return (prior.get("mode") == "enforce" and isinstance(expected, str)
            and bool(expected) and hmac.compare_digest(expected, outcome.binding_hash))

def stored_approval(transaction: Callable[[str], Any], tenant: str,
                    item_id: str) -> tuple[str, str] | None:
    """``(approver, approver_role)`` of the item's stored approval, or None.

    Read in its own short transaction, before the execute transaction, like
    the other pre-checks; an unknown item or an approval without a recorded
    role gives None, which closes no REVIEW precondition."""
    try:
        with transaction(tenant) as q:
            approval = q.item(item_id).approval
    except (KeyError, LookupError):
        return None
    if approval is None or not approval.approver_role:
        return None
    return str(approval.approver), str(approval.approver_role)


def authorization_context(
    *,
    tenant: str,
    principal: str,
    semantic: dict[str, Any],
    target_environment: str,
    policy_bundle_hash: str,
    toolspec_hash: str,
    task: TaskIdentity | None = None,
    request_ref: RequestRef | None = None,
    delegated_executor: str = "",
    ws1_binding_hash: str = "",
) -> AuthorizationContext:
    """The conditions a decision is made under, in one place.

    Built identically at issuance and at redemption, because the whole point is
    that the two comparisons cannot drift. Three call sites constructing the
    same six fields by hand is how they would (RMR-001).

    Three of the six were read out of the semantic block, which never carries
    them: ``target_environment`` and ``policy_bundle_hash`` were therefore
    always the empty string, and ``toolspec_hash`` carried the tool-contract
    BUNDLE hash rather than the identity of the signed spec the call was
    decided against. A field bound to "" binds nothing, and the bundle hash
    moves for reasons that have nothing to do with this tool's spec. They are
    passed explicitly now, so a caller cannot leave one unbound by omission.
    The contract-bundle hash keeps its own place in the audit record.

    ``task`` (Q7.2) is the task the call is made under. It enters the hash
    only when present, so a request that names no task hashes as before, and
    a token issued under one task and redeemed under another is refused as
    ``context_mismatch`` before the grant is consumed.

    ``request_ref`` is the request the call arrived in
    (:mod:`remora.execution.request_ref`). It enters the hash only when
    present, by the same rule, so a grant issued for one request is refused,
    unspent, when its call is re-presented under another.

    ``delegated_executor`` is the delegate the proposal named, admitted at
    assess time (remora/governance/delegation.py). It enters the hash only
    when present, for the same reason, so a delegate cannot be added to or
    swapped in a grant or an approval after the fact.

    ``ws1_binding_hash`` is the WS1 binding (issue #953), present only under
    WS1 enforce. Redemption recomputes it from a fresh WS1 re-gate.
    """

    return AuthorizationContext(
        tenant=tenant,
        principal=principal,
        target_environment=target_environment,
        policy_bundle_hash=policy_bundle_hash,
        toolspec_hash=toolspec_hash,
        intent_authority_hash=str(semantic.get("intent_authority_hash", "")),
        context_id=task.context_id if task is not None else "",
        task_id=task.task_id if task is not None else "",
        execution_context_hash=str(semantic.get("execution_context_hash", "")),
        request_ref_hash=request_ref.digest() if request_ref is not None else "",
        delegated_executor=delegated_executor or "",
        ws1_binding_hash=ws1_binding_hash or "",
    )


def task_identity_of(tool_call: Any) -> TaskIdentity | None:
    """The task a proposal names, or None. Raises ValueError for one half.

    Read by attribute so the duck-typed call a worker rebuilds from the outbox
    is handled like the wire model; a call without the fields names no task.
    """
    return TaskIdentity.from_fields({
        "context_id": getattr(tool_call, "context_id", None) or None,
        "task_id": getattr(tool_call, "task_id", None) or None,
    })


def plan_binding_of(tool_call: Any) -> Any:
    """The plan a proposal carries (Q7.5), or None. Raises ValueError when
    the plan is malformed, so a bad plan is refused rather than dropped."""
    raw = getattr(tool_call, "plan", None)
    if raw is None:
        return None
    from remora.governance.plan_binding import PlanBinding

    data = raw.model_dump() if hasattr(raw, "model_dump") else raw
    return PlanBinding.from_dict(data)


def _flow_refusal(obs: Any) -> str | None:
    """Why the call's current flow verdict refuses it, or None.

    The same states the engine's flow rungs accept pass here: flow control
    off (no ``flow_status``), a tool outside the strict profile with no flow
    block (``not_declared``), and a clean evaluated verdict. An unknown
    context, a missing policy, an unavailable store or a violation refuses.
    """
    status = getattr(obs, "flow_status", None)
    if status is None or status == "not_declared":
        return None
    if status != "evaluated":
        return f"flow_{status}"
    if getattr(obs, "flow_confidentiality_violation", False):
        return "flow_confidentiality_violation"
    if getattr(obs, "flow_integrity_violation", False):
        return "flow_integrity_violation"
    return None


def _flow_kwargs(obs: Any) -> dict[str, Any]:
    """``flow_expected`` for a dispatch call: the epoch and digest the flow
    check had when this call was last decided (SDD v2 WP-04, AR-018).

    Omitted unless the flow check evaluated, so a dispatcher binding that
    predates the parameter keeps working where flow control is off.
    """
    if getattr(obs, "flow_status", None) != "evaluated" or not getattr(obs, "flow_digest", None):
        return {}
    return {"flow_expected": (int(obs.flow_epoch or 0), str(obs.flow_digest))}


def _task_kwargs(tool_call: Any) -> dict[str, Any]:
    """``task_identity`` and ``plan`` for a dispatch call, each omitted when
    the call carries none, so a dispatcher binding that predates the
    parameters keeps working."""
    out: dict[str, Any] = {}
    task = task_identity_of(tool_call)
    if task is not None:
        out["task_identity"] = task
    plan = plan_binding_of(tool_call)
    if plan is not None:
        out["plan"] = plan
    return out


def redeem_accept_token(
    *,
    tenant: str,
    principal: str,
    token: PolicyDecisionTokenPort,
    tool_call: ToolCallPort,
    chain: AuditChainPort,
    gate: EnforcementGatePort,
    outbox: Callable[[], DispatchOutboxPort],
    worker_id: str,
    build_observation: Callable[[Any, str], tuple[Any, dict[str, Any]]],
    record_dispatch_intent: Callable[..., Any],
    dispatch_under_lease: Callable[..., dict[str, Any]],
    lifecycle_guard: Callable[..., None],
    note_proposal_id: Callable[[Any], None],
    resolve_toolspec: Callable[[str, dict[str, Any], str], dict[str, Any]] | None = None,
    assessed_toolspec: Callable[[str, str], str] | None = None,
    policy_bundle_hash: Callable[[], str] | None = None,
    require_execution_context: bool = False,
    ws1_gate: Ws1GatePort | None = None,
    ws1_capability: Callable[[Any, str], Any] | None = None,
    ws1_admission: Ws1AdmissionPort | None = None,
    transaction: Callable[[str], Any] | None = None,
    active_connection: Callable[[], Any] | None = None,
    transactional_append: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Execute a directly-ACCEPTed proposal under its single-use token.

    Order is the guarantee: (1) exact payload binding checked first and
    WITHOUT consuming - a mismatched payload must not burn the grant for
    the call the token actually authorizes; (2) atomic single-use
    consumption; (3) durable dispatch intent before any side effect;
    (4) governed dispatch under the same lease discipline. Deliberately no
    engine re-run: the token IS the exactly-bound authorization and its
    TTL is the freshness.

    The spec is resolved BEFORE any of that, for the same reason the review
    path resolves it first: a call whose ToolSpec moved since assessment must
    be refused without spending the grant. Resolving it late — or, as here,
    not at all — left the locally minted lease binding an empty spec hash
    while the dispatcher's resolver reported the live one, so every redemption
    under a configured bundle refused with ``toolspec_hash_mismatch`` after
    consumption had already made the token unusable (audit 2026-09-02).

    Under WS1 enforce (issue #953) the WS1 gate runs again with fresh
    lookups before the context check, and its binding is part of that
    context: a precondition no longer proved refuses as
    ``ws1_regate_refused``, a moved requirement as ``context_mismatch``, and
    neither spends the grant. ``ws1_capability(call, principal)`` gives the
    capability block the binding covers.

    With ``ws1_admission`` (WS1-M4 M4.1c) the re-gate's evidence is checked
    again at the instant the grant is spent: one ``transaction`` reads the
    database time and the authority epochs under lock, refuses expired or
    stale evidence, consumes the grant on its connection, records the intent
    and enqueues the admission event, and commits all of it or none of it.
    Evidence that lapses after the re-gate then refuses instead of running
    (control 2b, M4-T02).
    """
    obs, semantic = build_observation(tool_call, tenant)
    proposal_id = token.request_id or None
    note_proposal_id(proposal_id)
    context = historical_context(
        chain, tenant, str(proposal_id or ""), required=require_execution_context)
    obs = _bind_execution_context(
        obs, semantic, context, proposal_id=str(proposal_id or ""),
        tenant=tenant, principal=principal)

    toolspec_identity: dict[str, Any] | None = None
    if resolve_toolspec is not None:
        toolspec_identity = resolve_toolspec(
            tool_call.tool_name, tool_call.arguments,
            tool_call.target_environment)
        toolspec_identity.pop("argument_roles", None)
        assessed_hash = (
            assessed_toolspec(tenant, str(proposal_id or ""))
            if assessed_toolspec is not None else "")
        if (toolspec_identity["enforced"] and assessed_hash
                and toolspec_identity["hash"] != assessed_hash):
            chain.append(tenant, {
                "event": "execution_toolspec_changed",
                "proposal_id": proposal_id,
                "actor": principal,
                "item_id": f"accept:{token.jti}",
                "assessed_toolspec_hash": assessed_hash,
                "current_toolspec_hash": toolspec_identity["hash"],
            })
            raise ToolSpecChanged(
                "toolspec_changed_between_assess_and_dispatch: the spec "
                "in force is not the one this grant was issued under"
            )

    if token.observation_hash != observation_binding(obs):
        chain.append(tenant, {
            "event": "execution_binding_refused",
            "proposal_id": proposal_id,
            "actor": principal,
            "tool_call_hash": obs.tool_call_hash,
            "detail": "payload does not match the token binding",
        })
        raise TokenRefused(
            "binding refused: the presented tool call does not match "
            "the one this token authorizes",
            "binding_refused",
        )

    if str(token.action).lower() != "accept":
        raise TokenRefused(
            f"token authorizes {token.action!r}, not an autonomous "
            "execution; only an ACCEPT may be redeemed here",
            "not_accept",
        )

    # The conditions this decision was made under, recomputed from the request
    # being redeemed. Deliberately checked BEFORE consumption, like the payload
    # binding above: a token presented under different conditions must not burn
    # the grant for the conditions it actually authorizes.
    request_ref = request_ref_of(tool_call)
    # A delegate the proposal named redeems as the proposer it acts for, and
    # the delegate field it re-presents must be the one signed in; anyone
    # else is compared as themselves and refused as context_mismatch.
    acting_for = _acting_for(
        _assessed_payload(chain, tenant, str(proposal_id or "")), principal)
    admitting = (ws1_admission is not None and ws1_gate is not None
                 and ws1_gate.mode == "enforce")
    epochs_before: dict[str, int] | None = None
    if admitting:
        assert ws1_admission is not None
        epochs_before, why = ws1_admission.before_regate(
            ws1_gate, tenant=tenant, tool_name=tool_call.tool_name)
        if epochs_before is None:
            _refuse_admission(chain, tenant=tenant, proposal_id=proposal_id,
                              principal=principal, grant_jti=token.jti, reason=why)
    ws1 = ws1_regate(
        ws1_gate, chain=chain, tenant=tenant, proposal_id=str(proposal_id or ""),
        proposer=acting_for or principal, tool_call=tool_call, semantic=semantic,
        observation=obs, toolspec_hash=str((toolspec_identity or {}).get("hash", "")),
        policy_bundle_hash=_policy_bundle_hash(policy_bundle_hash),
        capability=(ws1_capability(tool_call, acting_for or principal)
                    if ws1_capability is not None else None))
    if ws1 is not None and ws1.final_action is not DecisionAction.ACCEPT:
        chain.append(tenant, {
            "event": "execution_ws1_refused",
            "proposal_id": proposal_id,
            "actor": principal,
            "grant_jti": token.jti,
            "ws1": ws1.audit_block(),
        })
        raise TokenRefused(
            "WS1 re-gate refused: a precondition this grant was issued under "
            "is not proved now", WS1_REGATE_REFUSED)
    current_context = authorization_context(
        tenant=tenant, principal=acting_for or principal, semantic=semantic,
        target_environment=tool_call.target_environment or "",
        policy_bundle_hash=_policy_bundle_hash(policy_bundle_hash),
        toolspec_hash=str((toolspec_identity or {}).get("hash", "")),
        task=task_identity_of(tool_call),
        request_ref=request_ref,
        delegated_executor=delegated_executor_of(tool_call),
        ws1_binding_hash=ws1.binding_hash if ws1 is not None else "",
    )
    request_ref_fields = (
        {"request_ref_hash": request_ref.digest()} if request_ref is not None else {})
    context_check = token.verify(observation_binding(obs), context=current_context)
    if not context_check.verified and context_check.reason in {
        "context_mismatch",
        "context_unbound",
    }:
        chain.append(tenant, {
            "event": "execution_context_refused",
            "proposal_id": proposal_id,
            "actor": principal,
            "grant_jti": token.jti,
            "detail": context_check.reason,
        })
        raise TokenRefused(
            "authorization context refused: this token was issued under "
            "different conditions than the ones presented here",
            str(context_check.reason),
        )

    # The ACCEPT path does not re-decide, so the flow verdict of the call as
    # it stands now is checked here, before the grant is spent. The review
    # and worker paths re-decide, and the engine's flow rungs refuse there.
    flow_refusal = _flow_refusal(obs)
    if flow_refusal is not None:
        chain.append(tenant, {
            "event": "execution_flow_refused",
            "proposal_id": proposal_id,
            "actor": principal,
            "grant_jti": token.jti,
            "detail": flow_refusal,
        })
        raise TokenRefused(
            "flow refused at redemption: the call's information flow is not "
            "clean now", flow_refusal)

    # Consume exactly once. A refused check here is expiry, audience
    # mismatch, a bad signature, or a replay - all terminal for this token.
    intent: Any = None
    if admitting:
        assert ws1_admission is not None and epochs_before is not None
        gate_result, intent = _admit_atomically(
            ws1_admission, ws1, epochs_before, tenant=tenant, principal=principal,
            proposal_id=proposal_id, token=token, obs=obs, tool_call=tool_call,
            context=current_context, chain=chain, gate=gate,
            transaction=transaction, active_connection=active_connection,
            transactional_append=transactional_append,
            record_dispatch_intent=record_dispatch_intent)
    else:
        gate_result = gate.check(
            token, observation_binding(obs), consume=True, context=current_context)
    if not gate_result.allowed:
        chain.append(tenant, {
            "event": "execution_grant_refused",
            "proposal_id": proposal_id,
            "actor": principal,
            "grant_jti": token.jti,
            "detail": gate_result.reason,
        })
        raise TokenRefused(
            f"execution grant refused: {gate_result.reason}",
            str(gate_result.reason),
        )

    lifecycle_guard("ASSESSED", "direct_accept_token")

    now = datetime.now(UTC)
    response: dict[str, Any] = {
        "proposal_id": proposal_id,
        "outcome": ExecutionDecision.EXECUTE.value,
        "detail": "authorized by single-use ACCEPT token",
        "execution_grant": token.to_dict(),
        "pep": {"allowed": gate_result.allowed, "reason": gate_result.reason},
    }

    # Durable dispatch intent before any side effect (FT-02). Under WS1-M4
    # admission it was recorded in the admission transaction above.
    if not admitting:
        intent = record_dispatch_intent(
            proposal_id=str(proposal_id or token.jti),
            tenant=tenant,
            item_id=f"accept:{token.jti}",
            tool_name=tool_call.tool_name,
            tool_call_hash=obs.tool_call_hash or "",
            grant_jti=token.jti,
        )
    intent_entry = chain.append(tenant, {
        "event": "execution_authorized",
        "proposal_id": proposal_id,
        "actor": principal,
        **({"acting_for": acting_for} if acting_for else {}),
        "item_id": f"accept:{token.jti}",
        "tool_call_hash": obs.tool_call_hash,
        "grant_jti": token.jti,
        "pep_allowed": gate_result.allowed,
        **({"execution_context_hash": obs.execution_context_hash,
            "observation_binding_hash": observation_binding(obs)}
           if obs.execution_context_hash else {}),
        "tool_contract_bundle_hash": semantic["tool_contract_bundle_hash"],
        "intent_authority_hash": semantic["intent_authority_hash"],
        **request_ref_fields,
        # The signed grant itself, recorded only now that the gate has
        # consumed it: a spent grant authorizes nothing, and without it an
        # export has a jti and no signature to check it against.
        "grant": token.to_dict(),
    })
    # Unlike the review path, consumption stays ahead of the claim here: the
    # presented token IS the authority, and it must be proven single-use
    # before any intent exists for it. A second redeemer is stopped by the
    # atomic consume above, and the async worker skips this row because it
    # carries no tool_call_json, so this branch is defensive.
    if not _claim_or_none(outbox, intent, worker_id=worker_id):
        return _claim_lost_response(
            response, chain=chain, tenant=tenant, principal=principal,
            proposal_id=proposal_id, item_id=f"accept:{token.jti}",
            tool_call_hash=obs.tool_call_hash, grant_jti=token.jti,
            intent_sequence_no=intent_entry.sequence_no)

    # Governed dispatch - same dispatcher, same lease discipline.
    tool_execution = dispatch_under_lease(
        tenant=tenant,
        principal=principal,
        tool_call=tool_call,
        semantic=semantic,
        now=now,
        toolspec=toolspec_identity,
        proposal_id=str(proposal_id or token.jti),
        grant_jti=token.jti,
        report_lease=True,
        **_task_kwargs(tool_call),
        **_flow_kwargs(obs),
    )

    # Same structural classification as the review path: a dispatch that began
    # and then failed is UNKNOWN, not a durable claim that nothing happened.
    outcome = classify_outcome(tool_execution)
    settled_before: Any = None
    if intent is not None:
        reason = tool_execution.get("refusal_reason")
        # Issue #416: projection payload commits WITH the terminal state.
        # No review item exists on the direct-ACCEPT path; the payload's
        # item_id is the accept marker and the projector's queue replay
        # converges as a no-op for it.
        settled_row, already = _settle_reported(
            outbox, intent.outbox_id, _OUTBOX_STATE[outcome], detail=reason,
            projection_json=_projection_payload(
                proposal_id=proposal_id, item_id=f"accept:{token.jti}",
                actor=principal, tool_call_hash=obs.tool_call_hash or "",
                grant_jti=token.jti, outcome=outcome,
                tool_execution=tool_execution,
                intent_sequence_no=intent_entry.sequence_no,
            ))
        if already:
            settled_before = settled_row

    result_record: dict[str, Any] = {
        "event": "execution_result",
        "proposal_id": proposal_id,
        "actor": principal,
        "item_id": f"accept:{token.jti}",
        "tool_call_hash": obs.tool_call_hash,
        "grant_jti": token.jti,
        "intent_sequence_no": intent_entry.sequence_no,
        "tool_executed": tool_execution["executed"],
        # Whether the outcome is unknown, not merely unsuccessful. An effect
        # receipt may resolve an UNKNOWN dispatch -- a lost response does not
        # mean nothing happened -- so the chain has to carry the distinction.
        "state_unknown": bool(tool_execution.get("state_unknown")),
        **request_ref_fields,
    }
    envelope_meta = tool_execution.get("result_envelope")
    if envelope_meta:
        result_record["result_sha256"] = envelope_meta["sha256"]
        result_record["result_size_bytes"] = envelope_meta["size_bytes"]
        result_record["result_truncated"] = envelope_meta["truncated"]
    if tool_execution.get("refusal_reason"):
        result_record["tool_refusal_reason"] = tool_execution["refusal_reason"]
    # The lease the dispatcher acted under, when this process minted it.
    # Recorded after dispatch, when its nonce is spent.
    spent_lease = tool_execution.pop("lease", None)
    if spent_lease is not None:
        result_record["lease"] = spent_lease
    result_record.update(_nested_effects_fields(tool_execution))
    if settled_before is not None:
        _mark_reported_after_terminal(result_record, settled_before)
    # Idempotent by outbox id (issue #416): the in-line write claims the
    # same key the projector would replay under, so the record can land at
    # most once regardless of who finishes it.
    entry: Any = (chain.append_once(
        tenant, f"execution-result:{intent.outbox_id}", result_record)
        if intent is not None else chain.append(tenant, result_record))
    if intent is not None:
        outbox().mark_projected(intent.outbox_id)

    response["tool_execution"] = tool_execution
    if entry is not None:
        response["audit"] = {
            "sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash,
        }
    return response
