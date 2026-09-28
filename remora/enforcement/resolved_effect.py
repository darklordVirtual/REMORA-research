# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Bind an authorization to the effect it resolves to, not only to the call (Q7.4).

An ``ExecutionLease`` binds the tool name, the full arguments, the tenant and
the target environment. Between that binding and the side effect sits an
adapter that *resolves* the call: a tool alias to an implementation, a
resource name to a canonical resource, an environment to an endpoint. If the
resolution changes after authorization, every bound field still matches and
the effect lands somewhere nobody approved:

alias
    ``close_wo`` resolved to ``workorder.close`` when approved and to
    ``workorder.delete`` at dispatch.
redirect
    ``WO-1`` resolved to ``tenant-a/WO-1`` when approved and to
    ``tenant-b/WO-1`` at dispatch.
remapping
    the implementation behind ``workorder.close`` was replaced between
    approval and dispatch.

Iyer (2026), *Closed-World Resolution Against Tool Hallucination in LLM
Agents* (arXiv:2609.19425, SHELF-033), resolves a tool reference against a
closed, known set before it is acted on. This module
takes that rule and applies it at both ends: the effect is resolved against a
closed registry when the lease is issued, its digest is signed into the lease
(``resolved_effect_hash``), and the dispatcher resolves again immediately
before execution. A different digest refuses as ``resolved_effect_mismatch``;
a reference the registry does not know refuses as ``unresolved_reference``
instead of falling through to a best guess.

Scope: the registry is deployment configuration. REMORA checks that the
resolution did not change; it does not check that the registry itself is
right, and an adapter that resolves differently from the registry it declared
is outside what this can see.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from remora.errors import RemoraError

__all__ = [
    "ClosedWorldResolver",
    "EffectResolver",
    "ResolvedEffect",
    "UnresolvedReference",
]


class UnresolvedReference(RemoraError):
    """The registry does not know this tool or resource. Refuse, never guess."""

    code = "unresolved_reference"
    category = "enforcement"


@dataclass(frozen=True)
class ResolvedEffect:
    """What a call resolves to at the moment it is resolved.

    ``implementation`` names the code that will run (a module path and
    version, an image digest), ``resource`` the canonical resource it acts
    on, ``effect`` the kind of effect (read, write, delete, send).
    """

    tool_name: str
    implementation: str
    resource: str
    effect: str

    def digest(self) -> str:
        """SHA-256 over the canonical form. Signed into the lease."""
        canonical = json.dumps(
            {"effect": self.effect, "implementation": self.implementation,
             "resource": self.resource, "tool_name": self.tool_name},
            sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


@runtime_checkable
class EffectResolver(Protocol):
    def resolve(self, tool_name: str, arguments: Any,
                target_environment: str) -> ResolvedEffect:
        """Resolve a call. Raises ``UnresolvedReference`` for an unknown one."""


class ClosedWorldResolver:
    """Resolution against a closed registry of tools and resources.

    ``tools`` maps a tool name or alias to ``(implementation, effect)``.
    ``resources`` maps ``(target_environment, reference)`` to the canonical
    resource. ``resource_argument`` names, per tool, the argument holding the
    resource reference; a tool without one acts on its environment as a
    whole. Anything not in the registry raises.

    Immutable. A registry that changes is a new resolver
    (:meth:`with_changes`), which is also what the authority and the executor
    holding different registries looks like.
    """

    def __init__(self, *, tools: Mapping[str, tuple[str, str]],
                 resources: Mapping[tuple[str, str], str],
                 resource_argument: Mapping[str, str]) -> None:
        self._tools = MappingProxyType(dict(tools))
        self._resources = MappingProxyType(dict(resources))
        self._resource_argument = MappingProxyType(dict(resource_argument))

    def with_changes(self, *, tools: Mapping[str, tuple[str, str]] | None = None,
                     resources: Mapping[tuple[str, str], str] | None = None
                     ) -> "ClosedWorldResolver":
        """A resolver with some entries replaced; this one is unchanged."""
        return ClosedWorldResolver(
            tools={**self._tools, **(tools or {})},
            resources={**self._resources, **(resources or {})},
            resource_argument=self._resource_argument)

    def resolve(self, tool_name: str, arguments: Any,
                target_environment: str) -> ResolvedEffect:
        if tool_name not in self._tools:
            raise UnresolvedReference(f"tool {tool_name!r} is not in the registry")
        implementation, effect = self._tools[tool_name]
        argument = self._resource_argument.get(tool_name)
        if argument is None:
            resource = f"env:{target_environment}"
        else:
            reference = (arguments or {}).get(argument) if isinstance(arguments, Mapping) else None
            if not isinstance(reference, str) or not reference:
                raise UnresolvedReference(
                    f"tool {tool_name!r} names no {argument!r} to resolve")
            key = (target_environment, reference)
            if key not in self._resources:
                raise UnresolvedReference(
                    f"resource {reference!r} is not in the registry for "
                    f"{target_environment!r}")
            resource = self._resources[key]
        return ResolvedEffect(tool_name=tool_name, implementation=implementation,
                              resource=resource, effect=effect)
