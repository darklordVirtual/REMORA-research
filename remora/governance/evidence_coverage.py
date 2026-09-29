# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Whether the evidence for a claim is complete, not only authentic (Q7.3).

REMORA's evidence is tamper-evident: the tenant chain recomputes its hashes,
effect evidence rechecks against its contract (RES-013), and an exported
bundle hashes its sections. None of that says whether the evidence is
*enough*. A chain with an authentic ``execution_authorized`` entry and no
``execution_result`` verifies clean, and so does a result with no effect
observation. A reader who sees "verified" can take authentic for complete.

An :class:`EvidenceContract` names the evidence kinds a claim requires.
:func:`assess_coverage` compares the items present against it and returns
one of four verdicts, in this precedence:

TAMPERED
    at least one item failed its own integrity check. Dominates, because
    nothing else about the set can be relied on.
INCONCLUSIVE
    at least one item that would count could not be checked. The set is not
    reported as authentic when part of it was never verified.
AUTHENTIC_BUT_INCOMPLETE
    every item checked out and at least one required kind is missing.
COMPLETE
    every required kind is present in an item that checked out.

Missing kinds are listed on every verdict, so an INCONCLUSIVE or TAMPERED
answer still says what was absent.

Authenticity is decided by a verifier the caller supplies. For the tenant
chain, :func:`chain_event_items` derives it from the chain's own
verification: an entry the chain reports broken is TAMPERED, and an entry
after the first break is UNVERIFIABLE, because its predecessor link can no
longer be trusted.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

__all__ = [
    "AUTHORIZED_EXECUTION",
    "EXECUTED_EFFECT",
    "SUCCESS_ESTABLISHED",
    "SUCCESS_ESTABLISHED_V2",
    "Authenticity",
    "CoverageStatus",
    "CoverageVerdict",
    "EvidenceContract",
    "EvidenceItem",
    "EvidenceRequirement",
    "assess_coverage",
    "chain_event_items",
    "content_digest_verifier",
]


class Authenticity(str, Enum):
    AUTHENTIC = "authentic"
    TAMPERED = "tampered"
    UNVERIFIABLE = "unverifiable"


class CoverageStatus(str, Enum):
    COMPLETE = "COMPLETE"
    AUTHENTIC_BUT_INCOMPLETE = "AUTHENTIC_BUT_INCOMPLETE"
    TAMPERED = "TAMPERED"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class EvidenceItem:
    """One piece of evidence: its kind, its content and a claimed digest.

    ``ref`` locates it (a chain sequence number, a file, a receipt id) so a
    verdict can name exactly which item failed.
    """

    kind: str
    payload: Mapping[str, Any]
    ref: str = ""
    sha256: str | None = None
    #: Set when authenticity was decided upstream (see chain_event_items).
    authenticity: Authenticity | None = None


@dataclass(frozen=True)
class EvidenceRequirement:
    """A kind the claim needs, optionally narrowed to items with given fields.

    ``where`` is an exact match on payload fields: an ``execution_result``
    only counts toward an executed effect when ``tool_executed`` is true.
    """

    kind: str
    where: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    description: str = ""

    def accepts(self, item: EvidenceItem) -> bool:
        return item.kind == self.kind and all(
            _field(item.payload, name) == value for name, value in self.where.items())

    @property
    def label(self) -> str:
        if not self.where:
            return self.kind
        return self.kind + "[" + ",".join(
            f"{k}={v}" for k, v in sorted(self.where.items())) + "]"


@dataclass(frozen=True)
class EvidenceContract:
    contract_id: str
    claim: str
    requirements: tuple[EvidenceRequirement, ...]


@dataclass(frozen=True)
class CoverageVerdict:
    contract_id: str
    status: CoverageStatus
    satisfied: tuple[str, ...]
    missing: tuple[str, ...]
    tampered: tuple[str, ...]
    unverifiable: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "status": self.status.value,
            "satisfied": list(self.satisfied),
            "missing": list(self.missing),
            "tampered": list(self.tampered),
            "unverifiable": list(self.unverifiable),
        }


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def content_digest_verifier(item: EvidenceItem) -> Authenticity:
    """AUTHENTIC when the payload hashes to the claimed digest.

    An item with no claimed digest is UNVERIFIABLE: there is nothing to check
    it against, and "nothing contradicted it" is not authenticity.
    """
    if item.authenticity is not None:
        return item.authenticity
    if not item.sha256:
        return Authenticity.UNVERIFIABLE
    return (Authenticity.AUTHENTIC if _canonical_sha256(item.payload) == item.sha256
            else Authenticity.TAMPERED)


def assess_coverage(
    contract: EvidenceContract,
    items: Sequence[EvidenceItem],
    verify: Callable[[EvidenceItem], Authenticity] = content_digest_verifier,
) -> CoverageVerdict:
    """Compare ``items`` with ``contract``; see the module docstring."""
    checked = [(item, verify(item)) for item in items]
    tampered = tuple(item.ref or item.kind for item, a in checked
                     if a is Authenticity.TAMPERED)
    satisfied: list[str] = []
    missing: list[str] = []
    unverifiable: list[str] = []
    for requirement in contract.requirements:
        matching = [(item, a) for item, a in checked if requirement.accepts(item)]
        if any(a is Authenticity.AUTHENTIC for _, a in matching):
            satisfied.append(requirement.label)
        elif matching:
            unverifiable.extend(item.ref or item.kind for item, a in matching
                                if a is Authenticity.UNVERIFIABLE)
            missing.append(requirement.label)
        else:
            missing.append(requirement.label)
    if tampered:
        status = CoverageStatus.TAMPERED
    elif unverifiable:
        status = CoverageStatus.INCONCLUSIVE
    elif missing:
        status = CoverageStatus.AUTHENTIC_BUT_INCOMPLETE
    else:
        status = CoverageStatus.COMPLETE
    return CoverageVerdict(contract.contract_id, status, tuple(satisfied),
                           tuple(missing), tampered, tuple(unverifiable))


