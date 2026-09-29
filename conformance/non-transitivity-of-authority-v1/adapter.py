# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The adapter contract for the non-transitivity-of-authority suite.

An adapter replays each vector's step programme against one system and reports
a normalized outcome class from ``vectors.json``. It is the only
implementation-specific code in the suite.

Handles are opaque names chosen by the vector (``"P"``, ``"C"``, ``"L"``); the
adapter maps them to whatever its system uses. A system that cannot express an
operation raises :class:`Unsupported`, which the runner records as
``UNSUPPORTED``: neither a pass nor a failure.
"""
from __future__ import annotations

from typing import Any, Protocol


class Unsupported(Exception):
    """This system does not express the operation the vector requires."""


class NtaAdapter(Protocol):
    name: str
    version: str

    def reset(self, world: dict[str, Any]) -> None:
        """Discard all state and load the vector suite's fixed world."""

    def resolve(self, handle: str, *, task: str) -> str:
        """Issue the principal's authority for ``task``. Returns an outcome class."""

    def delegate(self, handle: str, *, parent: str, delegatee: str, tools: list[str],
                 transitive: bool, extra_constraints: dict[str, Any]) -> str:
        """Derive an authority for ``delegatee`` from ``parent``. Returns DELEGATED or DELEGATION_DENIED."""

    def authorize(self, handle: str, *, authority_set: str, actor: str, tool: str,
                  arguments: dict[str, Any]) -> str:
        """Issue a call-bound authority (a grant, lease or token) for one call."""

    def dispatch(self, *, authority: str, authority_set: str, actor: str, tool: str,
                 arguments: dict[str, Any]) -> str:
        """Attempt the call under the named authorities. Returns an outcome class."""

    def revoke(self, authority_set: str) -> str:
        """Revoke one issued authority."""

    # NTA-2: effects inside a governed execution.

    def open_execution(self, handle: str, *, authority_set: str, tool: str,
                       policy_allows: list[str] | None) -> str:
        """Start executing ``tool`` under ``authority_set`` with the tool's declared
        downstream ceiling from the world. The effect authority is also
        addressable as a set under ``handle``. Returns OPENED or DELEGATION_DENIED."""

    def mediate(self, *, execution: str, capability: str, resource: str | None,
                arguments: dict[str, Any]) -> str:
        """Request one privileged effect from inside the execution. Returns an outcome class."""

    def close_execution(self, execution: str) -> str:
        """End the execution."""
