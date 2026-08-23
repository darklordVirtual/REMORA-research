# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The gateway's tool registry: every governed tool, in one place.

``REMORA_TOOL_REGISTRY_MODULE`` points here. The individual sets live in
their own modules and know nothing about each other; this composes them and
is the single place that decides what a deployment actually exposes.

Which sets are live is configuration, not code. A deployment that has no
knowledge-graph credential should not be offering knowledge-graph tools that
fail at dispatch — an agent cannot tell the difference between "refused" and
"broken", and it should never have to.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from deploy.gateway import gh_registry, kg_registry

#: Every set the gateway knows how to serve, and the configuration that has to
#: be present for it to be usable at all.
_SETS: dict[str, tuple[tuple[str, ...], Any]] = {
    "github": (("REMORA_GITHUB_TOKEN", "REMORA_GITHUB_REPOS"), gh_registry),
    "graph": (("REMORA_KG_TENANT", "REMORA_KG_DATABASE_ID",
               "REMORA_CF_API_TOKEN", "REMORA_CF_ACCOUNT_ID"), kg_registry),
}


def enabled_sets() -> tuple[str, ...]:
    """Sets this deployment serves.

    ``REMORA_GATEWAY_TOOL_SETS`` names them explicitly. Unset means every set
    whose configuration is complete, which keeps a first deployment simple
    without ever offering a tool that cannot work.

    Naming a set REMORA does not have is a startup failure rather than a
    silently ignored value: an operator who misspells one must not get a
    gateway with fewer tools than they think.
    """
    raw = os.getenv("REMORA_GATEWAY_TOOL_SETS", "").strip()
    if raw:
        requested = tuple(s.strip().lower() for s in raw.split(",") if s.strip())
        unknown = [s for s in requested if s not in _SETS]
        if unknown:
            raise RuntimeError(
                f"REMORA_GATEWAY_TOOL_SETS names unknown set(s) {unknown}; "
                f"expected a subset of {sorted(_SETS)}"
            )
        return requested
    return tuple(
        name for name, (required, _) in _SETS.items()
        if all(os.getenv(var, "").strip() for var in required)
    )


def tool_names() -> tuple[str, ...]:
    names: list[str] = []
    for name in enabled_sets():
        _, module = _SETS[name]
        names.extend(n for n, _ in module.TOOLS)
    return tuple(names)


def register_tools(register: Callable[[str, Callable[[Any], Any]], None]) -> None:
    for name in enabled_sets():
        _, module = _SETS[name]
        module.register_tools(register)
