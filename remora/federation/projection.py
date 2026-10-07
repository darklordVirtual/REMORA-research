# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The Claim Projection Engine (SDD sections 3, 4, 7 and 18).

A projection map (YAML, versioned, pinned by digest) says, per native claim,
which dimensions it needs and which transport capabilities each dimension
needs. The engine combines it with a transport's capability declaration and
the action's own losses (``remora.federation.canonical.javascript_losses``):

- every dimension supplied                      -> PRESERVED
- the map's narrowed claim's dimensions supplied -> NARROWED
- the claim needs a lifecycle the transport lacks -> UNSUPPORTED
- otherwise                                      -> NOT_ESTABLISHED

These are projection strengths, not check results. A projection can only
weaken: nothing an adapter reports can move a claim above what the map and the
capabilities allow (``ProjectionMap.assert_export``).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from remora.federation.capabilities import TransportCapabilities
from remora.policy.observation import _canonical_json

__all__ = ["MAP_SCHEMA", "PROJECTION_RESULTS", "ClaimProjection", "ProjectionError",
           "ProjectionMap", "load_projection_map"]

MAP_SCHEMA = "remora-federation-projection-map-v1"
PRESERVED, NARROWED, NOT_ESTABLISHED, UNSUPPORTED = (
    "PRESERVED", "NARROWED", "NOT_ESTABLISHED", "UNSUPPORTED")
PROJECTION_RESULTS = (PRESERVED, NARROWED, NOT_ESTABLISHED, UNSUPPORTED)
#: Order of strength. A projection never moves left to right.
_STRENGTH = {UNSUPPORTED: 0, NOT_ESTABLISHED: 1, NARROWED: 2, PRESERVED: 3}

#: Which action losses take away which dimensions. An integer that changes
#: value takes the argument values with it; a float that becomes an integer
#: takes only its lexical type.
_LOSS_DIMENSIONS = {"integer_precision": ("argument_values", "lexical_numeric_type"),
                    "lexical_numeric_type": ("lexical_numeric_type",)}


class ProjectionError(ValueError):
    """The bridge refuses: unknown version, missing dimension or a stronger export."""


@dataclass(frozen=True)
class ClaimProjection:
    native_claim: str
    native_version: str
    result: str
    exported_claim: str | None
    preserved: tuple[str, ...]
    not_established: tuple[str, ...]
    limits: tuple[str, ...]
    action_losses: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"native_claim": f"{self.native_claim}-v{self.native_version}"
                if self.native_version else self.native_claim,
                "projection": self.result, "exported_claim": self.exported_claim,
                "preserved": list(self.preserved), "not_established": list(self.not_established),
                "limits": list(self.limits), "action_losses": self.action_losses}


@dataclass(frozen=True)
class ProjectionMap:
    map_id: str
    transport: str
    claims: dict[str, dict[str, Any]]
    digest: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectionMap":
        if data.get("schema_version") != MAP_SCHEMA:
            raise ProjectionError(f"unknown projection map version {data.get('schema_version')!r}")
        claims = data.get("native_claims")
        if not isinstance(claims, dict) or not claims:
            raise ProjectionError("a projection map names at least one native claim")
        for name, spec in claims.items():
            dims = spec.get("dimensions") or {}
            narrowed = spec.get("narrowed") or {}
            missing = set(narrowed.get("requires", ())) - set(dims)
            if missing:
                raise ProjectionError(f"{name}: narrowed claim requires undeclared {sorted(missing)}")
            exported = {spec.get("preserved_claim"), narrowed.get("exported_claim")} - {None}
            if any(not str(c).startswith("remora.") for c in exported):
                raise ProjectionError(f"{name}: exported claims are namespaced remora.*")
        return cls(map_id=str(data["projection_map_id"]), transport=str(data["transport"]),
                   claims=claims, digest="sha256:" + hashlib.sha256(
                       _canonical_json(data).encode("utf-8")).hexdigest())

    def exported_claims(self) -> set[str]:
        out: set[str] = set()
        for spec in self.claims.values():
            for claim in (spec.get("preserved_claim"),
                          (spec.get("narrowed") or {}).get("exported_claim")):
                if claim:
                    out.add(str(claim))
        return out

    def project(self, native_claim: str, capabilities: TransportCapabilities,
                action_losses: dict[str, list[str]] | None = None) -> ClaimProjection:
        if capabilities.transport != self.transport:
            raise ProjectionError(
                f"map {self.map_id} is for {self.transport}, not {capabilities.transport}")
        spec = self.claims.get(native_claim)
        if spec is None:
            raise ProjectionError(f"no projection for native claim {native_claim!r}")
        losses = dict(action_losses or {})
        lost = {d for kind in losses for d in _LOSS_DIMENSIONS.get(kind, ())}
        dims: dict[str, list[str]] = spec.get("dimensions") or {}
        preserved = tuple(sorted(d for d, caps in dims.items()
                                 if d not in lost and all(capabilities.supplies(c) for c in caps)))
        not_established = tuple(sorted(set(dims) - set(preserved)))
        limits = tuple(spec.get("limits", ()))
        version = str(spec.get("version", ""))
        lifecycle = spec.get("lifecycle")
        narrowed = spec.get("narrowed") or {}
        if lifecycle and not capabilities.supplies(lifecycle):
            result, exported = UNSUPPORTED, None
        elif dims and not not_established:
            result, exported = PRESERVED, spec.get("preserved_claim")
        elif narrowed and set(narrowed["requires"]) <= set(preserved):
            result, exported = NARROWED, narrowed["exported_claim"]
        else:
            result, exported = NOT_ESTABLISHED, None
        return ClaimProjection(native_claim, version, result, exported, preserved,
                               not_established, limits, losses)

    def assert_export(self, claim: str, projection: ClaimProjection) -> None:
        """Refuse an adapter exporting anything the projection does not permit."""
        if claim not in self.exported_claims():
            raise ProjectionError(f"{claim!r} is not an exported claim of {self.map_id}")
        if projection.exported_claim != claim:
            raise ProjectionError(
                f"{claim!r} exceeds the projection of {projection.native_claim} "
                f"({projection.result}, exports {projection.exported_claim!r})")


def load_projection_map(path: str | Path) -> ProjectionMap:
    with open(path, encoding="utf-8") as fh:
        return ProjectionMap.from_dict(yaml.safe_load(fh))


def weaker_or_equal(after: str, before: str) -> bool:
    """The core invariant: a projection result never exceeds the one it came from."""
    return _STRENGTH[after] <= _STRENGTH[before]
