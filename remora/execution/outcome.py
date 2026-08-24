# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""What a dispatch settled as, decided structurally rather than from a string.

``schemas/execution_lifecycle_v1.yaml`` already draws the line this module
enforces:

    {from: DISPATCHING, to: FAILED,  on: tool_raised_pre_effect}
    {from: DISPATCHING, to: UNKNOWN, on: crash_or_timeout_after_possible_effect}

FAILED is reserved for a failure proven to have happened BEFORE the effect
boundary. The code did not honour that. It matched ``refusal_reason ==
"tool_failed_nonce_burned"`` and settled FAILED -- a reason whose own docstring
in ``lease.py`` says *"the tool raised after its nonce was consumed: state at
the tool is unknown"*. The durable record therefore asserted "no effect
occurred" on evidence that only showed the call raised, which is a different
claim.

The invariant, stated once:

    REFUSED   REMORA observed that dispatch never began. It is the one negative
              claim REMORA can make first-hand, because it declined the call
              itself.
    FAILED    Trusted adapter evidence proves the failure occurred before the
              effect boundary.
    UNKNOWN   Dispatch began and the absence of an effect is not proven.
              Durable. A later authoritative observation may supersede it.

A dispatcher exception, a timeout, a lost response, or ``tool_failed_nonce_burned``
alone earns only UNKNOWN.

Equal burden
------------
This follows from the rule recorded for effect receipts rather than being
invented here: positive and negative system claims carry the same burden of
proof. A durable FAILED is a negative claim asserting no effect occurred, and
it was being written on less evidence than a positive SUCCEEDED requires.

FAILED is currently unreachable from the synchronous path, and that is
deliberate. No adapter in this repository produces trustworthy pre-effect
evidence yet, so the honest terminal is UNKNOWN. Approximating FAILED -- for
instance by trusting a caller-supplied ``pre_effect`` flag -- would put the
unproven negative claim back, wearing a structured field instead of a string.
The one legitimate FAILED that does exist is reconciliation of an intent that
was never claimed: the claim strictly precedes invocation, so the side effect
provably did not happen.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

__all__ = [
    "DispatchOutcome",
    "PreEffectProof",
    "classify_outcome",
]


class DispatchOutcome(str, Enum):
    """Lifecycle-model state names, so the record and the schema agree."""

    SUCCEEDED = "SUCCEEDED"
    REFUSED = "REFUSED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"

    @property
    def asserts_no_effect(self) -> bool:
        """Whether this outcome claims the side effect did not happen.

        REFUSED and FAILED do. UNKNOWN explicitly does not, which is the
        distinction the whole module exists to keep.
        """
        return self in (DispatchOutcome.REFUSED, DispatchOutcome.FAILED)

    @property
    def may_be_superseded(self) -> bool:
        """UNKNOWN is durable but not the last word.

        A later authoritative observation can resolve it -- that is how an
        unknown gets closed honestly, and why it must not be recorded as a
        terminal negative in the first place.
        """
        return self is DispatchOutcome.UNKNOWN


@dataclass(frozen=True)
class PreEffectProof:
    """Adapter evidence that a failure happened before the effect boundary.

    Deliberately not constructible from a request field. Nothing in this
    repository produces one yet, and the type exists so that the day an adapter
    can, there is a place to put the evidence rather than a boolean to trust.

    ``source`` names the adapter that observed it, and ``detail`` records what
    it saw -- a transport-level rejection, a pre-commit constraint violation, a
    remote 4xx with a body proving the request was never applied. What must
    never appear here is the dispatcher's own exception, which is precisely the
    evidence that does not distinguish the two cases.
    """

    source: str
    detail: str

    def __post_init__(self) -> None:
        if not self.source or not self.detail:
            raise ValueError(
                "pre-effect proof needs a source and what it observed; an "
                "unattributed proof is an assertion")


def classify_outcome(
    tool_execution: Mapping[str, Any],
    *,
    pre_effect_proof: PreEffectProof | None = None,
) -> DispatchOutcome:
    """The outcome a dispatch actually earned.

    Reads structure, not prose. ``dispatch_began`` is reported by the
    dispatcher, which knows whether it invoked the callable; inferring it from
    ``refusal_reason`` would put the string matching back one level down and
    make every new refusal reason a silent reclassification.
    """
    if tool_execution.get("executed"):
        return DispatchOutcome.SUCCEEDED

    began = bool(tool_execution.get("dispatch_began"))
    if not began and not tool_execution.get("state_unknown"):
        # The dispatcher declined before invoking anything: a binding refusal,
        # a spent nonce, an unknown tool. REMORA watched itself not act.
        return DispatchOutcome.REFUSED

    if pre_effect_proof is not None:
        return DispatchOutcome.FAILED

    # Dispatch began, or its outcome is unknown, and nothing proves the effect
    # did not happen. This is the case the old code called FAILED.
    return DispatchOutcome.UNKNOWN
