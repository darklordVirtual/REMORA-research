# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Recipients and the flow check (SDD v1.3 §3.5, IFC-05).

:func:`recipients` computes who receives a call's payload from the ToolSpec
``flow.sink`` block and the *resolved* arguments (handles already
substituted). A tool that runs outside the TCB adds its provider. An
argument that cannot be mapped to a canonical principal (a display-name
email, a URL with user information or a non-http scheme, an IBAN that does
not parse, a resource with no ACL resolver) is returned as unresolved; the
check counts it as a confidentiality violation, because no reader set can be
shown to contain it. A rule that derives recipients from arguments, all of
which are null, empty or missing, names every argument it reads as
unresolved: such a call would leave the tool to choose its recipients.

:func:`flow_check` is the SDD's pseudo-code::

    R          = recipients(spec, resolved_args)
    L_payload  = L_ctx ⊔ ⨆ { value_labels[f] : f ∈ payload_args }
    conf_viol  = { r ∈ R : not flows_to(L_payload, r) } minus declassified
    int_viol   = { f ∈ integrity_required : value_labels[f] UNTRUSTED
                   and not endorsed(f, value) } minus integrity_granted
    ctrl_viol  = control_integrity_required and L_ctx UNTRUSTED and not granted
    role_viol  = { f ∈ integrity_required : f holds a parameter handle whose
                   role is not in roles_accepted[f] }

A field with no value label counts as literal text and gets ``L_ctx``. A
parameter handle in a field that declares no accepted roles is a role
violation. ``digest`` binds the violation sets and ``L_payload`` (§3.8), so
new data joining the payload changes it even when the same rungs fire; the
epoch is not part of it.

The check is pure. Mapping a verdict to a decision (rungs F1 to F6) is the
decision engine's job.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

from remora.capabilities.resource import ResourceRefused, canonical_resource
from remora.flow.label import PUBLIC, Integrity, Label, canonical_bytes, flows_to, join_all
from remora.flow.spec import FlowSpec

__all__ = ["PUBLIC_RECIPIENT", "FlowVerdict", "flow_check", "recipients"]

#: The recipient of a call whose target a resource ACL resolver reports as
#: world-readable (it answers :data:`remora.flow.label.PUBLIC`). It is not a
#: canonical resource, so :func:`remora.flow.label.flows_to` admits only
#: PUBLIC data to it: no reader set, however written, contains it.
PUBLIC_RECIPIENT: Final = "public://*"

_IBAN: Final = re.compile(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}")
_DIGEST_DOMAIN: Final = b"REMORA/FLOW-VERDICT/v1\x00"


@dataclass(frozen=True)
class FlowVerdict:
    #: Recipients the payload may not reach, and unresolved arguments as
    #: ``unresolved:<argument>``.
    conf_viol: frozenset[str]
    #: ``integrity_required`` fields that are untrusted or hold a parameter
    #: of the wrong role.
    int_viol: frozenset[str]
    ctrl_viol: bool
    epoch: int
    digest: str
    payload_label: Label

    @property
    def clean(self) -> bool:
        return not self.conf_viol and not self.int_viol and not self.ctrl_viol


def _values(value: Any) -> list[Any]:
    """One argument value, or each element of a list of them."""
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _email(value: Any) -> str:
    if not isinstance(value, str) or value.count("@") != 1:
        raise ResourceRefused("not a bare email address")
    local, domain = value.split("@")
    if not local or not domain:
        raise ResourceRefused("not a bare email address")
    return canonical_resource(f"email://{domain}/{local}")


def _url_host(value: Any) -> str:
    if not isinstance(value, str):
        raise ResourceRefused("not a URL")
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ResourceRefused("not an http(s) URL with a host")
    if parts.username is not None or parts.password is not None:
        raise ResourceRefused("a URL with user information names two hosts")
    return canonical_resource(f"ext://{parts.hostname}")


def _iban(value: Any) -> str:
    if not isinstance(value, str):
        raise ResourceRefused("not an IBAN")
    compact = value.replace(" ", "").upper()
    if not _IBAN.fullmatch(compact):
        raise ResourceRefused("not an IBAN")
    return canonical_resource(f"iban://{compact}")


