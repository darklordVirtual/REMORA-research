# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Deployment hooks for the WS7 pre-dispatch checks on the execution API.

One module serves all three module-shaped settings, as a deployment might:
``REMORA_EFFECT_REGISTRY_MODULE`` (``build_resolver``),
``REMORA_STATE_REVISION_MODULE`` (``read_revision``) and
``REMORA_PROCEDURE_MODULE`` (``contract``, ``trace_for``). Tests change the
module-level state between calls to model the world moving.
"""
from __future__ import annotations

from typing import Any

from remora.enforcement.resolved_effect import ClosedWorldResolver, ResolvedEffect
from remora.governance.procedure import ProcedureContract, Step, precedence

BASE = ClosedWorldResolver(
    tools={"read_telemetry": ("telemetry.read@1", "read"),
           "update_work_order": ("workorder.update@1", "write")},
    resources={("staging", "P-1"): "plant-a/P-1", ("staging", "WO-1"): "plant-a/WO-1"},
    resource_argument={"read_telemetry": "asset", "update_work_order": "work_order_id"})
#: Swapped by tests; the resolver the server holds reads it on every call.
CURRENT: dict[str, ClosedWorldResolver] = {"resolver": BASE}
REVISIONS: dict[str, str] = {"asset/P-1": "7", "calendar/today": "12"}
TRACE: list[Step] = []
CONTRACT = ProcedureContract("fixture_v1", (precedence("read_telemetry", "update_work_order"),))


class _Live:
    def resolve(self, tool_name: str, arguments: Any, target_environment: str) -> ResolvedEffect:
        return CURRENT["resolver"].resolve(tool_name, arguments, target_environment)


def build_resolver() -> _Live:
    return _Live()


def read_revision(resource: str) -> str:
    return REVISIONS[resource]


def contract() -> ProcedureContract:
    return CONTRACT


def trace_for(lease: Any) -> list[Step]:
    return list(TRACE)


def reset() -> None:
    CURRENT["resolver"] = BASE
    REVISIONS.clear()
    REVISIONS.update({"asset/P-1": "7", "calendar/today": "12"})
    TRACE.clear()
