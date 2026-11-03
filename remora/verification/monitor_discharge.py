# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""WS2-B typed monitor-veto discharge: an unwired prototype (WS2 SDD v1.4 §3).

Status: ``library_only``. No runtime path, server or worker imports this
module. It was built under the owner exception recorded on issue #953
(2026-11-03), before the SDD's D1 (§99 rebuilt-OT reproduction) and D2 (M4.1
closure) gates and before the owner's ruling on INV-M4-04. Tests passing here
are not H3 evidence.

The legacy composer (:func:`remora.verification.compose.compose_authorized_decision`)
is used unchanged, twice at most:

1. The *legacy* record is composed exactly as today, with the typed history
   in the ledger counted as a veto on record. Every path that does not
   discharge returns this record and its final action.
2. Only if every crossed question in the attempt family's history is
   discharged by an exact, signed, current receipt under a deployment-signed
   contract, a *discharged view* is composed with the crossing removed and no
   veto on record. Every other cap is the legacy one; the view is refused if
   that is not so. Uncertainty codes, outages and the deterministic caps still
   apply through the same meet.

A discharge never raises a cap: the view is the legacy composition minus the
monitor's crossed-threshold veto, so the engine, precondition, binding,
freshness and ceiling caps bound it from above. An untyped historical veto,
an uncovered question, an unverifiable contract or receipt, any binding
mismatch, and any contradicting receipt leave the veto in place.

The typed ledger records crossings per attempt family. It is immutable; the
caller persists the returned ledger. Storage, re-gate and admission are not
part of this prototype (SDD §3.4).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from remora.crypto.domain_signing import (
    Signature,
    SignatureDomain,
    VerificationKey,
    verify,
)
from remora.decision_providers.composition_adapter import (
    AssessmentOutcome,
    MonitorAssessment,
    MonitorMode,
    MonitorProfile,
)
from remora.evidence.admission.canonical import canonical_bytes
from remora.policy.report import DecisionReport
from remora.verification.check import CheckedPreconditions
from remora.verification.compose import compose_authorized_decision, monitor_usable
from remora.verification.preconditions import (
    LogicalState,
    ProposalContext,
    RequirementSet,
    tagged_digest,
)
from remora.verification.records import CompositionRecord

__all__ = [
    "CONTRACT_SCHEMA",
    "RECEIPT_SCHEMA",
    "CoveredQuestion",
    "CrossingEvent",
    "DischargeContract",
    "DischargeDecision",
    "DischargeReceipt",
    "MonitorDischargeTrace",
    "MonitorVetoLedger",
    "SignedContract",
    "SignedReceipt",
    "compose_with_monitor_discharge",
    "verify_contract",
]

CONTRACT_SCHEMA = "remora-ws2-monitor-resolution/v1"
RECEIPT_SCHEMA = "remora-ws2-monitor-discharge-receipt/v1"
#: The legacy monitor reasons a discharge may lift. Any other monitor cap
#: (uncertainty, outage, out of scope) is outside WS2-B and stays.
_DISCHARGEABLE = frozenset({"monitor_risk_over_threshold", "monitor_veto_sticky"})


@dataclass(frozen=True)
class CoveredQuestion:
    """One monitor question, the risk obligation that settles it, and who proves it."""

    question_id: str
    risk_obligation: str
    predicate_id: str
    verifier_id: str
    source_authority_id: str
    eligible_tools: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"question_id": self.question_id, "risk_obligation": self.risk_obligation,
                "predicate_id": self.predicate_id, "verifier_id": self.verifier_id,
                "source_authority_id": self.source_authority_id,
                "eligible_tools": sorted(self.eligible_tools)}


