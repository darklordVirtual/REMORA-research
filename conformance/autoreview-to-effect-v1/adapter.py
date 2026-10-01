# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The adapter contract for the AutoReview-to-Effect benchmark.

Every vector starts after a reviewer has approved one call. The adapter
replays the step programme against one execution layer and reports a
normalized outcome class from ``vectors.json``. Nothing else in the suite may
import an implementation.

Two rules carry over from decision-to-effect-v1: report what the system
decided, never what the vector expects; and raise :class:`Unsupported` rather
than approximate. ``verify_effect`` receives the tool's claimed result so the
record shows it was available, and a conforming adapter must not let it decide
the outcome.
"""
from __future__ import annotations

from typing import Any, Protocol


class Unsupported(Exception):
    """This system does not express the operation the vector requires."""


class AutoReviewToEffectAdapter(Protocol):
    name: str
    version: str

    def reset(self) -> None:
        """Discard all state from the previous vector."""

    def approve(self, call: dict[str, Any]) -> str:
        """Record a reviewer approval of ``call`` and return an opaque handle."""

    def dispatch(
        self, handle: str, call: dict[str, Any], *, actor: str | None = None
    ) -> str:
        """Attempt ``call`` under the approval, as ``actor`` if given. Returns an outcome class."""

    def register_alternate_tool(self, tool: str) -> None:
        """Make a second tool with the same behaviour reachable under another name."""

    def change_policy_bundle(self) -> None:
        """Supersede the policy the approval was evaluated under."""

    def verify_effect(
        self, handle: str, observed: dict[str, Any], *, claimed: dict[str, Any]
    ) -> str:
        """Compare authoritative ``observed`` state with the approved postcondition."""

    def executions(self) -> int:
        """How many times any tool body actually ran in this vector."""
