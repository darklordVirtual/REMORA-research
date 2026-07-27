# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Test tool-registry module for the execution API dispatcher wiring.

Mirrors the trusted-deployment-configuration contract of issue #13: the
API process imports the module named by ``REMORA_TOOL_REGISTRY_MODULE`` and
calls ``register_tools(register)`` — tool callables (and any credentials
they close over) live app-side, never in request payloads.
"""
from __future__ import annotations

from typing import Any, Callable

CALLS: list[Any] = []
RAISE: dict[str, bool] = {"update_work_order": False}


def _update_work_order(arguments: dict) -> dict:
    if RAISE.get("update_work_order"):
        raise RuntimeError("downstream system unavailable")
    CALLS.append(arguments)
    return {"work_order": arguments.get("order"), "status": "rescheduled"}


def register_tools(register: Callable[[str, Callable[[Any], Any]], None]) -> None:
    register("update_work_order", _update_work_order)
