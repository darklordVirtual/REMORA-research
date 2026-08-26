# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pilot-pack example: the partner's tool registry module.

The ``REMORA_TOOL_REGISTRY_MODULE`` contract (servers/execution_api.py):
the API imports this module once and calls ``register_tools(register)``.
Tool callables — and any credentials they close over — live app-side;
request payloads can never add or replace them.

Protocol precondition 4: every tool carries EXPLICIT risk/action metadata
from the partner's registry. Name inference (``infer=True``) is a
bootstrap aid and never drives verdicts that count. Precondition 3: only
the tools named here exist in the pilot — nothing else.

This example registers two side-effect-bounded tools; replace the bodies
with the partner's real (still bounded, still shadow-safe) integrations.
"""
from __future__ import annotations

from typing import Any, Callable


def _lookup_work_order(args: dict[str, Any]) -> dict[str, Any]:
    """Read-only example: fetch a work order from the partner system."""
    return {"work_order": args.get("id"), "status": "example", "read_only": True}


def _stage_report(args: dict[str, Any]) -> dict[str, Any]:
    """Bounded write example: stage a report in a sandbox area the pilot
    owns — never a production write in shadow mode."""
    return {"staged": True, "report_id": args.get("report_id")}


#: The explicit per-tool metadata (protocol precondition 4). The register
#: contract wires CALLABLES only — ``register(name, fn)`` — so the
#: metadata lives here as data: it feeds the ``registry_metadata`` block
#: of every event the partner supplies (event_schema.json), and it is the
#: record that name inference never drives verdicts that count.
TOOL_METADATA: dict[str, dict[str, str]] = {
    "lookup_work_order": {
        "domain": "maintenance",
        "action_type": "read",
        "risk_tier": "low",
        "target_environment": "staging",
        "description": "Read-only work-order lookup (partner CMMS).",
    },
    "stage_report": {
        "domain": "maintenance",
        "action_type": "write",
        "risk_tier": "medium",
        "target_environment": "staging",
        "description": "Stage a report in the pilot sandbox.",
    },
}

_TOOLS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "lookup_work_order": _lookup_work_order,
    "stage_report": _stage_report,
}


def register_tools(register: Callable[[str, Callable], None]) -> None:
    for name, fn in _TOOLS.items():
        assert name in TOOL_METADATA, f"{name} has no explicit metadata"
        register(name, fn)
