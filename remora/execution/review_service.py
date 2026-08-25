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
from datetime import timedelta
from typing import Any


class ReviewNotFound(Exception):
    """The item does not exist for this tenant (route maps to 404)."""


class ReviewConflict(Exception):
    """The item is not in an approvable/rejectable state (route maps to 409)."""


def approve_item(
    *,
    tenant: str,
    principal: str,
    item_id: str,
    approval_ttl_seconds: int,
    on_behalf_of: str | None,
    transaction: Callable[[str], Any],
    item_tenant: dict[str, str],
    chain: Any,
    authorize_approval: Callable[[Any], None],
    lifecycle_guard: Callable[..., None],
    note_proposal_id: Callable[[Any], None],
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
    # deployment's policy decides who may approve at this risk tier.
    authorize_approval(item)

    try:
        with transaction(tenant) as q:
            # REM-032 lazy sweep; an expired target then fails q.approve
            # with "not pending", surfaced as a conflict.
            q.expire_due()
            approval = q.approve(
                item_id, approver=principal,
                approval_ttl=timedelta(seconds=approval_ttl_seconds),
            )
    except (KeyError, ValueError) as exc:
        # The queue's own message is not repeated to the caller: it is raised
        # from internal state handling and can name item keys and internal
        # fields, and this reaches an HTTP 409 detail (CodeQL
        # py/stack-trace-exposure). The state the caller can act on is the
        # one this endpoint contracts on, and the original rides the
        # exception chain for the log.
        raise ReviewConflict(
            "item is not in an approvable state"
        ) from exc

    # FT-01 conformance, AFTER the queue accepted: the move the queue just
    # performed (pending → approved) must be one the declared machine allows.
    lifecycle_guard("REVIEW_PENDING", "human_approval")

    proposal_id = getattr(item.observation, "proposal_id", None)
    note_proposal_id(proposal_id)
    entry = chain.append(tenant, {
        "event": "approved",
        "proposal_id": proposal_id,
        "actor": principal,
        "on_behalf_of": on_behalf_of,
        "item_id": item_id,
        "expires_at": approval.expires_at.isoformat(),
    })
    return {
        "status": "approved",
        "proposal_id": proposal_id,
        "item_id": item_id,
        "expires_at": approval.expires_at.isoformat(),
        "audit": {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash},
    }


def reject_item(
    *,
    tenant: str,
    principal: str,
    item_id: str,
    reason: str,
    transaction: Callable[[str], Any],
    item_tenant: dict[str, str],
    chain: Any,
    lifecycle_guard: Callable[..., None],
    note_proposal_id: Callable[[Any], None],
) -> dict[str, Any]:
    """Refuse a pending review item, terminally.

    A rejected item can never be approved or executed afterwards — the
    queue refuses any later transition, so a refusal cannot be worked
    around by calling approve again.
    """
    try:
        with transaction(tenant) as q:
            if item_tenant.get(item_id) != tenant:
                raise KeyError(item_id)
            q.expire_due()
            item = q.reject(item_id, reviewer=principal, reason=reason)
    except KeyError as exc:
        raise ReviewNotFound(item_id) from exc
    except ValueError as exc:
        # See approve_item: the queue's message stays out of the response.
        raise ReviewConflict(
            "item is not in a rejectable state"
        ) from exc

    lifecycle_guard("REVIEW_PENDING", "human_rejection")
    proposal_id = getattr(item.observation, "proposal_id", None)
    note_proposal_id(proposal_id)
    entry = chain.append(tenant, {
        "event": "rejected",
        "proposal_id": proposal_id,
        "actor": principal,
        "item_id": item_id,
        "reason": reason,
    })
    return {
        "status": "rejected",
        "proposal_id": proposal_id,
        "item_id": item_id,
        "reason": reason,
        "audit": {"sequence_no": entry.sequence_no, "entry_hash": entry.entry_hash},
    }
