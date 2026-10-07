# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""BindingPolicy: what a strict deployment requires to be bound (CR-006, A2).

Most lease bindings used to be configuration-conditional. The lease signed a
task identity, a capability digest, a resolved effect or a surface, but
whether anything compared them depended on separate flags, resolvers and
observers, and their absence was logged rather than refused. A deployment
could believe it had a binding it did not have.

A BindingPolicy is one explicit, digestible declaration of every binding, in
exactly one of three states:

- ``REQUIRED``: compared at dispatch. The deployment must have the comparator
  (resolver, observer, policy file); a strict startup refuses without it.
- ``NOT_APPLICABLE``: the binding has no meaning for this tool. Allowed only
  per tool, only for ``resolved_effect``, and only for a tool whose signed
  ToolSpec declares a read-only action. "No resolver configured" is never
  NOT_APPLICABLE: a consequential tool must have a real resolver.
- ``UNVERIFIABLE``: the deployment states it cannot verify this binding. It is
  recorded in startup evidence as a declared gap, never silently skipped, and
  is allowed only for bindings outside the core set.

A binding that is missing, or set to anything else, is a startup failure:
implicit is not a state.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

__all__ = [
    "BINDINGS",
    "CORE_BINDINGS",
    "SCHEMA",
    "STATES",
    "BindingPolicy",
    "BindingPolicyError",
    "load_binding_policy",
]

SCHEMA = "remora-binding-policy/v1"

#: Every binding a policy must state, in the order the matrix documents them.
BINDINGS: tuple[str, ...] = (
    "exact_call", "toolspec", "tenant", "task_identity", "capability_set",
    "resolved_effect", "runtime_surface", "actor", "audience",
    "effect_mediation",
)
STATES = frozenset({"REQUIRED", "NOT_APPLICABLE", "UNVERIFIABLE"})

#: Bindings a strict profile requires outright. exact_call and tenant are
#: always compared by the dispatcher; the others have their comparator checked
#: at startup. resolved_effect is core too: a consequential tool must have a
#: real resolver, so the only escape is per-tool NOT_APPLICABLE for a
#: read-only tool.
CORE_BINDINGS = frozenset({
    "exact_call", "toolspec", "tenant", "resolved_effect", "runtime_surface",
    "actor", "audience", "effect_mediation",
})

#: Per-tool overrides the policy may express, and the value each may take.
_PER_TOOL = {"resolved_effect": frozenset({"NOT_APPLICABLE"})}


class BindingPolicyError(ValueError):
    """The policy is malformed, implicit or weaker than the profile allows."""


@dataclass(frozen=True)
class BindingPolicy:
    """A validated BindingPolicy. ``digest`` identifies it in evidence."""

    bindings: Mapping[str, str]
    tools: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    digest: str = ""

    def state(self, binding: str, tool_name: str | None = None) -> str:
        if tool_name is not None:
            override = self.tools.get(tool_name, {}).get(binding)
            if override is not None:
                return override
        return self.bindings[binding]

    def required(self, binding: str, tool_name: str | None = None) -> bool:
        return self.state(binding, tool_name) == "REQUIRED"

    def unverifiable(self) -> tuple[str, ...]:
        return tuple(b for b in BINDINGS if self.bindings[b] == "UNVERIFIABLE")

    def not_applicable_tools(self, binding: str) -> tuple[str, ...]:
        return tuple(sorted(t for t, o in self.tools.items()
                            if o.get(binding) == "NOT_APPLICABLE"))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "BindingPolicy":
        problems: list[str] = []
        if raw.get("schema") != SCHEMA:
            problems.append(f"schema must be {SCHEMA!r}, got {raw.get('schema')!r}")
        declared = raw.get("bindings")
        if not isinstance(declared, Mapping):
            raise BindingPolicyError("bindings must be a mapping of every binding to a state")
        bindings: dict[str, str] = {}
        for name in BINDINGS:
            value = declared.get(name)
            if value is None:
                problems.append(f"{name}: missing (implicit is not a state)")
            elif value not in STATES:
                problems.append(f"{name}: {value!r} is not one of {sorted(STATES)}")
            elif value == "NOT_APPLICABLE":
                problems.append(f"{name}: NOT_APPLICABLE is per tool, never deployment-wide")
            elif value == "UNVERIFIABLE" and name in CORE_BINDINGS:
                problems.append(f"{name}: a core binding must be REQUIRED, not UNVERIFIABLE")
            else:
                bindings[name] = value
        unknown = set(declared) - set(BINDINGS)
        if unknown:
            problems.append(f"unknown bindings: {sorted(unknown)}")
        tools: dict[str, dict[str, str]] = {}
        for tool, overrides in (raw.get("tools") or {}).items():
            if not isinstance(overrides, Mapping):
                problems.append(f"tools.{tool}: overrides must be a mapping")
                continue
            for binding, value in overrides.items():
                allowed = _PER_TOOL.get(binding)
                if allowed is None:
                    problems.append(f"tools.{tool}.{binding}: no per-tool override exists")
                elif value not in allowed:
                    problems.append(f"tools.{tool}.{binding}: {value!r} not in {sorted(allowed)}")
            tools[str(tool)] = dict(overrides)
        if problems:
            raise BindingPolicyError("binding policy refused: " + "; ".join(problems))
        canonical = json.dumps({"schema": SCHEMA, "bindings": bindings, "tools": tools},
                               sort_keys=True, separators=(",", ":"))
        return cls(
            bindings=MappingProxyType(bindings),
            tools=MappingProxyType({t: MappingProxyType(o) for t, o in tools.items()}),
            digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )

    def check_read_only_exemptions(self, action_types: Mapping[str, str],
                                   read_only: Iterable[str]) -> list[str]:
        """Each NOT_APPLICABLE tool must be signed as read-only (fail closed)."""
        ro = {a.strip().lower() for a in read_only}
        problems = []
        for tool in self.not_applicable_tools("resolved_effect"):
            declared = action_types.get(tool)
            if declared is None:
                problems.append(f"tools.{tool}: not in the signed ToolSpec bundle")
            elif declared.strip().lower() not in ro:
                problems.append(
                    f"tools.{tool}: resolved_effect NOT_APPLICABLE needs a read-only "
                    f"action, the signed spec declares {declared!r}")
        return problems


def load_binding_policy(path: str | Path) -> BindingPolicy:
    """Load a policy from YAML or JSON. Any problem is a BindingPolicyError."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        import yaml

        raw = yaml.safe_load(text)
    except ImportError:  # pragma: no cover - PyYAML is a core dependency
        raw = json.loads(text)
    if not isinstance(raw, Mapping):
        raise BindingPolicyError("a binding policy is a mapping")
    return BindingPolicy.from_mapping(raw)