def recipients(flow: FlowSpec, resolved_args: Mapping[str, Any], *,
               resource_acl: Callable[[str], Iterable[str]] | None = None,
               ) -> tuple[frozenset[str], tuple[str, ...]]:
    """``(recipients, unresolved arguments)`` for one resolved call."""
    rule = flow.sink.recipients
    found: set[str] = set()
    unresolved: list[str] = []
    seen_values = False

    def add(argument: str, compute: Callable[[Any], Iterable[str]]) -> None:
        nonlocal seen_values
        for value in _values(resolved_args.get(argument)):
            seen_values = True
            try:
                found.update(compute(value))
            except (ResourceRefused, TypeError, ValueError):
                unresolved.append(argument)

    if rule.kind == "from_args":
        for argument, kind in rule.from_args:
            add(argument, (lambda v: [_email(v)]) if kind == "email"
                else (lambda v: [canonical_resource(v)]))
    elif rule.kind == "url_host_of":
        add(str(rule.argument), lambda v: [_url_host(v)])
    elif rule.kind == "iban_of":
        add(str(rule.argument), lambda v: [_iban(v)])
    elif rule.kind == "resource_of":
        def acl(value: Any) -> list[str]:
            if resource_acl is None:
                raise ResourceRefused("no resource ACL resolver")
            readers = resource_acl(canonical_resource(value))
            if readers is PUBLIC:
                return [PUBLIC_RECIPIENT]
            return [canonical_resource(p) for p in readers]
        add(str(rule.argument), acl)
    elif rule.kind == "static":
        found.update(rule.static)
    if rule.kind not in ("none", "static") and not seen_values:
        # A rule derived from arguments that hold no value names no one, so
        # the tool decides where the payload goes (RMR-AUD-007). An empty
        # rule is unresolved, not "nobody"; one absent argument (a cc
        # beside a to) is not.
        unresolved.extend(rule.arguments())
    if flow.provider != "tcb":
        found.add(flow.provider)
    return frozenset(found), tuple(dict.fromkeys(unresolved))


def flow_check(flow: FlowSpec, *, context_label: Label, value_labels: Mapping[str, Label],
               resolved_args: Mapping[str, Any], epoch: int,
               resource_acl: Callable[[str], Iterable[str]] | None = None,
               declassified: frozenset[str] = frozenset(),
               integrity_granted: frozenset[str] = frozenset(),
               control_granted: bool = False,
               endorsed: Callable[[str, Any], bool] | None = None,
               parameter_roles: Mapping[str, str] | None = None) -> FlowVerdict:
    """The :class:`FlowVerdict` for one resolved call in one context."""
    sink = flow.sink
    roles = parameter_roles or {}
    accepted = dict(sink.roles_accepted)

    def label(field_name: str) -> Label:
        return value_labels.get(field_name, context_label)

    payload_fields = sink.payload_args if sink.payload_args is not None else tuple(resolved_args)
    payload = join_all((label(f) for f in payload_fields if f in resolved_args),
                       start=context_label)

    reached, unresolved = recipients(flow, resolved_args, resource_acl=resource_acl)
    conf = {r for r in reached if not flows_to(payload, r)} - declassified
    conf |= {f"unresolved:{a}" for a in unresolved}

    integrity: set[str] = set()
    for f in sink.integrity_required:
        if f not in resolved_args or resolved_args[f] is None:
            continue
        untrusted = label(f).integrity is Integrity.UNTRUSTED and not (
            endorsed is not None and endorsed(f, resolved_args[f]))
        wrong_role = f in roles and roles[f] not in accepted.get(f, ())
        if (untrusted and f not in integrity_granted) or wrong_role:
            integrity.add(f)

    control = (sink.control_integrity_required
               and context_label.integrity is Integrity.UNTRUSTED and not control_granted)

    digest = hashlib.sha256(
        _DIGEST_DOMAIN
        + json.dumps({"conf": sorted(conf), "int": sorted(integrity), "ctrl": bool(control)},
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\x00" + canonical_bytes(payload)).hexdigest()
    return FlowVerdict(conf_viol=frozenset(conf), int_viol=frozenset(integrity),
                       ctrl_viol=bool(control), epoch=epoch, digest=digest,
                       payload_label=payload)
