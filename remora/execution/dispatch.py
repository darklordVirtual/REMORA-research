# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Governed dispatch under an exact-call lease (issue #241, slice 4).

Moved from servers/execution_api.py with the module singletons turned into
explicit parameters (dispatcher, policy bundle hash, outbox, ambient
transaction connection). Enforcement semantics are unchanged and shared by
the review path (/execute) and the ACCEPT path (/execute-accepted): a lease
bound to tenant, actor, tool, exact arguments, target and the current policy
bundle, dispatched by the component that holds the credentials — never the
caller. Every refusal is named; the return value reports what REALLY
happened instead of implying execution.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from remora.enforcement.lease import ExecutionLease, LeaseRefused
from remora.enforcement.outbox import ExecutionOutbox
from remora.enforcement.result_envelope import capture_tool_result


def dispatch_under_lease(
    *,
    tenant: str,
    principal: str,
    tool_call: Any,
    semantic: dict[str, Any],
    now: datetime,
    dispatcher: Any,
    policy_bundle_hash: str,
    gate_allowed: bool = True,
    toolspec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dispatch one authorized call through the governed dispatcher."""
    tool_execution: dict[str, Any] = {"executed": False}
    if not gate_allowed:
        tool_execution["refusal_reason"] = "pep_denied"
        return tool_execution
    if dispatcher is None:
        tool_execution["refusal_reason"] = "policy_bundle_unavailable"
        return tool_execution
    try:
        lease = ExecutionLease.issue(
            decision="accept",
            tenant_id=tenant,
            actor_identity=principal,
            tool_name=tool_call.tool_name,
            arguments=tool_call.arguments,
            target_environment=tool_call.target_environment,
            policy_bundle_hash=policy_bundle_hash,
            issued_at=now.isoformat(),
            tool_contract_bundle_hash=semantic["tool_contract_bundle_hash"],
            intent_authority_hash=semantic["intent_authority_hash"],
            toolspec_hash=(toolspec or {}).get("hash", ""),
            toolspec_version=int((toolspec or {}).get("version", 0)),
        )
    except (LeaseRefused, ValueError) as exc:
        tool_execution["refusal_reason"] = f"lease_unavailable: {exc}"
        return tool_execution
    try:
        dres = dispatcher.dispatch(
            lease,
            tool_call.tool_name,
            tool_call.arguments,
            tenant_id=tenant,
            target_environment=tool_call.target_environment,
            actor_identity=principal,
        )
    except RuntimeError as exc:
        # Tool raised: the nonce is burned, state is unknown.
        tool_execution["refusal_reason"] = "tool_failed_nonce_burned"
        tool_execution["error"] = str(exc)
        return tool_execution
    tool_execution["executed"] = dres.executed
    if dres.executed:
        # Bounded retention, unbounded verification: the hash covers the
        # full result even when the preview is truncated, so an oversized
        # or hostile tool output cannot inflate the audit chain or the
        # response while still being provable in replay.
        captured = capture_tool_result(dres.result)
        tool_execution["result"] = captured.preview
        tool_execution["result_envelope"] = captured.to_dict()
    else:
        tool_execution["refusal_reason"] = dres.refusal_reason
    return tool_execution


def record_dispatch_intent(
    outbox: ExecutionOutbox,
    connection: Any,
    *,
    proposal_id: str,
    tenant: str,
    item_id: str,
    tool_name: str,
    tool_call_hash: str,
    grant_jti: str,
):
    """Record the dispatch intent, inside the caller's transaction when open.

    With a durable backend the row commits with the authorization and rolls
    back with it, so "authorized" and "a dispatch was intended" can never
    disagree. Without one (development), the in-process store records it
    non-atomically — a limitation of that configuration, not of the design.
    """
    # Only the durable adapters can join a transaction; the in-process base
    # class refuses enlistment by design rather than faking the guarantee.
    if connection is not None and type(outbox) is not ExecutionOutbox:
        return outbox.record_intent_enlisted(
            connection,
            proposal_id=proposal_id,
            tenant_id=tenant,
            item_id=item_id,
            tool_name=tool_name,
            tool_call_hash=tool_call_hash,
            grant_jti=grant_jti,
        )
    return outbox.record_intent(
        proposal_id=proposal_id,
        tenant_id=tenant,
        item_id=item_id,
        tool_name=tool_name,
        tool_call_hash=tool_call_hash,
        grant_jti=grant_jti,
    )
