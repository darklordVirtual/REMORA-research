# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A second adapter, with nothing implemented yet.

    python conformance/decision-to-effect-v1/run_conformance.py --adapter skeleton

Every vector reports UNSUPPORTED, which is a legitimate result and neither a
pass nor a failure. Copy this file to ``adapter_<system>.py`` and fill in the
methods your system can express; each one you implement turns one vector into a
real result.

Two things to keep, because they are what makes a run comparable:

- Report what your system decided, mapped to a class from ``vectors.json``.
  Never return the class the vector expects. If a refusal has no mapping,
  return ``"UNMAPPED:<your reason>"`` and add the mapping deliberately.
- Raise :class:`Unsupported` rather than approximating a mechanism you do not
  have. A system with no execution lease should say so, not simulate one.
"""
from __future__ import annotations

from typing import Any

from adapter import Unsupported


class SkeletonAdapter:
    name = "skeleton"
    version = "0"

    def reset(self) -> None:
        """Discard state from the previous vector. Usually the only method
        that does not raise."""

    def authorize(self, call: dict[str, Any], *, audience: str = "") -> str:
        """Evaluate the call and return an opaque handle to the authority."""
        raise Unsupported("authorize")

    def redeem_grant(self, handle: str, *, audience: str = "") -> str:
        """Present the authority at the enforcement point."""
        raise Unsupported("redeem_grant")

    def dispatch(
        self, handle: str, call: dict[str, Any], *, now: str | None = None
    ) -> str:
        """Attempt the call under the authority. ``call`` may carry arguments
        that differ from the authorized ones; that is the point of V-02."""
        raise Unsupported("dispatch")

    def dispatch_concurrent(
        self, handle: str, call: dict[str, Any], workers: int
    ) -> str:
        """Attempt the same call from several threads at once. Return
        ``EXACTLY_ONE_EXECUTED`` only if exactly one side effect occurred."""
        raise Unsupported("dispatch_concurrent")

    def dispatch_indeterminate(self, handle: str, call: dict[str, Any]) -> str:
        """Attempt a call whose outcome cannot be established."""
        raise Unsupported("dispatch_indeterminate")

    def revoke_principal(self) -> None:
        """Revoke the principal the authority was issued to. Revocation must be
        decided by the system under test, never by this adapter."""
        raise Unsupported("revoke_principal")

    def change_toolspec(self) -> None:
        """Move the tool contract identity after evaluation."""
        raise Unsupported("change_toolspec")

    def change_policy_bundle(self) -> None:
        """Move the policy bundle identity after evaluation."""
        raise Unsupported("change_policy_bundle")

    def change_runtime(self) -> None:
        """Present the authority on a runtime other than the bound one."""
        raise Unsupported("change_runtime")

    def verify_effect(self, handle: str, observed: dict[str, Any]) -> str:
        """Compare independently observed state against the authorized call."""
        raise Unsupported("verify_effect")


def build() -> SkeletonAdapter:
    return SkeletonAdapter()