@dataclass(frozen=True)
class DischargeContract:
    """The deployment's map from monitor questions to discharge obligations."""

    contract_id: str
    pinned_monitor_profile_hash: str
    covered: tuple[CoveredQuestion, ...] = ()

    def __post_init__(self) -> None:
        ids = [c.question_id for c in self.covered]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate question_id in discharge contract")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": CONTRACT_SCHEMA, "contract_id": self.contract_id,
                "pinned_monitor_profile_hash": self.pinned_monitor_profile_hash,
                "covered": sorted((c.to_dict() for c in self.covered),
                                  key=lambda c: c["question_id"])}

    def payload(self) -> bytes:
        return canonical_bytes(self.to_dict())

    @property
    def contract_hash(self) -> str:
        return tagged_digest("monitor-discharge-contract", self.to_dict())

    def entry(self, question_id: str) -> CoveredQuestion | None:
        return next((c for c in self.covered if c.question_id == question_id), None)


@dataclass(frozen=True)
class SignedContract:
    contract: DischargeContract
    signature: Signature


def verify_contract(signed: SignedContract, keys: Iterable[VerificationKey], *,
                    revoked: Iterable[str] = ()) -> DischargeContract:
    """The contract if a trusted deployment key signed exactly it; ``ValueError`` otherwise."""
    result = verify(SignatureDomain.MONITOR_DISCHARGE_CONTRACT, signed.contract.payload(),
                    signed.signature, list(keys), revoked=revoked)
    if not result.ok:
        raise ValueError(f"discharge contract rejected: {result.reason}")
    return signed.contract


@dataclass(frozen=True)
class DischargeReceipt:
    """A verifier's statement that one risk obligation holds for one exact call."""

    question_id: str
    risk_obligation: str
    verifier_id: str
    contract_hash: str
    context_hash: str
    evidence_digest: str
    profile_hash: str
    state: LogicalState
    issued_at: int
    valid_until: int

    def to_dict(self) -> dict[str, Any]:
        return {"schema": RECEIPT_SCHEMA, "question_id": self.question_id,
                "risk_obligation": self.risk_obligation, "verifier_id": self.verifier_id,
                "contract_hash": self.contract_hash, "context_hash": self.context_hash,
                "evidence_digest": self.evidence_digest, "profile_hash": self.profile_hash,
                "state": LogicalState(self.state).value, "issued_at": self.issued_at,
                "valid_until": self.valid_until}

    def payload(self) -> bytes:
        return canonical_bytes(self.to_dict())

    @property
    def receipt_hash(self) -> str:
        return tagged_digest("monitor-discharge-receipt", self.to_dict())


@dataclass(frozen=True)
class SignedReceipt:
    receipt: DischargeReceipt
    signature: Signature


@dataclass(frozen=True)
class CrossingEvent:
    """One crossed question, bound to the assessment and context it came from."""

    attempt_family_id: str
    proposal_id: str
    question_id: str
    assessment_id: str
    context_hash: str
    profile_hash: str
    recorded_at: int

    def to_dict(self) -> dict[str, Any]:
        return {"attempt_family_id": self.attempt_family_id, "proposal_id": self.proposal_id,
                "question_id": self.question_id, "assessment_id": self.assessment_id,
                "context_hash": self.context_hash, "profile_hash": self.profile_hash,
                "recorded_at": self.recorded_at}

    @property
    def event_hash(self) -> str:
        return tagged_digest("monitor-crossing-event", self.to_dict())


@dataclass(frozen=True)
class MonitorVetoLedger:
    """Typed crossing history. *legacy_untyped_veto* is a pre-ledger veto: never discharged."""

    events: tuple[CrossingEvent, ...] = ()
    legacy_untyped_veto: bool = False

    def questions(self, attempt_family_id: str) -> frozenset[str]:
        return frozenset(e.question_id for e in self.events
                         if e.attempt_family_id == attempt_family_id)

    def with_crossings(self, assessment: MonitorAssessment, context: ProposalContext,
                       profile: MonitorProfile, attempt_family_id: str) -> MonitorVetoLedger:
        known = {e.event_hash for e in self.events}
        new = [CrossingEvent(attempt_family_id, context.proposal_id, q,
                             assessment.assessment_id, context.context_hash,
                             profile.profile_hash, assessment.recorded_at)
               for q in sorted(set(assessment.crossed))]
        fresh = tuple(e for e in new if e.event_hash not in known)
        return replace(self, events=self.events + fresh) if fresh else self