_MISSING = object()


def _field(payload: Mapping[str, Any], name: str) -> Any:
    """A payload field; a dotted name reads a nested one (``capability.allowed``).
    A plain name reads the top level exactly as before."""
    value: Any = payload
    for part in name.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return _MISSING
        value = value[part]
    return value


_PROBLEM_INDEX = re.compile(r"_at:(\d+)$")


def chain_event_items(events: Sequence[Mapping[str, Any]],
                      chain_problems: Sequence[str]) -> list[EvidenceItem]:
    """Evidence items for a proposal's chain entries, authenticity decided.

    ``events`` are the proposal's entries as
    ``remora.execution.projections.proposal_events`` returns them, and
    ``chain_problems`` is the problem list from ``TenantAuditChain.verify``.
    An entry at a reported index is TAMPERED; an entry after the first
    reported break is UNVERIFIABLE; the rest are AUTHENTIC. A problem that
    names no index makes every entry UNVERIFIABLE.
    """
    indices = {int(m.group(1)) for p in chain_problems if (m := _PROBLEM_INDEX.search(p))}
    unindexed = any(not _PROBLEM_INDEX.search(p) for p in chain_problems)
    first_break = min(indices) if indices else None
    items: list[EvidenceItem] = []
    for event in events:
        seq = int(event["sequence_no"])
        if seq in indices:
            authenticity = Authenticity.TAMPERED
        elif unindexed or (first_break is not None and seq > first_break):
            authenticity = Authenticity.UNVERIFIABLE
        else:
            authenticity = Authenticity.AUTHENTIC
        items.append(EvidenceItem(
            kind=str(event.get("event") or ""),
            payload=dict(event.get("payload") or {}),
            ref=f"chain:{seq}",
            authenticity=authenticity,
        ))
    return items


#: The chain records a governed execution leaves when it was authorised and
#: dispatched. What it does not include is an observation of the effect.
AUTHORIZED_EXECUTION = EvidenceContract(
    contract_id="authorized_execution_v1",
    claim="the call was assessed, authorised, and the dispatcher ran it",
    requirements=(
        EvidenceRequirement("assessed", description="the decision"),
        EvidenceRequirement("execution_authorized", description="grant consumed, intent recorded"),
        EvidenceRequirement("execution_result", MappingProxyType({"tool_executed": True}),
                            description="the dispatcher invoked the tool and it returned"),
    ),
)

#: The claim a reader usually means by "it happened": the effect was also
#: observed, by a bound verifier, to match its postcondition contract.
EXECUTED_EFFECT = EvidenceContract(
    contract_id="executed_effect_v1",
    claim="the authorised call ran and its effect was observed as intended",
    requirements=(
        *AUTHORIZED_EXECUTION.requirements,
        EvidenceRequirement("effect_verified", MappingProxyType({"status": "EFFECT_VERIFIED"}),
                            description="a bound verifier observed the declared delta"),
    ),
)

#: SDD §24 (quality program Q8.7): an action is established only when every
#: layer holds, never because the executor returned success. The capability
#: check allowed the tool, the call was authorised, the dispatcher ran it,
#: and a bound verifier observed the intended effect. A proposal assessed
#: without a capability policy cannot complete this contract; the verdict
#: then names the missing capability decision instead of hiding it.
SUCCESS_ESTABLISHED = EvidenceContract(
    contract_id="success_established_v1",
    claim="capability, authority, execution and effect all hold for the action",
    requirements=(
        EvidenceRequirement("assessed", MappingProxyType({"capability.allowed": True}),
                            description="the capability check allowed the tool"),
        *EXECUTED_EFFECT.requirements[1:],
    ),
)

#: NTA-2 (docs/design/authority-preserving-capability-mediation-v1.md,
#: section 15): v1 plus the nested effects. The execution_result must also say
#: that every effect the tool requested through its mediator is settled, so an
#: execution with an UNKNOWN or truncated child is not established however its
#: parent reads. An unmediated tool records ``settled: true`` with
#: ``mediated: false``, which says nothing was requested through REMORA, not
#: that nothing happened. A new version rather than a changed v1, so a verdict
#: already given under v1 does not change after the fact.
SUCCESS_ESTABLISHED_V2 = EvidenceContract(
    contract_id="success_established_v2",
    claim="capability, authority, execution, nested effects and effect all hold for the action",
    requirements=tuple(
        EvidenceRequirement(
            "execution_result",
            MappingProxyType({"tool_executed": True, "nested_effects.settled": True}),
            description="the dispatcher ran the tool and every nested effect is settled")
        if r.kind == "execution_result" else r
        for r in SUCCESS_ESTABLISHED.requirements
    ),
)
