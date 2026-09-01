# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The adapter contract for the decision-to-effect conformance suite.

An adapter is the only implementation-specific code in this suite. It replays
each vector's step programme against one system and reports a normalized
outcome class from ``vectors.json``. Nothing else in the suite may import an
implementation.

The contract is deliberately small. A system that cannot express one of these
operations should raise :class:`Unsupported`, which the runner records as
``UNSUPPORTED`` for that vector. An unsupported vector is a legitimate result
and is never counted as a pass or as a failure.
"""
from __future__ import annotations

from typing import Any, Protocol


class Unsupported(Exception):
    """This system does not express the operation the vector requires."""


class ConformanceAdapter(Protocol):
    """One system under test."""

    name: str
    version: str

    def reset(self) -> None:
        """Discard all state from the previous vector."""

    def authorize(self, call: dict[str, Any], *, audience: str = "") -> str:
        """Evaluate ``call`` and return an opaque handle to the authority."""

    def redeem_grant(self, handle: str, *, audience: str = "") -> str:
        """Present the authority at the enforcement point. Returns an outcome class."""

    def dispatch(
        self, handle: str, call: dict[str, Any], *, now: str | None = None
    ) -> str:
        """Attempt the call under the authority. Returns an outcome class."""

    def dispatch_concurrent(self, handle: str, call: dict[str, Any], workers: int) -> str:
        """Attempt the same call from ``workers`` threads at once."""

    def dispatch_indeterminate(self, handle: str, call: dict[str, Any]) -> str:
        """Attempt a call whose outcome cannot be established."""

    def revoke_principal(self) -> None:
        """Revoke the principal that the authority was issued to."""

    def change_toolspec(self) -> None:
        """Move the tool contract identity after evaluation."""

    def change_policy_bundle(self) -> None:
        """Move the policy bundle identity after evaluation."""

    def change_runtime(self) -> None:
        """Present the authority on a runtime other than the bound one."""

    def verify_effect(self, handle: str, observed: dict[str, Any]) -> str:
        """Compare independently observed state against the authorized call."""
