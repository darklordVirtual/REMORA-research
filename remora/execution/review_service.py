# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Review use-case orchestration: approve / reject (issue #241, slice 6).

Moved from servers/execution_api.py with the module ambients turned into
explicit parameters and HTTP concerns turned into domain errors: the route
layer maps ReviewNotFound to 404 and ReviewConflict to 409. Policy hooks
that are deployment/route concerns (capability checks, profile-specific
approval roles, lifecycle conformance) are injected callables so their
behavior — including what they raise — stays exactly where it was.

The identity rule is unchanged and structural: the recorded reviewer is the
authenticated principal parameter; ``on_behalf_of`` is client-declared,
unverified metadata in the audit record only.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from remora.errors import RemoraError
from remora.execution.ports import (
    AuditChainPort,
    ReviewQueuePort,
    TransactionalAppendPort,
    appender,
    audit_ref,
)
from remora.governance.audit_outbox import encode_key
from remora.governance.execution_identity import (
    ExecutionContextRefused,
    historical_context,
)
from remora.governance.review_queue import ApproverAlreadyApproved, ItemStatus


class ReviewNotFound(RemoraError):
    """The item does not exist for this tenant (route maps to 404)."""

    code = "review_not_found"
    category = "execution"


class SeparationOfDutiesRefused(RemoraError):
    """The approver is the principal that proposed the call (route maps to 403).

    RMR-CR-004. A role check alone let one ``admin`` credential propose a
    call, approve its own escalation and execute it, and the chain then
    recorded a "human" approval. Under a strict profile the approver must be
    a different principal from the proposer, whatever its role.
    """

    code = "separation_of_duties_refused"
    category = "execution"

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def proposer_of(chain: AuditChainPort, tenant: str, proposal_id: str) -> str | None:
    """The authenticated principal that proposed ``proposal_id``.

    Read from the proposal's ``assessed`` event, written by the assess path
    from the authenticated credential, never from a request body. ``None``
    when there is no single such event.
    """
    actors = {
        str(e.payload.get("actor", ""))
        for e in chain.entries(tenant)
        if e.payload.get("proposal_id") == proposal_id
        and e.payload.get("event") == "assessed"
    }
    actors.discard("")
    return actors.pop() if len(actors) == 1 else None


def delegate_of(chain: AuditChainPort, tenant: str, proposal_id: str) -> str:
    """The delegated executor ``proposal_id`` named, or "" when none.

    Read from the same ``assessed`` record as :func:`proposer_of`, where the
    assess path wrote it after admitting the delegation. "" also when the
    record is missing or not unique; execution refuses those separately.
    """
    delegates = {
        str(e.payload.get("delegated_executor") or "")
        for e in chain.entries(tenant)
        if e.payload.get("proposal_id") == proposal_id
        and e.payload.get("event") == "assessed"
    }
    return delegates.pop() if len(delegates) == 1 else ""


@dataclass(frozen=True)
class ApprovalAuthority:
    """The authority an approval is granted under, as the deployment resolved it.

    Returned by the injected ``authorize_approval`` hook after it admitted the
    approver, and stored on the approval, so execution can tell whether the
    requirement that admitted this approver still holds.
    """

    approver_role: str
    required_role: str | None
    policy_hash: str


class ReviewConflict(RemoraError):
    """The item is not in an approvable/rejectable state (route maps to 409).

    ``reason`` is the published, constant string the route returns; the
    exception message is for logs and never reaches a client.
    """

    code = "review_conflict"
    category = "execution"

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        # Generic construction (``raise conflict(str(exc))`` in the service)
        # falls back to the class code, so the wire detail is a constant in
        # every case and the exception text stays server-side.
        self.reason = reason or self.code