@dataclass(frozen=True)
class DischargeDecision:
    discharged: frozenset[str] = frozenset()
    undischarged: frozenset[str] = frozenset()
    reasons: tuple[tuple[str, str], ...] = ()
    receipt_hashes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MonitorDischargeTrace:
    """Everything the decision rests on. The legacy record is never altered."""

    legacy: CompositionRecord
    discharge: DischargeDecision
    discharged_view: CompositionRecord | None
    final_action: str
    ledger: MonitorVetoLedger
    contract_hash: str | None = None
    events: tuple[CrossingEvent, ...] = field(default=())


def _receipt_reason(signed: SignedReceipt, entry: CoveredQuestion, contract_hash: str,
                    context: ProposalContext, checked: CheckedPreconditions,
                    profile: MonitorProfile, now_s: int, keys: list[VerificationKey],
                    revoked: tuple[str, ...]) -> str | None:
    """``None`` for a valid PROVED receipt, else why it does not discharge."""
    r = signed.receipt
    result = verify(SignatureDomain.MONITOR_DISCHARGE_RECEIPT, r.payload(), signed.signature,
                    keys, revoked=revoked)
    if not result.ok:
        return f"receipt_{result.reason}"
    for name, got, want in (("contract", r.contract_hash, contract_hash),
                            ("obligation", r.risk_obligation, entry.risk_obligation),
                            ("verifier", r.verifier_id, entry.verifier_id),
                            ("context", r.context_hash, context.context_hash),
                            ("evidence", r.evidence_digest, checked.evidence_digest),
                            ("profile", r.profile_hash, profile.profile_hash)):
        if got != want:
            return f"receipt_binding_{name}"
    if now_s < r.issued_at:
        return "receipt_not_yet_valid"
    if now_s >= r.valid_until:
        return "receipt_expired"
    if LogicalState(r.state) is not LogicalState.PROVED:
        return "receipt_not_proved"
    return None


def _decide(questions: frozenset[str], contract: DischargeContract | None,
            receipts: Iterable[SignedReceipt], context: ProposalContext,
            checked: CheckedPreconditions, profile: MonitorProfile, now_s: int,
            keys: list[VerificationKey], revoked: tuple[str, ...],
            legacy_untyped_veto: bool) -> DischargeDecision:
    if legacy_untyped_veto:
        return DischargeDecision(undischarged=questions, reasons=(("*", "legacy_untyped_veto"),))
    if contract is None:
        return DischargeDecision(undischarged=questions, reasons=(("*", "no_contract"),))
    if contract.pinned_monitor_profile_hash != profile.profile_hash:
        return DischargeDecision(undischarged=questions,
                                 reasons=(("*", "contract_for_another_monitor_profile"),))
    by_question: dict[str, list[SignedReceipt]] = {}
    for signed in receipts:
        by_question.setdefault(signed.receipt.question_id, []).append(signed)
    done: set[str] = set()
    left: set[str] = set()
    reasons: list[tuple[str, str]] = []
    hashes: list[str] = []
    for q in sorted(questions):
        entry = contract.entry(q)
        if entry is None:
            left.add(q)
            reasons.append((q, "question_not_covered"))
            continue
        if context.tool_name not in entry.eligible_tools:
            left.add(q)
            reasons.append((q, "tool_not_covered"))
            continue
        candidates = by_question.get(q, [])
        if not candidates:
            left.add(q)
            reasons.append((q, "no_receipt"))
            continue
        verdicts = [(s, _receipt_reason(s, entry, contract.contract_hash, context, checked,
                                        profile, now_s, keys, revoked)) for s in candidates]
        proving = [s for s, why in verdicts if why is None]
        # A validly signed, bound receipt for this question that does not
        # prove it contradicts any receipt that does.
        contradicting = [why for s, why in verdicts
                         if why == "receipt_not_proved"]
        if proving and not contradicting:
            done.add(q)
            hashes.extend(s.receipt.receipt_hash for s in proving)
            reasons.append((q, "discharged"))
        else:
            left.add(q)
            reasons.extend((q, why) for _, why in verdicts if why is not None)
            if proving and contradicting:
                reasons.append((q, "receipt_conflict"))
    return DischargeDecision(frozenset(done), frozenset(left), tuple(reasons), tuple(hashes))


