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
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from remora.enforcement.outbox import OutboxState
from remora.enforcement.token import PolicyDecisionToken
from remora.governance.review_queue import ExecutionDecision
from remora.governance.proposal_lineage import derive_lineage, lineage_key_for
from remora.policy.report import DecisionAction


def assess_proposal(
    *,
    tenant: str,
    principal: str,
    proposal: Any,
    engine: Any,
    chain: Any,
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


class ToolSpecChanged(Exception):
    """The spec in force is not the one the approval was granted under
    (route maps to 409). Refused BEFORE authorizing - a refused call must
    leave no dispatch intent behind (handoff gate section 3)."""


def execute_approved_item(
    *,
    tenant: str,
    principal: str,
    item_id: str,
    tool_call: Any,
    transaction: Callable[[str], Any],
    item_tenant: dict[str, str],
    chain: Any,
    gate: Any,
    outbox: Callable[[], Any],
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
) -> dict[str, Any]:
    """Execute a previously approved item under full re-gating.

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
        entry = chain.append(tenant, {
            "event": f"execution_{outcome.decision.value}",
            "proposal_id": proposal_id,
            "actor": principal,
            "item_id": item_id,
            "tool_call_hash": fresh_obs.tool_call_hash,
            "detail": outcome.detail,
        })
        response["audit"] = {
            "sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash,
        }
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
    })

    # FT-02: claim the intent before anything can take effect (exclusive).
    if intent is not None:
        outbox().claim(intent.outbox_id, worker_id=worker_id)

    tool_execution = dispatch_under_lease(
        tenant=tenant,
        principal=principal,
        tool_call=tool_call,
        semantic=fresh_semantic,
        now=now,
        gate_allowed=gate_result.allowed,
        toolspec=toolspec_identity,
    )

    # FT-02: settle with what actually happened - derived, never assumed.
    if intent is not None:
        reason = tool_execution.get("refusal_reason")
        if tool_execution["executed"]:
            settled_state = OutboxState.SUCCEEDED
        elif reason == "tool_failed_nonce_burned":
            settled_state = OutboxState.FAILED
        else:
            settled_state = OutboxState.REFUSED
        outbox().settle(intent.outbox_id, settled_state, detail=reason)

    # Persist the REAL outcome as the item's terminal state.
    with transaction(tenant) as q:
        q.record_execution_outcome(
            item_id,
            executed=tool_execution["executed"],
            failed=tool_execution.get("refusal_reason") == "tool_failed_nonce_burned",
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
    }
    # The chain records the result's identity, never the result body.
    envelope_meta = tool_execution.get("result_envelope")
    if envelope_meta:
        result_record["result_sha256"] = envelope_meta["sha256"]
        result_record["result_size_bytes"] = envelope_meta["size_bytes"]
        result_record["result_truncated"] = envelope_meta["truncated"]
    if tool_execution.get("refusal_reason"):
        result_record["tool_refusal_reason"] = tool_execution["refusal_reason"]
    entry = chain.append(tenant, result_record)

    response["tool_execution"] = tool_execution
    response["audit"] = {
        "sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash,
    }
    return response


class TokenRefused(Exception):
    """The presented ACCEPT token does not authorize this call (route maps
    to 409). ``refusal`` is the bounded metric label."""

    def __init__(self, detail: str, refusal: str) -> None:
        super().__init__(detail)
        self.refusal = refusal


def redeem_accept_token(
    *,
    tenant: str,
    principal: str,
    token: Any,
    tool_call: Any,
    chain: Any,
    gate: Any,
    outbox: Callable[[], Any],
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
    if intent is not None:
        outbox().claim(intent.outbox_id, worker_id=worker_id)

    # Governed dispatch - same dispatcher, same lease discipline.
    tool_execution = dispatch_under_lease(
        tenant=tenant,
        principal=principal,
        tool_call=tool_call,
        semantic=semantic,
        now=now,
    )

    if intent is not None:
        reason = tool_execution.get("refusal_reason")
        if tool_execution["executed"]:
            settled_state = OutboxState.SUCCEEDED
        elif reason == "tool_failed_nonce_burned":
            settled_state = OutboxState.FAILED
        else:
            settled_state = OutboxState.REFUSED
        outbox().settle(intent.outbox_id, settled_state, detail=reason)

    result_record: dict[str, Any] = {
        "event": "execution_result",
        "proposal_id": proposal_id,
        "actor": principal,
        "item_id": f"accept:{token.jti}",
        "tool_call_hash": obs.tool_call_hash,
        "grant_jti": token.jti,
        "intent_sequence_no": intent_entry.sequence_no,
        "tool_executed": tool_execution["executed"],
    }
    envelope_meta = tool_execution.get("result_envelope")
    if envelope_meta:
        result_record["result_sha256"] = envelope_meta["sha256"]
        result_record["result_size_bytes"] = envelope_meta["size_bytes"]
        result_record["result_truncated"] = envelope_meta["truncated"]
    if tool_execution.get("refusal_reason"):
        result_record["tool_refusal_reason"] = tool_execution["refusal_reason"]
    entry = chain.append(tenant, result_record)

    response["tool_execution"] = tool_execution
    response["audit"] = {
        "sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash,
    }
    return response
