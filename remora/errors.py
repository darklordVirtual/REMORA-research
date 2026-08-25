# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Root of the runtime exception taxonomy (issue #45, gap 4).

The 2026-07-28 observability audit found three custom exception classes with
three unrelated bases across 262 files, and 230 builtin raises: severity
routing and alert classification required string-matching messages. This
module gives every governance-relevant runtime exception one root and two
machine-readable class attributes:

``code``
    A stable slug naming the failure, safe to route and count on. Never
    derived from the message.
``category``
    Which subsystem's contract failed: ``enforcement``, ``execution``,
    ``governance``, ``persistence``, ``tenancy``. Coarse on purpose — it is
    an alerting dimension, not a second exception hierarchy.

Two deliberate boundaries:

* :mod:`remora.sdk.errors` has its own ``RemoraError``. That is the
  CLIENT-side contract — typed views of HTTP responses, with ``retryable``
  and ``request_id`` — and it stays separate: the SDK contract is stable by
  policy (FT-13) and must not inherit churn from server internals. The two
  hierarchies meet at the wire, not in Python.
* Existing builtin bases are KEPT via multiple inheritance.
  ``ToolExecutionStateUnknown`` stays a ``RuntimeError`` and
  ``SpecIntakeRefused`` stays a ``ValueError``, because callers catch those
  bases today and an exception-taxonomy change that silently un-catches a
  guarded failure would be a safety regression dressed as a cleanup.
"""
from __future__ import annotations


class RemoraError(Exception):
    """Base class for every governance-relevant runtime exception."""

    code: str = "remora_error"
    category: str = "runtime"

    def machine_readable(self) -> dict[str, str]:
        """The routable identity of this failure: code, category, class."""
        return {
            "code": self.code,
            "category": self.category,
            "error": type(self).__name__,
        }
