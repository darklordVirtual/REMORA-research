# SPDX-License-Identifier: BUSL-1.1
"""Internal broker shim used by generated stub modules (RF-11).

The generated ``remora_tools.py`` modules produced by
:mod:`remora.toolcall.ptc.stub_generator` import ``remora_propose`` from this
module.  Its *only* job is to return a :class:`ProposedCall` data object — it
never contacts any real API, holds any credential, or executes any action.

This module is intentionally minimal so that the trust boundary is obvious on
inspection.
"""
from __future__ import annotations

from typing import Any

from remora.toolcall.ptc.call_graph import ProposedCall

import uuid

__all__ = ["remora_propose"]


def remora_propose(
    *,
    tool_id: str,
    arguments: dict[str, Any],
    toolspec_hash: str,
    plan_source_hash: str = "",
) -> ProposedCall:
    """Return a :class:`ProposedCall` — no execution, no side effects.

    This is the *only* callable that generated stub functions are allowed to
    call.  Returning a data object rather than performing any action is the
    architectural guarantee that separates planning from execution.
    """
    return ProposedCall(
        call_id=str(uuid.uuid4()),
        tool_id=tool_id,
        arguments=arguments,
        toolspec_hash=toolspec_hash,
        plan_source_hash=plan_source_hash,
    )
