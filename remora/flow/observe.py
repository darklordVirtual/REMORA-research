# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The flow fields of a policy observation (SDD v1.3 §3.7, IFC-05b).

:func:`flow_observation` is the successor the SDD names for
``_registry_only_observation``'s flow part. It loads the call's flow context,
resolves its handles, runs :func:`remora.flow.check.flow_check` against the
signed ToolSpec's ``flow`` block and returns the ``PolicyObservation`` fields
the decision engine's rungs F1 to F6 read. It never raises on a flow
condition: every one becomes a status, and the engine refuses on it.

Statuses (``FLOW_STATUSES``):

- ``state_unavailable`` (F1): the flow store failed.
- ``context_unknown`` (F2): no ``context_id``, no authenticated principal, or
  a context minted for another tenant or principal. With flow control on a
  caller-chosen id is never accepted (§3.2).
- ``handle_invalid`` (F2): a handle unknown, expired or from another context.
- ``policy_missing`` (F3): the strict profile is on and the call has no
  signed ToolSpec with a ``flow`` block.
- ``not_declared``: outside the strict profile, a call with no ``flow``
  block. No rung fires; the research profile says so instead of refusing.
- ``evaluated``: the check ran; the violation flags hold its verdict.

The status and the two flags are all a decision may show. The verdict's
recipient sets stay here.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final

from remora.flow.check import flow_check
from remora.flow.context import FlowContextState, FlowContextUnknown, FlowStoreUnavailable
from remora.flow.handles import FlowHandleInvalid, HandleStore
from remora.flow.spec import FlowSpec

__all__ = ["FLOW_STATUSES", "flow_observation"]

FLOW_STATUSES: Final = frozenset({
    "state_unavailable", "context_unknown", "handle_invalid", "policy_missing",
    "not_declared", "evaluated",
})

#: Bounds the parent walk; a lineage this deep is a corrupt store.
_MAX_LINEAGE: Final = 64


def _status(status: str) -> dict[str, Any]:
    return {"flow_status": status}


def _lineage(load: Callable[[str], FlowContextState], state: FlowContextState) -> tuple[str, ...]:
    """The context and its ancestors, nearest first (handles are valid in descendants)."""
    ids = [state.context_id]
    parent = state.parent_context_id
    while parent is not None:
        if len(ids) >= _MAX_LINEAGE or parent in ids:
            raise FlowStoreUnavailable("flow context lineage is cyclic or too deep")
        ids.append(parent)
        parent = load(parent).parent_context_id
    return tuple(ids)


def flow_observation(
    *,
    contexts: Any,
    handles: HandleStore | None,
    tenant: str,
    principal: str | None,
    context_id: str | None,
    flow: FlowSpec | None,
    arguments: Mapping[str, Any],
    strict: bool,
    resource_acl: Callable[[str], Iterable[str]] | None = None,
) -> dict[str, Any]:
    """The ``flow_*`` observation fields for one proposed call, with flow control on."""
    if not context_id or not principal:
        return _status("context_unknown")

    def load(cid: str) -> FlowContextState:
        return contexts.load(tenant, principal, cid)

    try:
        state = load(context_id)
        lineage = _lineage(load, state)
    except FlowContextUnknown:
        return _status("context_unknown")
    except FlowStoreUnavailable:
        return _status("state_unavailable")
    if flow is None:
        return _status("policy_missing" if strict else "not_declared")
    if handles is not None:
        try:
            resolution = handles.resolve(tenant, lineage, arguments,
                                         context_label=state.label)
        except FlowHandleInvalid:
            return _status("handle_invalid")
        resolved, value_labels = resolution.args, resolution.value_labels
    else:
        # No handle store: every value is literal text, labelled L_ctx by the check.
        resolved, value_labels = dict(arguments), {}
    verdict = flow_check(flow, context_label=state.label, value_labels=value_labels,
                         resolved_args=resolved, epoch=state.epoch,
                         resource_acl=resource_acl)
    return {
        "flow_status": "evaluated",
        "flow_confidentiality_violation": bool(verdict.conf_viol),
        "flow_integrity_violation": bool(verdict.int_viol) or verdict.ctrl_viol,
        "flow_epoch": verdict.epoch,
        "flow_digest": verdict.digest,
    }
