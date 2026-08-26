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

from remora.errors import RemoraError

from remora.execution.ports import (AuditChainPort, DispatchOutboxPort,
                                    EnforcementGatePort,
                                    PolicyDecisionTokenPort,
                                    PolicyEnginePort, ToolCallPort)

import dataclasses
import json
from collections.abc import Callable
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from remora.execution.outcome import DispatchOutcome, classify_outcome
from remora.enforcement.outbox import OutboxState
from remora.enforcement.token import PolicyDecisionToken
from remora.governance.review_queue import ExecutionDecision
from remora.governance.proposal_lineage import derive_lineage, lineage_key_for
from remora.policy.report import DecisionAction


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
    intent_sequence_no: int,
) -> dict[str, Any]:
    """Record and return "another worker holds this intent".

    The chain gets a result record like any other dispatch, because the absence
    of a dispatch is itself an auditable outcome and a gap in the chain would
    read as a lost event rather than a refusal. What it does NOT do is settle
    the outbox row or drive the item to a terminal state: both belong to the
    worker that won the claim, and writing them here would overwrite the record
    of the execution that actually happens.
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
    """
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
    report = engine.decide(obs)
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
    response: dict[str, Any] = {
        "proposal_id": proposal_id,
        "decision": report.action.value,
        "reasons": [r.value for r in report.reasons],
        "tool_call_hash": obs.tool_call_hash,
        "semantic": dict(semantic),
        "toolspec": dict(toolspec_identity),
    }
    # FT-01 conformance BEFORE anything is recorded.
    branch_event = {
        DecisionAction.ACCEPT: "direct_accept_token",
        DecisionAction.VERIFY: "verify_or_escalate",
        DecisionAction.ESCALATE: "verify_or_escalate",
        DecisionAction.ABSTAIN: "abstain_or_hard_refusal",
    }.get(report.action, "abstain_or_hard_refusal")
    lifecycle_guard("PROPOSED", "engine_decision", branch_event)

    item = None
    if report.action is DecisionAction.ACCEPT:
        token = PolicyDecisionToken.issue(
            action="accept",
            observation_hash=obs.tool_call_hash or "",
            request_id=proposal_id,
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=token_ttl_seconds)).isoformat(),
            audience=token_audience,
        )
        record["grant_jti"] = token.jti
        response["execution_token"] = token.to_dict()
    else:
        with transaction(tenant) as q:
            # REM-032 lazy sweep: overdue PENDING items resolve to ABSTAIN
            # before new work is considered.
            q.expire_due()
            item = q.enqueue(obs, report.action) if report.action in (
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
    return response


class ToolSpecChanged(RemoraError):
    """The spec in force is not the one the approval was granted under
    (route maps to 409). Refused BEFORE authorizing - a refused call must
    leave no dispatch intent behind (handoff gate section 3)."""

    code = "toolspec_changed"
    category = "execution"


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
    async_dispatch: bool = False,
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
    """
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
    try:
        # Tenant binding inside the transaction (review finding 2a); the
        # canonical proposal identity rides the QUEUED observation - the
        # re-presented payload never carries one the caller could assert.
        with transaction(tenant) as q:
            if item_tenant.get(item_id) != tenant:
                raise not_found(item_id)
            q.expire_due()
            proposal_id = getattr(q.item(item_id).observation,
                                  "proposal_id", None)
            note_proposal_id(proposal_id)
            outcome = q.execute(item_id, fresh_obs)
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
                )
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
        refusal_entry = chain.append(tenant, {
            "event": f"execution_{outcome.decision.value}",
            "proposal_id": proposal_id,
            "actor": principal,
            "item_id": item_id,
            "tool_call_hash": fresh_obs.tool_call_hash,
            "detail": outcome.detail,
        })
        response["audit"] = {
            "sequence_no": refusal_entry.sequence_no,
            "entry_hash": refusal_entry.entry_hash,
        }
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

    # The re-gate only AUTHORIZED the call; EXECUTED is recorded separately
    # after the dispatcher reports what actually happened.
    now = datetime.now(UTC)
    token = PolicyDecisionToken.issue(
        action="accept",
        observation_hash=fresh_obs.tool_call_hash or "",
        # FT-01: the grant carries the canonical proposal identity; the
        # legacy composite only for pre-lifecycle items with no proposal.
        request_id=proposal_id or f"{tenant}:{item_id}",
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=token_ttl_seconds)).isoformat(),
        audience=token_audience,
    )
    # PEP consumption happens HERE: the grant is consumed atomically the
    # moment it is honoured - a re-presented token can never execute twice.
    gate_result = gate.check(token, fresh_obs.tool_call_hash, consume=True)
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
        "item_id": item_id,
        "tool_call_hash": fresh_obs.tool_call_hash,
        "grant_jti": token.jti,
        "pep_allowed": gate_result.allowed,
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

    # FT-02: claim the intent before anything can take effect (exclusive).
    # A lost race means another worker holds this intent. Dispatching anyway
    # would execute the same side effect twice, which is the single failure the
    # outbox exists to prevent.
    if not _claim_or_none(outbox, intent, worker_id=worker_id):
        return _claim_lost_response(
            response, chain=chain, tenant=tenant, principal=principal,
            proposal_id=proposal_id, item_id=item_id,
            tool_call_hash=fresh_obs.tool_call_hash, grant_jti=token.jti,
            intent_sequence_no=intent_entry.sequence_no)

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
    )

    # FT-02: settle with what actually happened - derived, never assumed.
    #
    # The outcome is classified structurally. This used to match
    # refusal_reason == "tool_failed_nonce_burned" and settle FAILED, which
    # asserted "no effect occurred" on evidence that only showed the call
    # raised. A dispatch that began and then failed is UNKNOWN until something
    # proves otherwise (NEGATIVE_RESULTS section 48).
    outcome = classify_outcome(tool_execution)
    if intent is not None:
        reason = tool_execution.get("refusal_reason")
        # Issue #416: the projection payload commits WITH the terminal
        # state, so a crash after this line strands nothing unrecoverable.
        outbox().settle(
            intent.outbox_id, _OUTBOX_STATE[outcome], detail=reason,
            projection_json=_projection_payload(
                proposal_id=proposal_id, item_id=item_id, actor=principal,
                tool_call_hash=fresh_obs.tool_call_hash or "",
                grant_jti=token.jti, outcome=outcome,
                tool_execution=tool_execution,
                intent_sequence_no=intent_entry.sequence_no,
            ))

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
    }
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
    if p.get("intent_sequence_no") is not None:
        record["intent_sequence_no"] = p["intent_sequence_no"]
    if p.get("refusal_reason"):
        record["tool_refusal_reason"] = p["refusal_reason"]
    for key in ("result_sha256", "result_size_bytes", "result_truncated"):
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
    rebuild_call: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any] | None:
    """Dispatch one DISPATCH_PENDING intent from a separate worker (issue #82).

    The dispatch half of :func:`execute_approved_item`'s async mode, with
    the SAME record shapes and the same order of guarantees: the grant is
    minted and PEP-consumed at the moment of honouring, the
    ``execution_authorized`` chain entry precedes the claim, the claim is
    exclusive, dispatch goes through the governed dispatcher, and the row
    settles with what ACTUALLY happened before the ``execution_result``
    entry lands.

    Returns ``None`` for rows this worker must not touch: not
    DISPATCH_PENDING (another worker, or already settled), no persisted
    payload (pre-#82 rows and synchronous-path rows — the reconciler owns
    their fate, this worker cannot reconstruct the call), or a lost claim
    race. A payload that no longer hashes to the authorization's binding
    is refused and settled REFUSED — a worker must never dispatch a call
    other than the one that was authorized.
    """
    if row.state is not OutboxState.DISPATCH_PENDING:
        return None
    if not row.tool_call_json:
        return None
    refusal: str | None = None
    tool_call: Any = None
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
    proposal_id = row.proposal_id
    if refusal is not None:
        if outbox().claim(row.outbox_id, worker_id=worker_id) is None:
            return None
        refusal_execution = {"executed": False, "dispatch_began": False,
                             "state_unknown": False,
                             "refusal_reason": refusal}
        outbox().settle(
            row.outbox_id, OutboxState.REFUSED, detail=refusal,
            projection_json=_projection_payload(
                proposal_id=proposal_id, item_id=row.item_id,
                actor=principal, tool_call_hash=row.tool_call_hash,
                grant_jti="", outcome=DispatchOutcome.REFUSED,
                tool_execution=refusal_execution,
                intent_sequence_no=None,
            ))
        # Issue #421 (RMR-CR-006): the review item takes the SAME terminal
        # outcome as the outbox — a refused dispatch must never leave the
        # item AUTHORIZED forever.
        with transaction(tenant) as q:
            q.record_execution_outcome(
                row.item_id, outcome=DispatchOutcome.REFUSED, reason=refusal)
        entry = chain.append_once(
            tenant, f"execution-result:{row.outbox_id}", {
                "event": "execution_result",
                "proposal_id": proposal_id,
                "actor": principal,
                "item_id": row.item_id,
                "tool_call_hash": row.tool_call_hash,
                "grant_jti": "",
                "tool_executed": False,
                "state_unknown": False,
                "tool_refusal_reason": refusal,
            })
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

    toolspec_identity: dict[str, Any] | None = None
    if resolve_toolspec is not None:
        toolspec_identity = resolve_toolspec(
            tool_call.tool_name, tool_call.arguments,
            tool_call.target_environment)
        toolspec_identity.pop("argument_roles", None)

    now = datetime.now(UTC)
    token = PolicyDecisionToken.issue(
        action="accept",
        observation_hash=fresh_obs.tool_call_hash or "",
        request_id=proposal_id or f"{tenant}:{row.item_id}",
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=token_ttl_seconds)).isoformat(),
        audience=token_audience,
    )
    gate_result = gate.check(token, fresh_obs.tool_call_hash, consume=True)
    coverage = policy_coverage() if policy_coverage is not None else None
    intent_entry = chain.append(tenant, {
        "event": "execution_authorized",
        "proposal_id": proposal_id,
        "actor": principal,
        "item_id": row.item_id,
        "tool_call_hash": fresh_obs.tool_call_hash,
        "grant_jti": token.jti,
        "pep_allowed": gate_result.allowed,
        "tool_contract_bundle_hash": fresh_semantic["tool_contract_bundle_hash"],
        "intent_authority_hash": fresh_semantic["intent_authority_hash"],
        "policy_components": coverage,
    })

    if outbox().claim(row.outbox_id, worker_id=worker_id) is None:
        return None

    tool_execution = dispatch_under_lease(
        tenant=tenant,
        principal=principal,
        tool_call=tool_call,
        semantic=fresh_semantic,
        now=now,
        gate_allowed=gate_result.allowed,
        toolspec=toolspec_identity,
        proposal_id=str(proposal_id or row.item_id),
        grant_jti=token.jti,
    )

    outcome = classify_outcome(tool_execution)
    # Issue #416: projection payload commits WITH the terminal state.
    outbox().settle(
        row.outbox_id, _OUTBOX_STATE[outcome],
        detail=tool_execution.get("refusal_reason"),
        projection_json=_projection_payload(
            proposal_id=proposal_id, item_id=row.item_id, actor=principal,
            tool_call_hash=fresh_obs.tool_call_hash or "",
            grant_jti=token.jti, outcome=outcome,
            tool_execution=tool_execution,
            intent_sequence_no=intent_entry.sequence_no,
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
        "actor": principal,
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
) -> dict[str, Any]:
    """Execute a directly-ACCEPTed proposal under its single-use token.

    Order is the guarantee: (1) exact payload binding checked first and
    WITHOUT consuming - a mismatched payload must not burn the grant for
    the call the token actually authorizes; (2) atomic single-use
    consumption; (3) durable dispatch intent before any side effect;
    (4) governed dispatch under the same lease discipline. Deliberately no
    engine re-run: the token IS the exactly-bound authorization and its
    TTL is the freshness.
    """
    obs, semantic = build_observation(tool_call, tenant)
    proposal_id = token.request_id or None
    note_proposal_id(proposal_id)

    if token.observation_hash != (obs.tool_call_hash or ""):
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

    # Consume exactly once. A refused check here is expiry, audience
    # mismatch, a bad signature, or a replay - all terminal for this token.
    gate_result = gate.check(token, obs.tool_call_hash, consume=True)
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

    # Durable dispatch intent before any side effect (FT-02).
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
        "item_id": f"accept:{token.jti}",
        "tool_call_hash": obs.tool_call_hash,
        "grant_jti": token.jti,
        "pep_allowed": gate_result.allowed,
        "tool_contract_bundle_hash": semantic["tool_contract_bundle_hash"],
        "intent_authority_hash": semantic["intent_authority_hash"],
    })
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
        proposal_id=str(proposal_id or token.jti),
        grant_jti=token.jti,
    )

    # Same structural classification as the review path: a dispatch that began
    # and then failed is UNKNOWN, not a durable claim that nothing happened.
    outcome = classify_outcome(tool_execution)
    if intent is not None:
        reason = tool_execution.get("refusal_reason")
        # Issue #416: projection payload commits WITH the terminal state.
        # No review item exists on the direct-ACCEPT path; the payload's
        # item_id is the accept marker and the projector's queue replay
        # converges as a no-op for it.
        outbox().settle(
            intent.outbox_id, _OUTBOX_STATE[outcome], detail=reason,
            projection_json=_projection_payload(
                proposal_id=proposal_id, item_id=f"accept:{token.jti}",
                actor=principal, tool_call_hash=obs.tool_call_hash or "",
                grant_jti=token.jti, outcome=outcome,
                tool_execution=tool_execution,
                intent_sequence_no=intent_entry.sequence_no,
            ))

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
    }
    envelope_meta = tool_execution.get("result_envelope")
    if envelope_meta:
        result_record["result_sha256"] = envelope_meta["sha256"]
        result_record["result_size_bytes"] = envelope_meta["size_bytes"]
        result_record["result_truncated"] = envelope_meta["truncated"]
    if tool_execution.get("refusal_reason"):
        result_record["tool_refusal_reason"] = tool_execution["refusal_reason"]
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
