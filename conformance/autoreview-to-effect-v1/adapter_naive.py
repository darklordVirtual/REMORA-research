# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A deliberately non-conforming execution layer: the discrimination control.

It treats an approval as a boolean gate: once anything is approved, whatever
is dispatched runs, under whoever dispatches it, and the tool's own success
report is taken as the effect. This is the post-approval model the benchmark
exists to distinguish from.

If the suite reported MATCH for this adapter on AR-01..AR-05 the vectors would
prove nothing. It is expected to diverge on all five and match only the
AR-00 control.
"""
from __future__ import annotations

from typing import Any


class NaiveAdapter:
    name = "naive"
    version = "0"

    def reset(self) -> None:
        self._approved: set[str] = set()
        self._tools = {"transfer_funds"}
        self._executed = 0

    def __init__(self) -> None:
        self.reset()

    def approve(self, call: dict[str, Any]) -> str:
        self._approved.add("h")
        return "h"

    def dispatch(self, handle: str, call: dict[str, Any], *, actor: str | None = None) -> str:
        if handle in self._approved and call["name"] in self._tools:
            self._executed += 1
            return "EXECUTED"
        return "UNKNOWN_TOOL"

    def register_alternate_tool(self, tool: str) -> None:
        self._tools.add(tool)

    def change_policy_bundle(self) -> None:
        pass

    def verify_effect(self, handle: str, observed: dict[str, Any], *, claimed: dict[str, Any]) -> str:
        return "EFFECT_VERIFIED" if claimed.get("ok") is True else "EFFECT_MISMATCH"

    def executions(self) -> int:
        return self._executed


def build() -> NaiveAdapter:
    return NaiveAdapter()