def approve_item(
    *,
    tenant: str,
    principal: str,
    item_id: str,
    approval_ttl_seconds: int,
    on_behalf_of: str | None,
    transaction: Callable[[str], AbstractContextManager[ReviewQueuePort]],
    item_tenant: dict[str, str],
    chain: AuditChainPort,
    authorize_approval: Callable[[Any], ApprovalAuthority | None],
    lifecycle_guard: Callable[..., None],
    note_proposal_id: Callable[[Any], None],
    transactional_append: TransactionalAppendPort | None = None,
    require_execution_context: bool = False,
    require_distinct_approver: bool = False,
) -> dict[str, Any]:
    """Record an approval by the authenticated reviewer.

    The tenant-binding check runs INSIDE the transaction: after a process
    restart the item→tenant mirror is rehydrated from the durable store by
    the transaction load, so checking before the load 404s real items
    (review finding 2a). The approval itself runs inside the durable
    transaction (external review 2026-07-27): mutating only in-process
    state was silently discarded when the next transaction reloaded the
    queue — approve→execute was broken in Postgres/SQLite mode.
    """
    try:
        with transaction(tenant) as q:
            if item_tenant.get(item_id) != tenant:
                raise KeyError(item_id)
            item = q.item(item_id)
    except KeyError as exc:
        raise ReviewNotFound(item_id) from exc

    # Profile-specific approval role (review-8 finding): injected — the
    # deployment's policy decides who may approve at this risk tier. What it
    # resolved is kept with the approval, so a later change to that policy
    # voids the approval at execution instead of being inherited by it.
    authority = authorize_approval(item)

    proposal_id = getattr(item.observation, "proposal_id", None)
    proposer = proposer_of(chain, tenant, str(proposal_id or ""))
    delegate = delegate_of(chain, tenant, str(proposal_id or ""))
    if delegate and delegate == principal:
        # Whatever the profile: the identity that will execute must not be
        # the one that approved, or delegation is a way to approve oneself.
        raise SeparationOfDutiesRefused(
            "the approver is the delegated executor of this call",
            reason="approver_is_delegated_executor")
    if require_distinct_approver:
        # Before anything is written: a refused self-approval leaves the item
        # pending for a different principal. Unknown is refused too; a
        # separation that cannot be checked is not separation.
        if proposer is None:
            raise SeparationOfDutiesRefused(
                "the proposing principal could not be established",
                reason="proposer_unknown")
        if proposer == principal:
            raise SeparationOfDutiesRefused(
                "the approver proposed this call", reason="approver_is_proposer")
    if getattr(item, "required_approvers", 1) > 1:
        # Dual control asks for two people besides the one who proposed, in
        # every profile: a proposer counted as one of the two would make it
        # one human and the agent. Unknown is refused, as above.
        if proposer is None:
            raise SeparationOfDutiesRefused(
                "the proposing principal could not be established",
                reason="proposer_unknown")
        if proposer == principal:
            raise SeparationOfDutiesRefused(
                "the approver proposed this call", reason="approver_is_proposer")
    context = historical_context(
        chain, tenant, str(proposal_id or ""), required=require_execution_context)
    if (context.digest() if context is not None else "") != item.observation.execution_context_hash:
        raise ExecutionContextRefused("execution_context_review_mismatch")
    # Deterministic per approval, not per item (RMR-AUD-005). An expired or
    # invalidated approval returns the item to pending, so one item can be
    # approved more than once. A key naming only the item made every later
    # approval collide with the first, and the outbox dropped it. The issue
    # instant identifies this approval and is the same on a retried append.
    key = ""
    append = appender(chain, transactional_append)
    entry: Any = None
    try:
        with transaction(tenant) as q:
            # REM-032 lazy sweep; an expired target then fails q.approve
            # with "not pending", surfaced as a conflict.
            q.expire_due()
            approval = q.approve(
                item_id, approver=principal,
                approval_ttl=timedelta(seconds=approval_ttl_seconds),
                approver_role=authority.approver_role if authority else None,
                required_role=authority.required_role if authority else None,
                approval_policy_hash=authority.policy_hash if authority else None,
            )
            settled = q.item(item_id)
            # Dual control: an approval short of the item's quorum leaves it
            # pending, and is recorded as one approval towards it.
            partial = settled.status is ItemStatus.PENDING
            quorum: dict[str, Any] = {}
            if settled.required_approvers > 1:
                quorum = {
                    "approvals_received": len({a.approver for a in settled.approvals}),
                    "approvals_required": settled.required_approvers,
                    **({} if partial else
                       {"approvers": [a.approver for a in settled.approvals]}),
                }
            event = "approval_recorded" if partial else "approved"
            key = encode_key(tenant, event, item_id,
                             approval.issued_at.isoformat())
            # REM-047: INSIDE the transaction that records the approval. It
            # used to be appended after the commit, so a crash in between left
            # an approved item with no audit event and a verifier unable to
            # tell that from a chain nobody had written to.
            entry = append(tenant, {
                "event": event,
                "proposal_id": proposal_id,
                "actor": principal,
                # Both principals on the approval record, so a reader can
                # check the separation without joining events (RMR-CR-004).
                "proposer": proposer,
                "on_behalf_of": on_behalf_of,
                "item_id": item_id,
                "expires_at": approval.expires_at.isoformat(),
                # The authority the approval was granted under, so the record
                # shows which requirement admitted this approver.
                "approver_role": approval.approver_role,
                "required_role": approval.required_role,
                "approval_policy_hash": approval.approval_policy_hash,
                # The reasons approved; an approved ESCALATE survives
                # re-decision only within them.
                "approved_reasons": (list(approval.approved_reasons)
                                     if approval.approved_reasons is not None
                                     else None),
                # What the reviewer approved includes who may execute it.
                **({"delegated_executor": delegate} if delegate else {}),
                **quorum,
            }, key=key)
    except ApproverAlreadyApproved as exc:
        # Dual control needs a second person; the same one twice is not that.
        raise ReviewConflict(
            "the approver already approved this item",
            reason="approver_already_approved") from exc
    except (KeyError, ValueError) as exc:
        # The queue's own message is not repeated to the caller: it is raised
        # from internal state handling and can name item keys and internal
        # fields, and this reaches an HTTP 409 detail (CodeQL
        # py/stack-trace-exposure). The state the caller can act on is the
        # one this endpoint contracts on, and the original rides the
        # exception chain for the log.
        raise ReviewConflict(
            "item is not in an approvable state", reason="item_not_approvable"
        ) from exc

    # FT-01 conformance, AFTER the queue accepted: the move the queue just
    # performed (pending → approved) must be one the declared machine allows.
    # An approval short of a dual-control quorum moved nothing.
    if not partial:
        lifecycle_guard("REVIEW_PENDING", "human_approval")

    note_proposal_id(proposal_id)
    response: dict[str, Any] = {
        "status": "approval_recorded" if partial else "approved",
        "proposal_id": proposal_id,
        "item_id": item_id,
        "expires_at": approval.expires_at.isoformat(),
        "audit": audit_ref(entry, key=key),
        **{k: v for k, v in quorum.items() if k != "approvers"},
    }
    if delegate:
        response["delegated_executor"] = delegate
    return response


