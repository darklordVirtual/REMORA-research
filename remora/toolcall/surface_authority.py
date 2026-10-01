# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Finite observed authority graph; no inference from the absence of a bypass.

Scope strings are exact identifiers or '*'. They are observations supplied by
the deployment provider, not credential inspection performed by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from remora.toolcall.runtime_surface import RuntimeTool, RuntimeToolSurface, SurfaceVerdict

_SCOPES = ("credential_scope", "allowed_targets", "network_scope", "operations", "effect_classes")


@dataclass(frozen=True)
class AuthorityReport:
    verdict: SurfaceVerdict
    reasons: tuple[str, ...]
    edges: tuple[tuple[str, str, str], ...]
    alternate_paths: tuple[tuple[str, str], ...]
    scope_mismatches: tuple[str, ...]
    unresolved_tools: tuple[str, ...]


def _overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return bool(left and right and (set(left) & set(right) or "*" in left or "*" in right))


def analyze_authority(surface: RuntimeToolSurface, governed: Mapping[str, RuntimeTool], *,
                      inventory_complete: bool = False) -> AuthorityReport:
    """Compare observed scopes with the deployment's expected signed scopes.

    inventory_complete is the provider's bounded inventory assertion. Even
    when true, the strongest result is MATCHED_OBSERVATION, not a proof about
    unobserved processes, credentials, targets or network routes.
    """
    if type(inventory_complete) is not bool:
        raise ValueError("inventory_complete must be bool")
    active = {t.tool_id: t for t in surface.tools
              if t.callable_at_dispatch is not False or t.offered_to_agent is not False}
    unresolved = set()
    mismatches = set()
    alternate = set()
    edges: set[tuple[str, str, str]] = set()
    for name, tool in active.items():
        if not tool.authority_provenance or any(getattr(tool, key) is None for key in _SCOPES):
            unresolved.add(name)
        for key in _SCOPES:
            observed = getattr(tool, key)
            if observed is not None:
                edges.update((name, key, value) for value in observed)
            if name in governed:
                expected = getattr(governed[name], key)
                if expected is None:
                    unresolved.add(name)
                elif observed is not None and "*" not in expected and not set(observed) <= set(expected):
                    mismatches.add(name)
        if name not in governed and name not in unresolved:
            for governed_name, expected in governed.items():
                reach = ("allowed_targets", "operations", "effect_classes")
                if any(getattr(expected, key) is None for key in reach):
                    unresolved.add(name)
                elif all(_overlap(getattr(tool, key), getattr(expected, key)) for key in reach):
                    alternate.add((name, governed_name))
    reasons = []
    if alternate:
        reasons.append("alternate_effect_path_detected")
    if mismatches:
        reasons.append("authority_scope_mismatch")
    if unresolved or not inventory_complete or not surface.complete or set(governed) - set(active):
        reasons.append("alternate_effect_path_not_ruled_out")
    if surface.observation_source != "agent-runtime":
        reasons.append("runtime_registry_unattested")
    if alternate or mismatches:
        verdict = SurfaceVerdict.MISMATCH
    elif reasons:
        verdict = SurfaceVerdict.NOT_ESTABLISHED
    else:
        verdict = SurfaceVerdict.MATCHED_OBSERVATION
    return AuthorityReport(verdict, tuple(reasons), tuple(sorted(edges)),
                           tuple(sorted(alternate)), tuple(sorted(mismatches)),
                           tuple(sorted(unresolved)))
