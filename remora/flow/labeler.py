# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Label a tool result and decide what the model sees (SDD v1.3 §3.3, IFC-04).

:meth:`FlowLabeler.label_result` walks a JSON result and gives every node a
label from the ToolSpec ``flow.sources`` block:

- A node uses the rule whose path matches its own path exactly (``[*]``
  matches any index). A node no rule matches gets the defaults: readers
  ``{user_principal}``, integrity ``default_integrity``, rendered as a
  handle. Rules are not inherited: a rule for ``$[*]`` says nothing about
  ``$[*].sender``.
- Readers come from the rule's kind: ``PUBLIC``, ``static``,
  ``from_source_metadata`` (reported by the source system, looked up at the
  node's nearest path that the metadata names), ``resource_acl`` (the ACL of
  the resource an argument names, from the deployment's resolver) or
  ``inherit_args``. ``plus_user`` and ``plus_processors`` add the context's
  user and processors. A reader the source reports that is not a canonical
  principal is dropped, which only narrows the label.
- Every label is joined with the call's argument labels: data that went in
  can come out.

Rendering. A node is shown by value only when its rule says ``BY_VALUE`` (or
it has no rule and its label is ⊥) and its label flows to the model
principal (§3.2.1). Otherwise the node and everything under it becomes one
handle, labelled with the join of every label in that subtree. A container
shown by value reveals its structure (its length, its keys, which children
are null), so its own label joins the raise, except the length of a list
whose rule declares ``length_public``. Every leaf shown by value joins the
raise.

The labeler is pure. It returns the rendered result, the label to raise the
context by, and the handle records to store; committing the raise and the
handles before the rendered result is returned is the dispatcher's job
(IFC-04b, §3.3.2).
"""
from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from remora.capabilities.resource import ResourceRefused, canonical_resource
from remora.flow.context import FlowDispatchFenceLost
from remora.flow.handles import HandleRecord, handle_token, new_handle_id
from remora.flow.label import (
    BOTTOM,
    PUBLIC,
    Label,
    flows_to,
    join,
    join_all,
)
from remora.flow.render import handle_ref
from remora.flow.spec import FieldRule, FlowSpec

__all__ = [
    "CommittedFlowResult",
    "FlowCommitFailed",
    "FlowLabeler",
    "FlowLabelingError",
    "LabeledResult",
    "LabelingContext",
    "commit_labeled_result",
    "verify_flow_at_dispatch",
]

#: Type tag of a handle whose field declares no type.
UNDECLARED_TYPE = "value"


class FlowLabelingError(ValueError):
    """A result the labeler cannot give labels to, such as a non-JSON value."""


@dataclass(frozen=True)
class LabelingContext:
    tenant_id: str
    context_id: str
    user_principal: str
    model_principal: str
    processors: frozenset[str]
    proposal_id: str


@dataclass(frozen=True)
class LabeledResult:
    #: What the model receives: values and handle references.
    rendered: Any
    #: Join of every label shown by value; the context label rises by it.
    raise_label: Label
    #: Records to store before ``rendered`` is returned.
    handles: tuple[HandleRecord, ...] = field(default=())


# A concrete path is a tuple of steps: ("k", key) or ("i", index).
_Step = tuple[str, Any]


def _pattern_steps(pattern: str) -> tuple[str, ...]:
    """'$[*].a.b' -> ('[*]', 'a', 'b')."""
    out: list[str] = []
    rest = pattern[1:]
    while rest:
        if rest.startswith("[*]"):
            out.append("[*]")
            rest = rest[3:]
        else:
            name = rest[1:].split(".", 1)[0].split("[", 1)[0]
            out.append(name)
            rest = rest[1 + len(name):]
    return tuple(out)


def _matches(pattern: tuple[str, ...], path: tuple[_Step, ...]) -> bool:
    if len(pattern) != len(path):
        return False
    for p, (kind, value) in zip(pattern, path, strict=True):
        if p == "[*]":
            if kind != "i":
                return False
        elif kind != "k" or value != p:
            return False
    return True


def _path_text(path: tuple[_Step, ...]) -> str:
    out = "$"
    for kind, value in path:
        if kind == "i":
            out += f"[{value}]"
        elif value.isidentifier():
            out += f".{value}"
        else:
            out += f"[{json.dumps(value, ensure_ascii=False)}]"
    return out


def _check_json(value: Any) -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FlowLabelingError("a result holds a non-finite number")
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            _check_json(v)
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise FlowLabelingError("a result object has a non-string key")
            _check_json(v)
        return
    raise FlowLabelingError(f"a result holds a {type(value).__name__}, not a JSON value")


class FlowLabeler:
    def __init__(self, *, resource_acl: Callable[[str], Iterable[str]] | None = None,
                 clock: Callable[[], float] = time.time, ttl_seconds: float = 3600.0) -> None:
        self._resource_acl = resource_acl
        self._clock = clock
        self._ttl = ttl_seconds

    def label_result(self, flow: FlowSpec, ctx: LabelingContext, *,
                     resolved_args: Mapping[str, Any], arg_labels: Mapping[str, Label],
                     raw_result: Any,
                     source_metadata: Mapping[str, Mapping[str, Iterable[str]]] | None = None,
                     ) -> LabeledResult:
        _check_json(raw_result)
        sources = flow.sources
        rules = [(_pattern_steps(r.path), r) for r in sources.fields]
        args_label = join_all(arg_labels.values())
        metadata = source_metadata or {}
        expires = self._clock() + self._ttl
        minted: list[HandleRecord] = []
        raised = [BOTTOM]

        def rule_for(path: tuple[_Step, ...]) -> FieldRule | None:
            for pattern, rule in rules:
                if _matches(pattern, path):
                    return rule
            return None

        def canonical(principals: Iterable[str]) -> set[str]:
            # Exact principals only. A subtree pattern from a source would
            # widen the label to principals the source never named.
            out = set()
            for p in principals:
                try:
                    out.add(canonical_resource(p))
                except (ResourceRefused, TypeError, AttributeError):
                    continue  # not a principal: dropping it only narrows
            return out

        def metadata_readers(name: str, path: tuple[_Step, ...]) -> set[str]:
            table = metadata.get(name, {})
            for depth in range(len(path), -1, -1):
                key = _path_text(path[:depth])
                if key in table:
                    return canonical(table[key])
            return set()

        def label_of(path: tuple[_Step, ...], rule: FieldRule | None) -> Label:
            integrity = sources.default_integrity
            readers: Any = {ctx.user_principal}
            if rule is not None:
                integrity = rule.integrity or sources.default_integrity
                r = rule.readers
                if r.kind == "public":
                    readers = PUBLIC
                elif r.kind == "static":
                    readers = set(r.values)
                elif r.kind == "from_source_metadata":
                    readers = set()
                    for name in r.values:
                        readers |= metadata_readers(name, path)
                elif r.kind == "resource_acl":
                    resource = resolved_args.get(r.values[0])
                    readers = (canonical(self._resource_acl(resource))
                               if self._resource_acl is not None and isinstance(resource, str)
                               else set())
                elif r.kind == "inherit_args":
                    readers = (args_label.readers if arg_labels else {ctx.user_principal})
                if readers is not PUBLIC:
                    readers = set(readers)
                    if r.plus_user:
                        readers.add(ctx.user_principal)
                    if r.plus_processors:
                        readers |= ctx.processors
            return join(Label(readers, integrity), args_label)

        def subtree_label(node: Any, path: tuple[_Step, ...]) -> Label:
            own = label_of(path, rule_for(path))
            if isinstance(node, dict):
                return join_all((subtree_label(v, (*path, ("k", k))) for k, v in node.items()),
                                start=own)
            if isinstance(node, (list, tuple)):
                return join_all((subtree_label(v, (*path, ("i", i)))
                                 for i, v in enumerate(node)), start=own)
            return own

        def as_handle(node: Any, path: tuple[_Step, ...], rule: FieldRule | None) -> dict:
            record = HandleRecord(
                handle_id=new_handle_id(), tenant_id=ctx.tenant_id, context_id=ctx.context_id,
                value=json.loads(json.dumps(node)), label=subtree_label(node, path),
                type_tag=(rule.type if rule is not None and rule.type else UNDECLARED_TYPE),
                created_by_proposal=ctx.proposal_id, expires_at=expires)
            minted.append(record)
            return handle_ref(handle_token(record.handle_id), record.type_tag)

        def render(node: Any, path: tuple[_Step, ...]) -> Any:
            rule = rule_for(path)
            label = label_of(path, rule)
            mode = (rule.return_mode if rule is not None and rule.return_mode
                    else ("BY_VALUE" if label == BOTTOM else sources.default_return_mode))
            if mode != "BY_VALUE" or not flows_to(label, ctx.model_principal):
                return as_handle(node, path, rule)
            if isinstance(node, dict):
                raised.append(label)
                return {k: render(v, (*path, ("k", k))) for k, v in node.items()}
            if isinstance(node, (list, tuple)):
                if not (rule is not None and rule.length_public):
                    raised.append(label)
                return [render(v, (*path, ("i", i))) for i, v in enumerate(node)]
            raised.append(label)
            return node

        rendered = render(raw_result, ())
        return LabeledResult(rendered=rendered, raise_label=join_all(raised),
                             handles=tuple(minted))


class FlowCommitFailed(RuntimeError):
    """Persisting handles or raising the context label failed (SDD v2 AR-017).

    Never carries raw tool output or rendered values in its message or
    attributes so an exception, log or stream cannot leak uncommitted data.
    """

    def __init__(self, reason_code: str = "flow_result_commit_failed") -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class CommittedFlowResult:
    """Agent-facing rendered result separated from raw attestation digest (SDD v2 AR-017)."""

    rendered_result: Any
    raw_result_sha256: str
    new_epoch: int
    new_label: Label
    minted_handle_ids: tuple[str, ...]


def commit_labeled_result(
    labeler: FlowLabeler,
    flow: FlowSpec,
    *,
    contexts: Any,
    handles: Any,
    tenant_id: str,
    principal: str,
    context_id: str,
    proposal_id: str,
    arguments: Mapping[str, Any],
    raw_result: Any,
    source_metadata: Mapping[str, Mapping[str, Iterable[str]]] | None = None,
    expected_epoch: int | None = None,
    dispatch_id: str | None = None,
) -> CommittedFlowResult:
    """Compute labels, persist handles and context raise BEFORE returning
    ``rendered_result`` to the agent (SDD v2 WP-04 / AR-017, IFC-04b).

    If persistence fails, raises :class:`FlowCommitFailed` with no raw or
    rendered payload attached. With *expected_epoch* (the epoch the dispatch
    check passed on), a context whose label moved in between is refused as
    ``flow_epoch_changed_during_dispatch``: the call ran, and its result is
    not released under a flow decision made on a stale label. With
    *dispatch_id* (the dispatch fence the call holds, IFC-06), a fence that
    is no longer held unexpired is refused as ``flow_dispatch_fence_expired``:
    another proposal may have run in the context while the hold had lapsed,
    so the result is not released as if the call had run alone.
    """
    import hashlib
    import time

    from remora.flow.observe import _lineage

    failed = False
    reason: str | None = None
    updated: Any = None
    try:
        state = contexts.load(tenant_id, principal, context_id)
        if expected_epoch is not None and state.epoch != expected_epoch:
            reason = "flow_epoch_changed_during_dispatch"
            raise FlowCommitFailed(reason)
        if dispatch_id is not None:
            now = time.time()
            if not any(o.dispatch_id == dispatch_id and o.expires_at > now
                       for o in state.open_dispatches):
                reason = "flow_dispatch_fence_expired"
                raise FlowCommitFailed(reason)
        lineage = _lineage(lambda cid: contexts.load(tenant_id, principal, cid), state)
        if handles is not None:
            res = handles.resolve(tenant_id, lineage, arguments, context_label=state.label)
            resolved_args, arg_labels = res.args, res.value_labels
        else:
            resolved_args, arg_labels = dict(arguments), {}
        ctx = LabelingContext(
            tenant_id=tenant_id,
            context_id=context_id,
            user_principal=state.user_principal,
            model_principal=state.model_principal,
            processors=state.processors,
            proposal_id=proposal_id,
        )
        labeled = labeler.label_result(
            flow,
            ctx,
            resolved_args=resolved_args,
            arg_labels=arg_labels,
            raw_result=raw_result,
            source_metadata=source_metadata,
        )
        raw_bytes = json.dumps(raw_result, sort_keys=True, separators=(",", ":")).encode("utf-8")
        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        if handles is not None and labeled.handles:
            handles.put_all(labeled.handles)
        if dispatch_id is None:
            updated = contexts.raise_label(tenant_id, principal, context_id, labeled.raise_label)
        else:
            # The final ownership check and the raise are one compare-and-swap
            # in the store: the append lands only if the fence is still held
            # unexpired in the state it is conditioned on.
            updated = contexts.raise_label(tenant_id, principal, context_id, labeled.raise_label,
                                           dispatch_id=dispatch_id)
    except FlowDispatchFenceLost:
        failed = True
        reason = "flow_dispatch_fence_expired"
    except Exception:
        failed = True
    # Raise outside the handler: neither cause nor implicit exception context
    # may retain a store exception containing raw tool data.
    if reason is not None:
        raise FlowCommitFailed(reason) from None
    if failed or updated is None:
        raise FlowCommitFailed("flow_result_commit_failed") from None
    return CommittedFlowResult(
        rendered_result=labeled.rendered,
        raw_result_sha256=raw_sha256,
        new_epoch=updated.epoch,
        new_label=updated.label,
        minted_handle_ids=tuple(h.handle_id for h in labeled.handles),
    )


def verify_flow_at_dispatch(
    *,
    contexts: Any,
    handles: Any | None,
    tenant_id: str,
    principal: str,
    context_id: str,
    flow: FlowSpec,
    arguments: Mapping[str, Any],
    expected_epoch: int,
    expected_digest: str,
    resource_acl: Callable[[str], Iterable[str]] | None = None,
) -> tuple[bool, str, dict[str, Any], int]:
    """Re-verify ``flow_epoch``, ``flow_digest`` and resolved arguments right
    before dispatch (SDD v2 WP-04 / AR-018, IFC-06).

    Returns ``(ok, reason, resolved_arguments, seq)``. ``seq`` is the stream
    sequence of the context state the verdict was computed on (0 on a
    refusal); the dispatch fence is taken at exactly that sequence
    (``FlowContextStore.begin_dispatch(expected_seq=...)``), so a context that
    moved after the check refuses instead of dispatching on a stale verdict.
    """
    from remora.flow.check import flow_check
    from remora.flow.observe import _lineage

    try:
        state = contexts.load(tenant_id, principal, context_id)
        lineage = _lineage(lambda cid: contexts.load(tenant_id, principal, cid), state)
    except Exception:
        return False, "flow_state_unavailable", {}, 0
    if state.epoch != expected_epoch:
        return False, "flow_epoch_changed", {}, 0
    if handles is not None:
        try:
            res = handles.resolve(tenant_id, lineage, arguments, context_label=state.label)
            resolved_args, value_labels = res.args, res.value_labels
        except Exception:
            return False, "flow_handle_invalid", {}, 0
    else:
        resolved_args, value_labels = dict(arguments), {}
    verdict = flow_check(
        flow,
        context_label=state.label,
        value_labels=value_labels,
        resolved_args=resolved_args,
        epoch=state.epoch,
        resource_acl=resource_acl,
    )
    if verdict.digest != expected_digest:
        return False, "flow_digest_changed", {}, 0
    if not verdict.clean:
        return False, "flow_violation_at_dispatch", {}, 0
    return True, "ok", resolved_args, state.seq

