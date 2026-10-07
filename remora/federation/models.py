# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The transport-independent Native Federation Action Envelope (SDD section 5).

One REMORA authorization, described once, before any transport sees it. A
field this workflow does not have is ``None`` and is listed in
``unavailable``: it is never invented, so a projection can tell "absent"
from "empty".
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from remora.federation.canonical import CanonicalArguments, canonical_arguments
from remora.policy.observation import _canonical_json

__all__ = ["ACTION_SCHEMA", "NativeFederationAction", "exact_utc_ms"]

ACTION_SCHEMA = "remora-federation-action-v1"
_EXACT_UTC_MS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

_AUTHORITY_FIELDS = ("authorization_id", "principal", "tenant", "target", "resource",
                     "valid_until", "lease_id")
_CONTEXT_FIELDS = ("policy_digest", "toolspec_digest", "context_digest")
_EVIDENCE_FIELDS = ("authorization_digest", "native_claims_digest")


def exact_utc_ms(value: str) -> str:
    """Refuse any instant not in the exact UTC millisecond form transports compare."""
    if not _EXACT_UTC_MS.match(value):
        raise ValueError(f"valid_until {value!r} is not YYYY-MM-DDTHH:MM:SS.sssZ")
    return value


@dataclass(frozen=True)
class NativeFederationAction:
    operation_id: str
    workflow_id: str
    tool: str
    arguments: Any
    authority: dict[str, str | None]
    execution_context: dict[str, str | None] = field(default_factory=dict)
    evidence: dict[str, str | None] = field(default_factory=dict)
    tool_definition_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.operation_id or not self.workflow_id or not self.tool:
            raise ValueError("operation_id, workflow_id and tool are required")
        unknown = (set(self.authority) - set(_AUTHORITY_FIELDS)
                   | set(self.execution_context) - set(_CONTEXT_FIELDS)
                   | set(self.evidence) - set(_EVIDENCE_FIELDS))
        if unknown:
            raise ValueError(f"unknown envelope fields: {sorted(unknown)}")
        if self.authority.get("valid_until"):
            exact_utc_ms(str(self.authority["valid_until"]))

    @property
    def canonical(self) -> CanonicalArguments:
        return canonical_arguments(self.arguments)

    def _section(self, values: dict[str, str | None], names: tuple[str, ...]) -> dict[str, Any]:
        return {name: values.get(name) for name in names}

    def unavailable(self) -> list[str]:
        """Every envelope field this workflow does not supply, by dotted path."""
        out = [f"authority.{n}" for n in _AUTHORITY_FIELDS if not self.authority.get(n)]
        out += [f"execution_context.{n}" for n in _CONTEXT_FIELDS
                if not self.execution_context.get(n)]
        out += [f"evidence.{n}" for n in _EVIDENCE_FIELDS if not self.evidence.get(n)]
        if not self.tool_definition_digest:
            out.append("action.tool_definition_digest")
        return sorted(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ACTION_SCHEMA,
            "operation_id": self.operation_id,
            "workflow_id": self.workflow_id,
            "action": {"tool": self.tool, **self.canonical.to_dict(),
                       "tool_definition_digest": self.tool_definition_digest},
            "authority": self._section(self.authority, _AUTHORITY_FIELDS),
            "execution_context": self._section(self.execution_context, _CONTEXT_FIELDS),
            "evidence": self._section(self.evidence, _EVIDENCE_FIELDS),
            "unavailable": self.unavailable(),
        }

    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(
            _canonical_json(self.to_dict()).encode("utf-8")).hexdigest()
