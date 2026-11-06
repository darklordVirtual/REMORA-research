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
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from remora.enforcement.lease import (
    DEFAULT_LEASE_TTL_SECONDS,
    ExecutionLease,
    LeaseRefused,
    ToolExecutionStateUnknown,
)
from remora.enforcement.lease_signing import SigningUnavailable
from remora.enforcement.outbox import (
    ExecutionOutbox,
    OutboxRow,
    UnbackedExecutionOutbox,
)
from remora.enforcement.result_envelope import capture_tool_result
from remora.execution.ports import ToolCallPort, ToolDispatcherPort
from remora.execution.remote_dispatch import (
    RemoteDispatchUnavailable,
    execution_endpoint,
    remote_dispatch,
)
from remora.governance.execution_identity import ExecutionContextV1
from remora.observability.events import governance_event


def _execution_context(semantic: dict[str, Any]) -> ExecutionContextV1 | None:
    canonical = semantic.get("execution_context_canonical")
    return ExecutionContextV1.from_canonical(canonical) if canonical is not None else None

if TYPE_CHECKING:
    from remora.capabilities.model import EffectiveCapabilitySet
    from remora.enforcement.resolved_effect import ResolvedEffect
    from remora.governance.plan_binding import PlanBinding
    from remora.governance.task_identity import TaskIdentity


