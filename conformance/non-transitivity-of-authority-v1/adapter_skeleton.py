# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A second adapter with nothing implemented.

Copy it, fill in one method at a time, and run
``run_conformance.py --adapter <name>``. Until a method exists every vector
that needs it reports UNSUPPORTED, which is a result, not a failure.
"""
from __future__ import annotations

from typing import Any

from adapter import Unsupported


class SkeletonNtaAdapter:
    name = "skeleton"
    version = "0"

    def reset(self, world: dict[str, Any]) -> None:
        self._world = world

    def resolve(self, handle: str, *, task: str) -> str:
        raise Unsupported("resolve")

    def delegate(self, handle: str, **_: Any) -> str:
        raise Unsupported("delegate")

    def authorize(self, handle: str, **_: Any) -> str:
        raise Unsupported("authorize")

    def dispatch(self, **_: Any) -> str:
        raise Unsupported("dispatch")

    def revoke(self, authority_set: str) -> str:
        raise Unsupported("revoke")

    def open_execution(self, handle: str, **_: Any) -> str:
        raise Unsupported("open_execution")

    def mediate(self, **_: Any) -> str:
        raise Unsupported("mediate")

    def close_execution(self, execution: str) -> str:
        raise Unsupported("close_execution")


def build() -> SkeletonNtaAdapter:
    return SkeletonNtaAdapter()
