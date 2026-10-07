# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Execution lifecycle separation across a transport (SDD sections 15 and 16).

A transport reports what its executor said. That is an execution report, not
an observation of the world: ``provider_confirmed`` never becomes
``EFFECT_VERIFIED``. Effect evidence is a separate edge, produced by REMORA's
effect verifier (``remora.governance.effect_verification``) from a system of
record, and only that edge can establish it.
"""
from __future__ import annotations

from typing import Any

__all__ = ["transport_outcome"]

_EXECUTION = {
    "provider_confirmed": "EXECUTION_REPORTED_SUCCESS",
    "failed": "EXECUTION_FAILED",
    "unknown": "EXECUTION_UNKNOWN",
    "dispatched": "DISPATCHED",
    "refused": "NOT_ADMITTED",
}


def transport_outcome(outcome: str, effect_evidence: Any = None) -> dict[str, str]:
    """REMORA's reading of a transport outcome, with the effect kept separate.

    ``effect_evidence`` is an ``EffectVerification`` from REMORA's verifier,
    or ``None``. The effect is established only by such evidence, and only
    when it says ``EFFECT_VERIFIED``; the transport outcome never decides it.
    """
    if outcome not in _EXECUTION:
        raise ValueError(f"unknown transport outcome {outcome!r}")
    effect = "NOT_ESTABLISHED"
    status = getattr(getattr(effect_evidence, "status", None), "value", None)
    if status == "EFFECT_VERIFIED":
        effect = "EFFECT_VERIFIED"
    elif status in ("EFFECT_MISMATCH",):
        effect = "EFFECT_MISMATCH"
    return {"transport_outcome": outcome, "execution": _EXECUTION[outcome], "effect": effect}
