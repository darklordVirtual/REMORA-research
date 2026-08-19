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

from remora.enforcement.token import PolicyDecisionToken
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
