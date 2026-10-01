# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A runnable adapter with nothing implemented.

``--adapter skeleton`` reports six UNSUPPORTED vectors. Copy this file, fill in
the operations your execution layer can express, and each one turns into a
result.
"""
from __future__ import annotations

from typing import Any

from adapter import Unsupported


class SkeletonAdapter:
    name = "skeleton"
    version = "0"

    def reset(self) -> None:
        pass

    def approve(self, call: dict[str, Any]) -> str:
        raise Unsupported("approve")

    def dispatch(self, handle: str, call: dict[str, Any], *, actor: str | None = None) -> str:
        raise Unsupported("dispatch")

    def register_alternate_tool(self, tool: str) -> None:
        raise Unsupported("register_alternate_tool")

    def change_policy_bundle(self) -> None:
        raise Unsupported("change_policy_bundle")

    def verify_effect(self, handle: str, observed: dict[str, Any], *, claimed: dict[str, Any]) -> str:
        raise Unsupported("verify_effect")

    def executions(self) -> int:
        return 0


def build() -> SkeletonAdapter:
    return SkeletonAdapter()
