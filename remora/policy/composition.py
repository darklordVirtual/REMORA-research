# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Monotone (meet) composition of decision components (SDD §3.9, P-MONO; COMP-01).

Every component of a decision returns a *cap*: the most executable action it
permits. The final decision is the least executable cap::

    ABSTAIN ≡ ESCALATE  <  VERIFY  <  ACCEPT

so no component can raise a decision above what another allows. This
replaces first-match composition, under which the first component to fire
decided and a later, stricter component was never consulted: a VERIFY from
the taint floor masked an ESCALATE the environment-mismatch gate demanded,
and an approver could then redeem a call that needed a higher authority.

Ties are resolved by component order, earliest first, so a decision that
first-match and meet agree on keeps its reasons unchanged.

A refusal that review cannot lift ranks below every other cap (RMR-AUD-003).
ESCALATE opens a review item on the execution path; a cross-tenant argument or
an intent the deployment never authorised has no such route. Under the tie
``ABSTAIN ≡ ESCALATE`` an ESCALATE guard listed earlier (``schema_valid=False``,
``adversarial_detected``) won the tie and turned the refusal into a review
item. A cap is non-approvable when its reason is in ``NON_APPROVABLE_REASONS``
or its source says so (``approvable=False``).

External components (a learned monitor or an LLM judge, an RF-04 control
protocol) enter as caps with their own reason codes and can only lower a
decision.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from remora.policy.report import DecisionAction, DecisionReason

__all__ = [
    "EXECUTABILITY",
    "EXTERNAL_CAP_REASONS",
    "GRANT_ONLY_REASONS",
    "NON_APPROVABLE_REASONS",
    "Cap",
    "executability",
    "meet",
    "rank",
]

#: How far an action lets a call proceed without further authority.
EXECUTABILITY: Final[dict[DecisionAction, int]] = {
    DecisionAction.ESCALATE: 0,
    DecisionAction.ABSTAIN: 0,
    DecisionAction.VERIFY: 1,
    DecisionAction.ACCEPT: 2,
}

#: Reasons an external cap may carry; each names the kind of component.
EXTERNAL_CAP_REASONS: Final = frozenset({
    DecisionReason.MONITOR_CAP,
    DecisionReason.PROTOCOL_CAP,
})


#: Refusals no reviewer can lift: nothing downstream can supply the authority
#: or the tenant scope the call lacks. The OPA adapter keeps the same set.
NON_APPROVABLE_REASONS: Final = frozenset({
    DecisionReason.CROSS_TENANT_ARGUMENT_BLOCKED,
    DecisionReason.INTENT_PROVENANCE_REQUIRED,
})

#: Escalations a reviewer's approval does not cover. A payload that may not
#: reach a recipient is released only by a DeclassificationGrant from a
#: reader of the data who holds the declassifier role; the grant changes the
#: verdict, so the rung stops firing (SDD v1.3 §3.6 c, §3.7; IFC-08). Until
#: then the item can be reviewed, and nothing it covers executes.
GRANT_ONLY_REASONS: Final = frozenset({
    DecisionReason.FLOW_CONFIDENTIALITY_VIOLATION,
})

#: Below every action in ``EXECUTABILITY``.
_NON_APPROVABLE_RANK: Final = -1


def executability(action: DecisionAction) -> int:
    return EXECUTABILITY[action]


@dataclass(frozen=True)
class Cap:
    """One component's cap on a decision."""

    source: str
    action: DecisionAction
    reason: DecisionReason
    approvable: bool = True


def rank(cap: Cap) -> int:
    """A cap's place in the meet: its executability, or below all of them for
    an ABSTAIN no review can lift."""
    if cap.action is DecisionAction.ABSTAIN and (
        not cap.approvable or cap.reason in NON_APPROVABLE_REASONS
    ):
        return _NON_APPROVABLE_RANK
    return executability(cap.action)


def meet(caps: Iterable[Cap]) -> Cap:
    """The least executable cap; the earliest one among equals."""
    chosen: Cap | None = None
    for cap in caps:
        if chosen is None or rank(cap) < rank(chosen):
            chosen = cap
    if chosen is None:
        raise ValueError("meet of no caps")
    return chosen