def reject_item(
    *,
    tenant: str,
    principal: str,
    item_id: str,
    reason: str,
    transaction: Callable[[str], AbstractContextManager[ReviewQueuePort]],
    item_tenant: dict[str, str],
    chain: AuditChainPort,
    lifecycle_guard: Callable[..., None],
    note_proposal_id: Callable[[Any], None],
    transactional_append: TransactionalAppendPort | None = None,
) -> dict[str, Any]:
    """Refuse a pending review item, terminally.

    A rejected item can never be approved or executed afterwards — the
    queue refuses any later transition, so a refusal cannot be worked
    around by calling approve again.
    """
    key = encode_key(tenant, "rejected", item_id)
    append = appender(chain, transactional_append)
    entry: Any = None
    try:
        with transaction(tenant) as q:
            if item_tenant.get(item_id) != tenant:
                raise KeyError(item_id)
            q.expire_due()
            item = q.reject(item_id, reviewer=principal, reason=reason)
            # REM-047: the refusal and its audit event commit together. A
            # rejection is terminal, so a lost audit post could never be
            # inferred from a later transition.
            entry = append(tenant, {
                "event": "rejected",
                "proposal_id": getattr(item.observation, "proposal_id", None),
                "actor": principal,
                "item_id": item_id,
                "reason": reason,
            }, key=key)
    except KeyError as exc:
        raise ReviewNotFound(item_id) from exc
    except ValueError as exc:
        # See approve_item: the queue's message stays out of the response.
        raise ReviewConflict(
            "item is not in a rejectable state", reason="item_not_rejectable"
        ) from exc

    lifecycle_guard("REVIEW_PENDING", "human_rejection")
    proposal_id = getattr(item.observation, "proposal_id", None)
    note_proposal_id(proposal_id)
    return {
        "status": "rejected",
        "proposal_id": proposal_id,
        "item_id": item_id,
        "reason": reason,
        "audit": audit_ref(entry, key=key),
    }