def dispatch_under_lease(
    *,
    tenant: str,
    principal: str,
    tool_call: ToolCallPort,
    semantic: dict[str, Any],
    now: datetime,
    dispatcher: ToolDispatcherPort | None,
    policy_bundle_hash: str,
    gate_allowed: bool = True,
    toolspec: dict[str, Any] | None = None,
    proposal_id: str = "",
    grant_jti: str = "",
    presented_lease: ExecutionLease | None = None,
    task_identity: TaskIdentity | None = None,
    resolved_effect: ResolvedEffect | None = None,
    plan: PlanBinding | None = None,
    capability_set: EffectiveCapabilitySet | None = None,
    surface_digest: str = "",
    report_lease: bool = False,
    result_commit: Callable[[Any], tuple[Any, dict[str, Any]]] | None = None,
    invocation_arguments: Any = None,
    not_after: datetime | None = None,
    flow_binding: tuple[int, str, str] | None = None,
    flow_recipients: frozenset[str] | None = None,
    cam_digest: str = "",
    approver_count: int = 0,
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

    ``task_identity`` (Q7.2) is the task the call is made under. It is signed
    into a lease minted here and checked against the lease at dispatch, so an
    approval granted under one task cannot run under another.

    ``resolved_effect`` (Q7.4) is what the call resolves to in this domain's
    registry. It is signed into a lease minted here; the executing
    dispatcher resolves again and refuses a different effect.

    ``plan`` (Q7.5) is the plan whose premises this write depends on. Its
    digest is signed into a lease minted here and the dispatcher re-reads
    the premises before the write.

    ``capability_set`` (Q8.2) is the set the call runs under, resolved from
    trusted state by the caller. Its digest is signed into a lease minted here
    and the dispatcher checks the tool against it.

    The lease is NOT trusted because it arrived. ``dispatcher.dispatch``
    re-verifies the whole binding against the concrete call before anything
    runs, exactly as it does for a locally issued one. The only thing that
    changes is who signed it.

    ``report_lease`` adds the lease minted here, as ``lease``, to a result the
    dispatcher returned: its nonce is spent by then, and the caller records
    it as evidence. A presented lease, a forwarded one and a refusal before
    dispatch are never reported.

    ``result_commit`` (SDD v2 WP-04, AR-017) runs on the raw result of an
    executed call before anything is returned. It returns what the caller may
    see and an audit block. When it raises, the call still counts as executed,
    and the result is withheld: no preview and no envelope are returned.

    ``invocation_arguments`` (IFC-06) are the call's flow handles resolved to
    their values by this execution domain. The lease binds
    ``tool_call.arguments``; the local dispatcher checks both forms and the
    tool receives these. A forwarded call ignores them: the executing domain
    resolves the handles in its own store.

    ``not_after`` (WS1-M4, M4-T14) caps the expiry of a lease minted here at
    the instant the evidence behind the admission stops holding. At or past
    it, nothing is minted and the call is refused as ``permit_expired``.

    ``flow_binding`` (IFC-06) is the flow decision this call was judged
    under: the context epoch, the verdict digest and the canonical hash of
    the call with every handle resolved. It is signed into a lease minted
    here, so the executing domain compares its live context and the
    arguments it is about to run against what this authority judged.
    """
    tool_execution: dict[str, Any] = {"executed": False}
    if not gate_allowed:
        tool_execution["refusal_reason"] = "pep_denied"
        return tool_execution
    if not_after is not None and presented_lease is None and now >= not_after:
        tool_execution["refusal_reason"] = "permit_expired"
        return tool_execution
    # A dispatcher is needed exactly when this process will execute locally,
    # which is when it is NOT going to forward. Forwarding happens only for a
    # lease minted here with an execution domain configured.
    #
    # The earlier form tested only `not execution_endpoint()`, so a process
    # configured as both (endpoint set) that received a presented lease with no
    # dispatcher skipped this guard and reached dispatcher.dispatch(None) --
    # an AttributeError instead of the named refusal this function documents.
    # Found by review; the deployed endpoint guards it separately, so it was
    # reachable through the library rather than through the API.
    will_forward = presented_lease is None and bool(execution_endpoint())
    if dispatcher is None and not will_forward:
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
                task_identity=task_identity,
                resolved_effect=resolved_effect,
                plan=plan,
                capability_set=capability_set,
                surface_digest=surface_digest,
                not_after=not_after,
                flow_binding=flow_binding,
                flow_recipients=flow_recipients,
                cam_digest=cam_digest,
                approver_count=approver_count,
            )
        except (LeaseRefused, ValueError, SigningUnavailable) as exc:
            # SigningUnavailable belongs here, and its absence was a live 500.
            # The deployed image installed .[api,postgres] without [security],
            # so cryptography was missing, _ed25519() raised, and the exception
            # escaped as an unhandled server error instead of a named refusal
            # (NEGATIVE_RESULTS section 45).
            #
            # Failing loudly on missing crypto is deliberate -- silently
            # falling back to HMAC would restore the custody defect. Failing as
            # a 500 is not: the operator learns nothing, and the audit chain
            # records no reason. It is a refusal with a name.
            # The exception text goes to the audit event, never to the caller:
            # a signing failure can name key material and paths.
            governance_event(
                "dispatch.lease_unavailable", level=logging.ERROR,
                tenant_id=tenant, tool_name=tool_call.tool_name,
                proposal_id=proposal_id, detail=str(exc),
            )
            tool_execution["refusal_reason"] = "lease_unavailable"
            tool_execution["error"] = type(exc).__name__
            return tool_execution
    # ── the custody boundary ────────────────────────────────────────────
    # When an execution domain is configured, THIS process is the authority:
    # it holds the private key and has just signed a lease, and it does not
    # hold the downstream credential. The effect happens on the other side.
    #
    # Only reached when a lease was minted here. A presented_lease means this
    # process IS the executor, so forwarding it again would be a loop.
    if will_forward:
        try:
            forwarded = remote_dispatch(
                lease=lease, tenant=tenant, principal=principal,
                tool_call=tool_call, capability_set=capability_set, plan=plan,
                execution_context=_execution_context(semantic),
            )
            if result_commit is None or not forwarded.get("executed"):
                return forwarded
            if forwarded.get("flow_commit") is not None or forwarded.get("result_withheld"):
                # The execution domain ran the flow check and committed the
                # result's labels itself (/dispatch-leased under flow
                # control), or withheld it. Committing again here would label
                # the rendered result a second time and, when the first
                # commit raised the context label, withhold it as
                # flow_epoch_changed_during_dispatch.
                return forwarded
            envelope = forwarded.pop("result_envelope", None) or {}
            raw = forwarded.pop("result", None)
            if envelope.get("truncated", True):
                # Labels are computed over the whole result. A preview is
                # not the whole result, so nothing of it is returned.
                forwarded["result_withheld"] = "flow_result_truncated"
                return forwarded
            return _committed(forwarded, raw, result_commit, tenant, tool_call, proposal_id)
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
                # Class only; the message is in the audit event above.
                "error": type(exc).__name__,
                "proposal_id": proposal_id,
                "state_unknown": True,
                **({"execution_context_hash": lease.execution_context_hash,
                    "execution_id": lease.grant_jti}
                   if lease.execution_context_hash else {}),
            }

    # Narrowing for the type checker, not a runtime decision: the compound
    # guard above returned already when dispatcher is None and this process
    # is not forwarding, and the forwarding branch returned before reaching
    # here. If this ever fires, the guard logic changed and the named
    # refusal contract with it.
    assert dispatcher is not None
    # Passed only when present, so a dispatcher implementing the port without
    # the parameter keeps working for calls that carry no task.
    task_kwargs: dict[str, Any] = (
        {"task_identity": task_identity} if task_identity is not None else {}
    )
    if plan is not None:
        task_kwargs["plan"] = plan
    if capability_set is not None:
        task_kwargs["capability_set"] = capability_set
    if invocation_arguments is not None:
        task_kwargs["invocation_arguments"] = invocation_arguments
    if flow_recipients is not None:
        # IFC-12: the recipients the flow check approved, for the mediator
        # and for the comparison with the lease's signed digest.
        task_kwargs["flow_recipients"] = flow_recipients
    context = _execution_context(semantic)
    if context is not None:
        task_kwargs["execution_context"] = context
    try:
        dres = dispatcher.dispatch(
            lease,
            tool_call.tool_name,
            tool_call.arguments,
            tenant_id=tenant,
            target_environment=tool_call.target_environment,
            actor_identity=principal,
            # The clock this function was handed, used for the whole call. It
            # already issued the lease against `now`; verifying against the
            # wall clock instead meant issue and verify could disagree about
            # what time it was. In production the two are moments apart and
            # nothing showed. Under a long test run they were minutes apart,
            # the 120-second TTL elapsed between collection and execution,
            # and two security guards failed as lease_expired at random
            # (issue #379) -- a flake in exactly the tests that must not be
            # re-run until green.
            now=now.isoformat(),
            **task_kwargs,
        )
    except RuntimeError as exc:
        # The tool raised after its nonce was consumed. Whether the effect
        # happened is exactly what is not known: the call reached the tool, and
        # the exception says nothing about whether it committed first.
        #
        # state_unknown is set here, structurally, because settlement used to
        # read this refusal_reason string and record a durable FAILED --
        # asserting no effect occurred on evidence that only shows the call
        # raised (NEGATIVE_RESULTS section 48).
        governance_event(
            "dispatch.tool_raised", level=logging.ERROR,
            tenant_id=tenant, tool_name=tool_call.tool_name,
            proposal_id=proposal_id, detail=str(exc),
        )
        tool_execution["refusal_reason"] = "tool_failed_nonce_burned"
        # The tool's own message stays server-side: a downstream client can
        # embed hosts, paths or credentials in what it raises.
        tool_execution["error"] = type(exc).__name__
        tool_execution["proposal_id"] = proposal_id
        tool_execution["dispatch_began"] = True
        tool_execution["state_unknown"] = True
        if isinstance(exc, ToolExecutionStateUnknown) and exc.execution_context_hash:
            tool_execution["execution_context_hash"] = exc.execution_context_hash
            tool_execution["execution_id"] = exc.execution_id
            tool_execution["dispatch_check"] = exc.dispatch_check
        # NTA-2: what a mediated tool asked for before it raised.
        nested = getattr(exc, "nested_effects", None)
        if nested is not None:
            tool_execution["nested_effects"] = dict(nested)
        graph = getattr(exc, "effect_graph", None)
        if graph is not None:
            tool_execution["effect_graph"] = graph.to_dict()
        return tool_execution
    tool_execution["executed"] = dres.executed
    if report_lease and presented_lease is None:
        tool_execution["lease"] = lease.to_dict()
    # Reported by the dispatcher, never inferred from the refusal reason.
    tool_execution["dispatch_began"] = dres.dispatch_began
    # Read the identity back off the dispatch result rather than the local
    # variable: what is reported is what the dispatcher actually acted under.
    tool_execution["proposal_id"] = dres.proposal_id
    if getattr(dres, "execution_context_hash", "") or getattr(dres, "dispatch_check", None):
        tool_execution["execution_context_hash"] = dres.execution_context_hash
        tool_execution["execution_id"] = dres.execution_id
        tool_execution["dispatch_check"] = dict(dres.dispatch_check or {})
    # NTA-2: the nested effects a mediated tool requested, as a bounded
    # summary for the chain and the full graph for the response and export.
    tool_execution["nested_effects"] = dict(getattr(dres, "nested_effects", None) or {})
    if getattr(dres, "effect_graph", None) is not None:
        tool_execution["effect_graph"] = dres.effect_graph.to_dict()
    if dres.executed:
        # Bounded retention, unbounded verification: the hash covers the
        # full result even when the preview is truncated, so an oversized
        # or hostile tool output cannot inflate the audit chain or the
        # response while still being provable in replay.
        if result_commit is not None:
            return _committed(tool_execution, dres.result, result_commit, tenant, tool_call,
                              proposal_id)
        captured = capture_tool_result(dres.result)
        tool_execution["result"] = captured.preview
        tool_execution["result_envelope"] = captured.to_dict()
    else:
        tool_execution["refusal_reason"] = dres.refusal_reason
    return tool_execution


def _committed(tool_execution: dict[str, Any], raw: Any,
               result_commit: Callable[[Any], tuple[Any, dict[str, Any]]], tenant: str,
               tool_call: ToolCallPort, proposal_id: str) -> dict[str, Any]:
    """Return an executed call's result only after ``result_commit`` succeeded.

    On failure the effect has happened and the result is withheld. The
    exception is not chained or logged with its message: a store error can
    carry the raw result it failed to persist.
    """
    try:
        shown, audit = result_commit(raw)
    except Exception as exc:
        reason = str(getattr(exc, "reason_code", "") or "result_commit_failed")
        governance_event(
            "dispatch.result_commit_failed", level=logging.ERROR,
            tenant_id=tenant, tool_name=tool_call.tool_name,
            proposal_id=proposal_id, detail=reason,
        )
        tool_execution["result_withheld"] = reason
        return tool_execution
    captured = capture_tool_result(shown)
    tool_execution["result"] = captured.preview
    tool_execution["result_envelope"] = captured.to_dict()
    tool_execution["flow_commit"] = dict(audit)
    return tool_execution


def issue_execution_lease(
    *,
    tenant: str,
    principal: str,
    tool_call: ToolCallPort,
    semantic: dict[str, Any],
    now: datetime,
    policy_bundle_hash: str,
    toolspec: dict[str, Any] | None = None,
    proposal_id: str = "",
    grant_jti: str = "",
    task_identity: TaskIdentity | None = None,
    resolved_effect: ResolvedEffect | None = None,
    plan: PlanBinding | None = None,
    capability_set: EffectiveCapabilitySet | None = None,
    flow_binding: tuple[int, str, str] | None = None,
    flow_recipients: frozenset[str] | None = None,
    cam_digest: str = "",
    approver_count: int = 0,
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
        task_identity=task_identity,
        resolved_effect=resolved_effect,
        plan=plan,
        capability_set=capability_set,
        flow_binding=flow_binding,
        flow_recipients=flow_recipients,
        cam_digest=cam_digest,
        approver_count=approver_count,
    )


def _issue_local_lease(
    *,
    tenant: str,
    principal: str,
    tool_call: ToolCallPort,
    semantic: dict[str, Any],
    now: datetime,
    policy_bundle_hash: str,
    toolspec: dict[str, Any] | None,
    proposal_id: str,
    grant_jti: str,
    task_identity: TaskIdentity | None = None,
    resolved_effect: ResolvedEffect | None = None,
    plan: PlanBinding | None = None,
    capability_set: EffectiveCapabilitySet | None = None,
    surface_digest: str = "",
    not_after: datetime | None = None,
    flow_binding: tuple[int, str, str] | None = None,
    flow_recipients: frozenset[str] | None = None,
    cam_digest: str = "",
    approver_count: int = 0,
) -> ExecutionLease:
    from remora.enforcement.flow_recipients import recipients_digest

    execution_context = _execution_context(semantic)
    # ADR-D: the runtime this lease is granted for. An execution context names
    # it (and ExecutionLease.issue takes it from there). Without one, the
    # authority signs its own declared runtime (REMORA_RUNTIME_*), which the
    # executor compares with its own: a strict executor refuses a lease naming
    # no runtime, so without this a deployment with no context provider could
    # execute nothing. An undeclared runtime hashes to "", as before.
    runtime_identity_hash = ""
    if execution_context is None:
        from remora.enforcement.runtime_identity import current_runtime_identity_hash

        runtime_identity_hash = current_runtime_identity_hash()
    expires_at = None
    if not_after is not None:
        expires_at = min(now + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS),
                         not_after).isoformat()
    return ExecutionLease.issue(
            decision="accept",
            tenant_id=tenant,
            actor_identity=principal,
            tool_name=tool_call.tool_name,
            arguments=tool_call.arguments,
            target_environment=tool_call.target_environment,
            policy_bundle_hash=policy_bundle_hash,
            issued_at=now.isoformat(),
            expires_at=expires_at,
            tool_contract_bundle_hash=semantic["tool_contract_bundle_hash"],
            intent_authority_hash=semantic["intent_authority_hash"],
            toolspec_hash=(toolspec or {}).get("hash", ""),
            toolspec_version=int((toolspec or {}).get("version", 0)),
            proposal_id=proposal_id,
            grant_jti=grant_jti,
            task_identity=task_identity,
            resolved_effect=resolved_effect,
            plan=plan,
            capability_set=capability_set,
            execution_context=execution_context,
            runtime_identity_hash=runtime_identity_hash,
            surface_digest=surface_digest,
            flow_epoch=flow_binding[0] if flow_binding is not None else None,
            flow_digest=flow_binding[1] if flow_binding is not None else "",
            resolved_tool_call_hash=flow_binding[2] if flow_binding is not None else "",
            flow_recipients_digest=(recipients_digest(flow_recipients)
                                    if flow_recipients is not None and flow_binding is not None
                                    else ""),
            cam_digest=cam_digest,
            approver_count=approver_count,
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
    tool_call_json: str | None = None,
    authorization_expires_at: datetime | None = None,
    requested_by: str | None = None,
) -> OutboxRow:
    """Record the dispatch intent, inside the caller's transaction when open.

    With a durable backend the row commits with the authorization and rolls
    back with it, so "authorized" and "a dispatch was intended" can never
    disagree. Without one (development), the in-process store records it
    non-atomically — a limitation of that configuration, not of the design.
    """
    # Only the durable adapters can join a transaction; the in-process base
    # class refuses enlistment by design rather than faking the guarantee.
    # UnbackedExecutionOutbox is that same in-process store under another
    # name: a D1 review transaction publishes its connection, and enlisting
    # would reach the base class's NotImplementedError.
    if connection is not None and type(outbox) not in (
            ExecutionOutbox, UnbackedExecutionOutbox):
        return outbox.record_intent_enlisted(
            connection,
            proposal_id=proposal_id,
            tenant_id=tenant,
            item_id=item_id,
            tool_name=tool_name,
            tool_call_hash=tool_call_hash,
            grant_jti=grant_jti,
            tool_call_json=tool_call_json,
            authorization_expires_at=authorization_expires_at,
            requested_by=requested_by,
        )
    return outbox.record_intent(
        proposal_id=proposal_id,
        tenant_id=tenant,
        item_id=item_id,
        tool_name=tool_name,
        tool_call_hash=tool_call_hash,
        grant_jti=grant_jti,
        tool_call_json=tool_call_json,
        authorization_expires_at=authorization_expires_at,
        requested_by=requested_by,
    )
