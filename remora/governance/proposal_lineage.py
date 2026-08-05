# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Making resubmit-until-accept probing visible in the audit trail.

An ABSTAIN is terminal: nothing can approve it, and nothing can execute
it. That stops the *individual* call and does nothing about the pattern.
An agent refused once can adjust an argument and propose again, and
because each proposal is minted fresh, the tenth attempt looks exactly
like the first. The refusals worked; the probing was invisible.

This module derives the lineage that makes it visible. Two decisions in
it are load-bearing, and both are about what a determined caller could do:

**Lineage is derived, never declared.** A ``supersedes_proposal_id``
field on the request would be defeated by the one caller it exists to
catch — a prober just omits it. Nothing here reads the request; the audit
chain is the only input, so the caller cannot influence the answer by
what it sends.

**The verdict is recorded, not acted on.** The key can only be as precise
as the deployment's declarations allow. When a signed ToolSpec declares
which argument is the target resource, "the same action retried" is
exact. Without that, the key falls back to (actor, tool, environment),
which cannot tell a legitimate agent using one tool repeatedly from a
prober — so ``escalation_eligible`` ships as shadow eligibility and
``shadow_only`` says so in the record. Routing on a signal whose
false-positive rate nobody has measured is the mistake this layer exists
to prevent, and the same discipline the ESCALATE→VERIFY routing change
was held to.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

__all__ = [
    "ESCALATION_THRESHOLD",
    "LINEAGE_WINDOW_SECONDS",
    "LineageKey",
    "ProposalLineage",
    "derive_lineage",
    "lineage_key_for",
]

#: How far back an abstain still counts as part of the same probing run.
#: Unbounded counting would make every long-lived tenant eventually look
#: like a prober, decaying the signal into a function of account age.
LINEAGE_WINDOW_SECONDS = 3600

#: Prior abstains on the same key before the next proposal is flagged.
#: Two refusals can be a client learning the contract; a third inside the
#: window is a pattern worth a human's attention.
ESCALATION_THRESHOLD = 3

#: The argument role a ToolSpec uses to name what an action targets.
_TARGET_ROLE = "target_resource"


@dataclass(frozen=True)
class LineageKey:
    """What counts as "the same attempt, retried".

    ``basis`` records how precise this key could be. A reader weighing an
    ``escalation_eligible`` verdict needs it: ``tool_only`` cannot
    distinguish repeated legitimate use from probing, and a verdict built
    on it deserves less weight than one built on a declared target.
    """

    actor: str
    tool_name: str
    target_environment: str
    resource: str = ""
    basis: str = "tool_only"


@dataclass(frozen=True)
class ProposalLineage:
    """What the chain says about this proposal's ancestry."""

    #: The most recent abstained proposal this one appears to supersede.
    superseded_proposal_id: str
    prior_abstain_count: int
    #: 1 for a first attempt, 2 for the first retry, and so on.
    probe_sequence_no: int
    escalation_eligible: bool
    lineage_key_basis: str
    window_seconds: int
    #: Always true in this version. Present so a reader is never left to
    #: infer whether the eligibility above actually changed the routing.
    shadow_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "superseded_proposal_id": self.superseded_proposal_id,
            "prior_abstain_count": self.prior_abstain_count,
            "probe_sequence_no": self.probe_sequence_no,
            "escalation_eligible": self.escalation_eligible,
            "lineage_key_basis": self.lineage_key_basis,
            "window_seconds": self.window_seconds,
            "shadow_only": self.shadow_only,
        }


def lineage_key_for(
    *,
    actor: str,
    tool_name: str,
    target_environment: str,
    arguments: Mapping[str, Any] | None = None,
    argument_roles: Mapping[str, str] | None = None,
) -> LineageKey:
    """Build the key this proposal would be grouped under.

    Only an argument the ToolSpec *declares* as the target role is read.
    An argument merely named ``target_resource`` is not one, or the caller
    would choose its own grouping — and a prober would choose a fresh one
    every time.
    """
    resource = ""
    for name, role in (argument_roles or {}).items():
        if role == _TARGET_ROLE:
            value = (arguments or {}).get(name)
            if value is not None:
                resource = str(value)
            break
    return LineageKey(
        actor=actor,
        tool_name=tool_name,
        target_environment=target_environment,
        resource=resource,
        basis="semantic_target" if resource else "tool_only",
    )


def _parse(timestamp: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(timestamp))
    except (TypeError, ValueError):
        return None


def _matches(payload: Mapping[str, Any], key: LineageKey) -> bool:
    return (
        payload.get("event") == "assessed"
        and str(payload.get("decision", "")).lower() == "abstain"
        and str(payload.get("actor", "")) == key.actor
        and str(payload.get("tool_name", "")) == key.tool_name
        and str(payload.get("target_environment", "")) == key.target_environment
        and str(payload.get("lineage_resource", "")) == key.resource
    )


def derive_lineage(
    entries: Sequence[Mapping[str, Any]],
    key: LineageKey,
    *,
    now: str,
    window_seconds: int = LINEAGE_WINDOW_SECONDS,
    threshold: int = ESCALATION_THRESHOLD,
) -> ProposalLineage:
    """Count this key's recent abstains and name the latest one.

    ``entries`` are audit-chain entries in chain order. Only assessments
    that ABSTAINED count: probing means being refused and trying again, so
    a call that was allowed is the system working, not evidence against
    the caller.

    An entry whose timestamp cannot be parsed is **excluded**, not
    counted. A record we cannot place in time cannot support a claim about
    a rate, and counting it would let a malformed entry manufacture
    eligibility.
    """
    reference = _parse(now)
    superseded = ""
    count = 0

    for entry in entries:
        payload = entry.get("payload") or {}
        if not _matches(payload, key):
            continue
        stamped = _parse(entry.get("timestamp"))
        if stamped is None or reference is None:
            continue
        age = (reference - stamped).total_seconds()
        if age < 0 or age > window_seconds:
            continue
        count += 1
        superseded = str(payload.get("proposal_id", "") or "")

    return ProposalLineage(
        superseded_proposal_id=superseded,
        prior_abstain_count=count,
        probe_sequence_no=count + 1,
        escalation_eligible=(count + 1) >= threshold + 1,
        lineage_key_basis=key.basis,
        window_seconds=window_seconds,
    )
