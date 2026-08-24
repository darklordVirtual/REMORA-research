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

import logging
from datetime import datetime
from typing import Any

from remora.enforcement.lease import ExecutionLease, LeaseRefused
from remora.execution.remote_dispatch import (
    RemoteDispatchUnavailable,
    execution_endpoint,
    remote_dispatch,
)
from remora.enforcement.outbox import ExecutionOutbox, OutboxRow
from remora.observability.events import governance_event
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
    proposal_id: str = "",
    grant_jti: str = "",
    presented_lease: ExecutionLease | None = None,
) -> dict[str, Any]:
    """Dispatch one authorized call through the governed dispatcher.

    ``proposal_id`` and ``grant_jti`` are the correlation half (issue #45):
    they are signed into the lease and reported back on the result, so an
    executed side effect joins to the decision that authorized it and to the
    grant that was consumed, without re-deriving hashes out of band.

    ``presented_lease`` is the custody-split seam (ADR-A). When supplied, this
    function does NOT mint: it dispatches under a lease some other component
    issued. That is what allows the executing process to hold only a public
    verification key -- a process that cannot sign cannot reach the branch
    below, and with a lease handed to it, it does not need to.

    The lease is NOT trusted because it arrived. ``dispatcher.dispatch``
    re-verifies the whole binding against the concrete call before anything
    runs, exactly as it does for a locally issued one. The only thing that
    changes is who signed it.
    """
    tool_execution: dict[str, Any] = {"executed": False}
    if not gate_allowed:
        tool_execution["refusal_reason"] = "pep_denied"
        return tool_execution
    if dispatcher is None and not execution_endpoint():
        # The authority domain has no tool callables and needs none; a missing
        # dispatcher is only a fault when this process is the one that executes.
        tool_execution["refusal_reason"] = "policy_bundle_unavailable"
        return tool_execution
    if presented_lease is not None:
        # Issued by the authority domain. Verification happens in dispatch()
        # below, against this concrete call -- arriving is not authorisation.
        lease = presented_lease
    else:
        try:
            lease = _issue_local_lease(
                tenant=tenant, principal=principal, tool_call=tool_call,
                semantic=semantic, now=now,
                policy_bundle_hash=policy_bundle_hash, toolspec=toolspec,
                proposal_id=proposal_id, grant_jti=grant_jti,
            )
        except (LeaseRefused, ValueError) as exc:
            tool_execution["refusal_reason"] = f"lease_unavailable: {exc}"
            return tool_execution
    # ── the custody boundary ────────────────────────────────────────────
    # When an execution domain is configured, THIS process is the authority:
    # it holds the private key and has just signed a lease, and it does not
    # hold the downstream credential. The effect happens on the other side.
    #
    # Only reached when a lease was minted here. A presented_lease means this
    # process IS the executor, so forwarding it again would be a loop.
    if presented_lease is None and execution_endpoint():
        try:
            return remote_dispatch(
                lease=lease, tenant=tenant, principal=principal,
                tool_call=tool_call, now=now.isoformat(),
            )
        except RemoteDispatchUnavailable as exc:
            # No verdict. Reported as unknown rather than as a refusal: the
            # request may have been received, the nonce spent and the effect
            # caused, with only the answer lost. Calling that "not executed"
            # would invite a retry of a side effect that already happened.
            governance_event(
                "dispatch.execution_domain_unavailable", level=logging.ERROR,
                tenant_id=tenant, tool_name=tool_call.tool_name,
                proposal_id=proposal_id, detail=str(exc),
            )
            return {
                "executed": False,
                "refusal_reason": "execution_domain_unreachable",
                "error": str(exc),
                "proposal_id": proposal_id,
                "state_unknown": True,
            }

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
        tool_execution["proposal_id"] = proposal_id
        return tool_execution
    tool_execution["executed"] = dres.executed
    # Read the identity back off the dispatch result rather than the local
    # variable: what is reported is what the dispatcher actually acted under.
    tool_execution["proposal_id"] = dres.proposal_id
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


def issue_execution_lease(
    *,
    tenant: str,
    principal: str,
    tool_call: Any,
    semantic: dict[str, Any],
    now: Any,
    policy_bundle_hash: str,
    toolspec: dict[str, Any] | None = None,
    proposal_id: str = "",
    grant_jti: str = "",
) -> ExecutionLease:
    """Mint a lease. The authority domain's half of the custody split.

    Public because the authority domain calls it directly: it decides, then it
    signs what it decided. Kept in this module so that the field set the
    authority signs and the field set the executor verifies cannot drift apart
    -- they are the same code.
    """
    return _issue_local_lease(
        tenant=tenant, principal=principal, tool_call=tool_call,
        semantic=semantic, now=now, policy_bundle_hash=policy_bundle_hash,
        toolspec=toolspec, proposal_id=proposal_id, grant_jti=grant_jti,
    )


def _issue_local_lease(
    *,
    tenant: str,
    principal: str,
    tool_call: Any,
    semantic: dict[str, Any],
    now: Any,
    policy_bundle_hash: str,
    toolspec: dict[str, Any] | None,
    proposal_id: str,
    grant_jti: str,
) -> ExecutionLease:
    return ExecutionLease.issue(
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
            proposal_id=proposal_id,
            grant_jti=grant_jti,
        )


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
) -> "OutboxRow":
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