def _monitor_code(record: CompositionRecord) -> str | None:
    return next((c.code for c in record.all_caps if c.source == "monitor"), None)


def compose_with_monitor_discharge(
    base: DecisionReport,
    context: ProposalContext,
    requirements: RequirementSet,
    checked: CheckedPreconditions,
    assessment: MonitorAssessment | None,
    profile: MonitorProfile,
    *,
    now_s: int,
    ledger: MonitorVetoLedger,
    attempt_family_id: str,
    contract: DischargeContract | None,
    receipts: Iterable[SignedReceipt] = (),
    receipt_keys: Iterable[VerificationKey] = (),
    revoked: Iterable[str] = (),
    verifiable: frozenset[str] = frozenset(),
    budget_exhausted: bool = False,
    parent_record_hash: str | None = None,
    uncertainty_settled: frozenset[str] | None = None,
) -> MonitorDischargeTrace:
    """Compose as today, then discharge typed crossings only where proved (module docstring).

    *contract* must come from :func:`verify_contract`; ``None`` disables discharge.
    """
    history = ledger.questions(attempt_family_id)
    kwargs: Mapping[str, Any] = dict(now_s=now_s, verifiable=verifiable,
                                     budget_exhausted=budget_exhausted,
                                     parent_record_hash=parent_record_hash,
                                     uncertainty_settled=uncertainty_settled)
    legacy = compose_authorized_decision(
        base, context, requirements, checked, assessment, profile,
        monitor_veto_on_record=ledger.legacy_untyped_veto or bool(history), **kwargs)

    outcome, _ = monitor_usable(assessment, profile, context, checked, now_s)
    crossed_now = (outcome is AssessmentOutcome.ASSESSED and assessment is not None
                   and profile.mode is not MonitorMode.SHADOW and bool(assessment.crossed))
    new_ledger = (ledger.with_crossings(assessment, context, profile, attempt_family_id)
                  if crossed_now and assessment is not None else ledger)
    questions = new_ledger.questions(attempt_family_id)
    contract_hash = None if contract is None else contract.contract_hash

    def legacy_trace(decision: DischargeDecision) -> MonitorDischargeTrace:
        return MonitorDischargeTrace(legacy, decision, None, legacy.final_action, new_ledger,
                                     contract_hash, new_ledger.events)

    if _monitor_code(legacy) not in _DISCHARGEABLE:
        return legacy_trace(DischargeDecision(undischarged=questions))
    decision = _decide(questions, contract, receipts, context, checked, profile, now_s,
                       list(receipt_keys), tuple(revoked), ledger.legacy_untyped_veto)
    if decision.undischarged or not decision.discharged:
        return legacy_trace(decision)

    view_assessment = None if assessment is None else replace(assessment, crossed=())
    view = compose_authorized_decision(base, context, requirements, checked, view_assessment,
                                       profile, monitor_veto_on_record=False, **kwargs)
    if [c for c in view.all_caps if c.source != "monitor"] != \
            [c for c in legacy.all_caps if c.source != "monitor"]:
        # Unreachable by construction; a difference would mean the discharge
        # changed more than the monitor cap, so it is refused.
        return legacy_trace(replace(decision, discharged=frozenset(),
                                    undischarged=questions,
                                    reasons=decision.reasons + (("*", "view_diverged"),)))
    return MonitorDischargeTrace(legacy, decision, view, view.final_action, new_ledger,
                                 contract_hash, new_ledger.events)
