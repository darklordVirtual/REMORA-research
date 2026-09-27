# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Research-only comparison of observed tool capability surfaces.

An observation from the serving agent runtime is still a provider assertion,
not an external attestation. A dispatcher registry only proves registration in
that dispatcher; it cannot prove which tools were offered to an agent.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping


class SurfaceVerdict(str, Enum):
    MATCHED_OBSERVATION = "MATCHED_OBSERVATION"
    MISMATCH = "MISMATCH"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"


@dataclass(frozen=True)
class RuntimeTool:
    tool_id: str
    source: str
    offered_to_agent: bool | None
    callable_at_dispatch: bool | None
    toolspec_hash: str | None
    registered: bool | None = None
    configured: bool | None = None
    discovered: bool | None = None
    source_server: str | None = None
    implementation_identity: str | None = None
    argument_schema_json: str = "{}"
    credential_scope: tuple[str, ...] | None = None
    allowed_targets: tuple[str, ...] | None = None
    network_scope: tuple[str, ...] | None = None
    operations: tuple[str, ...] | None = None
    effect_classes: tuple[str, ...] | None = None
    authority_provenance: str | None = None
    discovery_error: str | None = None
    registration_generation: int | None = None

    def __post_init__(self) -> None:
        if not self.tool_id or not self.source:
            raise ValueError("tool_id and source are required")
        for name in ("registered", "configured", "discovered", "offered_to_agent", "callable_at_dispatch"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise ValueError(f"{name} must be bool or None")
        schema = json.loads(self.argument_schema_json)
        if not isinstance(schema, dict):
            raise ValueError("argument_schema_json must encode an object")
        object.__setattr__(self, "argument_schema_json", canonical_json(schema))
        for name in ("credential_scope", "allowed_targets", "network_scope", "operations", "effect_classes"):
            value = getattr(self, name)
            if value is not None:
                if isinstance(value, str) or any(not isinstance(v, str) or not v for v in value):
                    raise ValueError(f"{name} must contain nonempty strings")
                object.__setattr__(self, name, tuple(sorted(set(value))))


@dataclass(frozen=True)
class RuntimeToolSurface:
    runtime_identity: str
    observation_source: str
    complete: bool
    tools: tuple[RuntimeTool, ...]
    observed_at: str = ""

    def __post_init__(self) -> None:
        if not self.runtime_identity or not self.observation_source:
            raise ValueError("runtime_identity and observation_source are required")
        if type(self.complete) is not bool:
            raise ValueError("complete must be bool")
        object.__setattr__(self, "tools", tuple(self.tools))
        names = [tool.tool_id for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("duplicate tool_id in runtime surface")

    def identity(self) -> dict:
        """Versioned identity; observation timestamps are evidence metadata."""
        return {
            "schema_version": "runtime-surface-v1",
            "runtime_identity": self.runtime_identity,
            "observation_source": self.observation_source,
            "complete": self.complete,
            "tools": [asdict(t) for t in sorted(self.tools, key=lambda t: t.tool_id)],
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.identity()).encode("utf-8")).hexdigest()


def canonical_json(value: object) -> str:
    """Version-one deterministic JSON (not a cross-language JCS claim)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class SurfaceReport:
    verdict: SurfaceVerdict
    reasons: tuple[str, ...]
    unexpected_tools: tuple[str, ...] = ()
    missing_tools: tuple[str, ...] = ()
    identity_mismatches: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurfaceContinuity:
    verdict: SurfaceVerdict
    reasons: tuple[str, ...]
    assessed_digest: str
    dispatch_digest: str


def compare_surfaces(assessed: RuntimeToolSurface, dispatch: RuntimeToolSurface) -> SurfaceContinuity:
    """Observe continuity only; a digest is not execution authority."""
    reasons = []
    if assessed.runtime_identity != dispatch.runtime_identity:
        reasons.append("runtime_identity_mismatch")
    if any(s.observation_source != "agent-runtime" or not s.complete for s in (assessed, dispatch)):
        reasons.append("surface_not_established")
    if reasons:
        verdict = SurfaceVerdict.NOT_ESTABLISHED
    elif assessed.digest() != dispatch.digest():
        verdict = SurfaceVerdict.MISMATCH
        reasons.append("surface_changed_since_assessment")
    else:
        verdict = SurfaceVerdict.MATCHED_OBSERVATION
    return SurfaceContinuity(verdict, tuple(reasons), assessed.digest(), dispatch.digest())


def evaluate_surface(
    observed: RuntimeToolSurface,
    governed_tools: Mapping[str, str],
    *,
    expected_runtime_identity: str,
) -> SurfaceReport:
    """Compare explicit agent observations with governed ToolSpec identities.

    MATCHED_OBSERVATION means only that the supplied snapshot matches; the
    caller still has to establish that the provider and its process identity
    are trustworthy. Missing tools are a mismatch only for complete snapshots.
    """
    reasons: list[str] = []
    if observed.runtime_identity != expected_runtime_identity:
        reasons.append("runtime_identity_mismatch")
    if observed.observation_source != "agent-runtime":
        reasons.append("observer_not_agent_runtime")
    if reasons:
        return SurfaceReport(SurfaceVerdict.NOT_ESTABLISHED, tuple(reasons))
    if not observed.complete:
        reasons.append("surface_incomplete")
    if any(tool.offered_to_agent is None or tool.callable_at_dispatch is None
           for tool in observed.tools):
        reasons.append("tool_visibility_unknown")

    callable_tools = {
        tool.tool_id: tool for tool in observed.tools
        if tool.offered_to_agent is True or tool.callable_at_dispatch is True
    }
    unexpected = tuple(sorted(set(callable_tools) - set(governed_tools)))
    missing = tuple(sorted(set(governed_tools) - set(callable_tools))) if observed.complete and not reasons else ()
    changed = tuple(sorted(
        name for name, tool in callable_tools.items()
        if name in governed_tools and tool.toolspec_hash is not None
        and tool.toolspec_hash != governed_tools[name]
    ))
    if unexpected or missing or changed:
        return SurfaceReport(SurfaceVerdict.MISMATCH, tuple(reasons), unexpected, missing, changed)
    if any(tool.toolspec_hash is None for tool in callable_tools.values()):
        reasons.append("toolspec_identity_unknown")
    if reasons:
        return SurfaceReport(SurfaceVerdict.NOT_ESTABLISHED, tuple(reasons))
    return SurfaceReport(SurfaceVerdict.MATCHED_OBSERVATION, ())


def observe_dispatcher_registry(dispatcher: object, *, runtime_identity: str) -> RuntimeToolSurface:
    """Read the current dispatcher registry without implying agent visibility.

    Uses the executor's public, detached name snapshot. A separate agent runtime
    must observe its offered tools; registration cannot establish that fact.
    """
    read_names = getattr(dispatcher, "registered_tool_names", None)
    if not callable(read_names):
        raise ValueError("dispatcher registry unavailable")
    tools = tuple(RuntimeTool(str(name), "dispatcher", None, None, None, True)
                  for name in read_names())
    return RuntimeToolSurface(runtime_identity, "dispatcher-registry", False, tools)
