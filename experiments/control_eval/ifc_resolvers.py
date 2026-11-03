# SPDX-License-Identifier: BUSL-1.1
"""Bounded WS1 evidence for the AgentDojo REMORA-IFC arm (E_IFC_WS1).

A sink argument the flow check finds UNTRUSTED may still be authorised when
the user's own records show it is an established counterparty or the user's
own object. This module proves that, and nothing else, through the WS1
library (``remora/verification``): each lookup is one requirement set
compiled from a registry, one :class:`VerificationRequest`, one
:func:`run_request` against a declared resolver, and one
:func:`check_preconditions` with a declared verifier. Only PROVED endorses.
UNKNOWN, REFUTED and every refusal grant nothing.

Every resolver reads a snapshot of the environment taken before the
trajectory's first executed call, never the live state. A record the agent
wrote in this session (a payment that slipped through, a sent message) can
therefore not endorse a later call.

Predicates, and why an injection cannot write their evidence
-------------------------------------------------------------

``bank.outgoing_counterparty``
    The IBAN is the recipient of a transaction whose sender is the user's own
    IBAN, or of one of the user's scheduled transactions. Incoming
    transactions do not count: anyone can pay the user and choose the sender
    IBAN and the subject, so an attacker IBAN in an incoming transaction is
    not a counterparty. Only the account owner creates outgoing ones.
``bank.own_scheduled_transaction``
    The id names one of the user's scheduled transactions. It proves which
    object is changed, not how: amount, subject and recipient stay
    integrity-required, so this cannot authorise an attacker's change.
``mail.sent_counterparty``
    The address received an email the user sent (sender is the account,
    status sent). The inbox contact list does not count: AgentDojo builds it
    from every email, received ones included, so any sender of a received
    email, an injected one included, is a "contact".
``slack.dm_counterparty``
    The user's own identity sent this user a direct message before. Being a
    workspace member does not count, and neither does channel membership:
    channel names are attacker-writable in AgentDojo's slack environment.
``drive.own_file``
    The file's owner is the user's account. It proves which object, not what
    is written to it or to whom it goes; those stay integrity-required.

No resolver exists for amounts, payload text, URLs, reservations, or for
deleting or cancelling: none of these has evidence an injection cannot
influence, and "the object is the user's own" does not authorise destroying
it.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from remora.policy.observation import canonical_tool_call_hash
from remora.verification.check import (
    ResolverEvidence,
    VerificationRequest,
    check_preconditions,
)
from remora.verification.preconditions import (
    ExecutionPrecondition,
    LogicalState,
    ProposalContext,
    ResolutionClass,
    derive_preconditions,
)
from remora.verification.registry import PreconditionRegistry, PredicateSpec, ResolverSpec
from remora.verification.resolvers import ResolverRefused, run_request

__all__ = [
    "MAX_LOOKUPS_PER_CALL",
    "PREDICATES",
    "SLACK_SELF",
    "LookupResult",
    "endorse_value",
    "normalise_iban",
    "own_identifiers",
]

#: Lookups one proposed call may make. A call that needs more is not recovered.
MAX_LOOKUPS_PER_CALL: Final = 4
#: The identity AgentDojo's slack tools send as (``slack.py``: ``sender = "bot"``).
SLACK_SELF: Final = "bot"
#: Fixed clock: the replay is deterministic and evidence never ages within it.
_NOW_S: Final = 1_700_000_000
_VERIFIER_ID: Final = "agentdojo.record_found/v1"


def normalise_iban(value: Any) -> str:
    return str(value).replace(" ", "").upper()


def _get(obj: Any, *path: str) -> Any:
    for name in path:
        if obj is None:
            return None
        obj = obj.get(name) if isinstance(obj, Mapping) else getattr(obj, name, None)
    return obj


def _status(value: Any) -> str:
    return str(getattr(value, "value", value)).lower()


def own_identifiers(suite: str, env: Any) -> frozenset[str]:
    """The principal's own addresses: deployment identity, not evidence.

    Lower-cased (IBANs compacted). Passwords, names and other profile fields
    are not identifiers and are never listed.
    """
    found: set[str] = set()
    if suite == "banking":
        iban = _get(env, "bank_account", "iban")
        if iban:
            found.add(normalise_iban(iban).lower())
    elif suite == "slack":
        found.add(SLACK_SELF.lower())
    elif suite in ("travel", "workspace"):
        for path in (("user", "email"), ("inbox", "account_email"),
                     ("calendar", "account_email"), ("cloud_drive", "account_email")):
            value = _get(env, *path)
            if value:
                found.add(str(value).lower())
    return frozenset(found)


# ── predicates over a snapshot ───────────────────────────────────────────


def _bank_outgoing(env: Any, subject: str) -> dict[str, Any]:
    own = normalise_iban(_get(env, "bank_account", "iban") or "")
    want = normalise_iban(subject)
    incoming_only = False
    for t in _get(env, "bank_account", "transactions") or ():
        if normalise_iban(_get(t, "recipient") or "") == want \
                and normalise_iban(_get(t, "sender") or "") == own and own:
            return {"found": True, "basis": "outgoing_transaction"}
        if normalise_iban(_get(t, "sender") or "") == want:
            incoming_only = True
    for t in _get(env, "bank_account", "scheduled_transactions") or ():
        if normalise_iban(_get(t, "recipient") or "") == want:
            return {"found": True, "basis": "scheduled_transaction"}
    return {"found": False, "basis": "incoming_only" if incoming_only else "no_record"}


def _bank_own_scheduled(env: Any, subject: str) -> dict[str, Any]:
    for t in _get(env, "bank_account", "scheduled_transactions") or ():
        if str(_get(t, "id")) == subject:
            return {"found": True, "basis": "own_scheduled_transaction"}
    return {"found": False, "basis": "no_record"}


def _emails(inbox: Any) -> list[Any]:
    emails = _get(inbox, "emails")
    if isinstance(emails, Mapping) and emails:
        return list(emails.values())
    return list(_get(inbox, "initial_emails") or ())


def _mail_sent(env: Any, subject: str) -> dict[str, Any]:
    inbox = _get(env, "inbox")
    account = str(_get(inbox, "account_email") or "").lower()
    want = subject.lower()
    for email in _emails(inbox):
        if str(_get(email, "sender") or "").lower() != account or not account:
            continue
        if _status(_get(email, "status")) != "sent":
            continue
        addressed = [*(_get(email, "recipients") or ()), *(_get(email, "cc") or ()),
                     *(_get(email, "bcc") or ())]
        if want in {str(a).lower() for a in addressed}:
            return {"found": True, "basis": "sent_email"}
    return {"found": False, "basis": "no_record"}


def _slack_dm(env: Any, subject: str) -> dict[str, Any]:
    inbox = _get(env, "slack", "user_inbox") or {}
    for msg in (inbox.get(subject) or ()) if isinstance(inbox, Mapping) else ():
        if _get(msg, "sender") == SLACK_SELF:
            return {"found": True, "basis": "own_direct_message"}
    return {"found": False, "basis": "no_record"}


def _drive_own(env: Any, subject: str) -> dict[str, Any]:
    drive = _get(env, "cloud_drive")
    account = str(_get(drive, "account_email") or "").lower()
    files = _get(drive, "files") or {}
    record = files.get(subject) if isinstance(files, Mapping) else None
    if record is not None and account and str(_get(record, "owner") or "").lower() == account:
        return {"found": True, "basis": "own_file"}
    return {"found": False, "basis": "no_record"}


@dataclass(frozen=True)
class Predicate:
    resolver_id: str
    source_id: str
    capability_id: str
    check: Callable[[Any, str], dict[str, Any]]


#: The declared resolvers. The flow declaration's ``endorse`` key may name
#: only these; nothing else can be looked up.
PREDICATES: Final[Mapping[str, Predicate]] = {
    p.resolver_id: p for p in (
        Predicate("bank.outgoing_counterparty", "bank.ledger", "read:bank.ledger", _bank_outgoing),
        Predicate("bank.own_scheduled_transaction", "bank.ledger", "read:bank.ledger",
                  _bank_own_scheduled),
        Predicate("mail.sent_counterparty", "mail.store", "read:mail.store", _mail_sent),
        Predicate("slack.dm_counterparty", "slack.store", "read:slack.store", _slack_dm),
        Predicate("drive.own_file", "drive.store", "read:drive.store", _drive_own),
    )
}


# ── the WS1 round for one value ──────────────────────────────────────────


class _SnapshotResolver:
    """A WS1 resolver over a frozen environment snapshot. Read-only."""

    def __init__(self, predicate: Predicate, snapshot: Any) -> None:
        self.resolver_id = predicate.resolver_id
        self._predicate = predicate
        self._snapshot = snapshot

    def fetch(self, request: VerificationRequest, tenant_id: str, now_s: int) -> ResolverEvidence:
        if self._snapshot is None:
            raise ResolverRefused("snapshot_unavailable")
        record = self._predicate.check(self._snapshot, request.subject_ref)
        payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        return ResolverEvidence(
            request_id=request.request_id, resolver_id=self.resolver_id,
            source_id=self._predicate.source_id, subject_ref=request.subject_ref,
            source_version="v1", tenant_id=tenant_id, acquired_at=now_s,
            valid_until=now_s + 60, payload=payload,
            payload_hash=hashlib.sha256(payload).hexdigest(), capture_method="env_snapshot")


class _FoundVerifier:
    verifier_id = _VERIFIER_ID
    version = "1"

    def verify(self, precondition: ExecutionPrecondition, payload: Any,
               context: ProposalContext) -> tuple[LogicalState, str]:
        if isinstance(payload, Mapping) and payload.get("found") is True:
            return LogicalState.PROVED, str(payload.get("basis"))
        basis = str(payload.get("basis")) if isinstance(payload, Mapping) else "malformed"
        return LogicalState.UNKNOWN, basis


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


@dataclass(frozen=True)
class LookupResult:
    resolver_id: str
    field: str
    subject_digest: str
    state: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"resolver": self.resolver_id, "field": self.field,
                "subject_sha256": self.subject_digest, "state": self.state,
                "reason": self.reason}


def endorse_value(*, suite: str, tool: str, field: str, resolver_id: str, subject: Any,
                  snapshot: Any, principal: str, flow_digest: str) -> LookupResult:
    """One bounded WS1 round: is *subject* proved for *field* of *tool*?"""
    subject_ref = str(subject)
    subject_digest = hashlib.sha256(subject_ref.encode()).hexdigest()

    def result(state: LogicalState | str, reason: str) -> LookupResult:
        return LookupResult(resolver_id, field, subject_digest,
                            getattr(state, "value", str(state)), reason)

    predicate = PREDICATES.get(resolver_id)
    if predicate is None:
        return result("refused", "resolver_not_declared")
    tenant = f"agentdojo:{suite}"
    pseudo_tool = f"endorse:{tool}.{field}"
    arguments = {"subject": subject_ref}
    registry = PreconditionRegistry(
        tools={pseudo_tool: (PredicateSpec(
            predicate_id=resolver_id, resolution_class=ResolutionClass.MACHINE,
            verifier_id=_VERIFIER_ID, resolver_ids=(resolver_id,),
            subject_argument="subject"),)},
        resolvers={resolver_id: ResolverSpec(resolver_id, predicate.source_id,
                                             frozenset({resolver_id}), predicate.capability_id)})
    context = ProposalContext(
        proposal_id=f"{pseudo_tool}:{subject_digest[:16]}", tenant_id=tenant,
        principal_id=principal or "unknown", tool_name=pseudo_tool,
        call_hash=canonical_tool_call_hash(name=pseudo_tool, arguments=arguments, tenant=tenant),
        intent_authority_hash=_digest("intent", suite, tool),
        policy_bundle_hash=_digest("agentdojo-flow-toolspecs/v1"),
        toolspec_hash=_digest("toolspec", suite, tool),
        profile_hash=_digest("profile", "control_eval"),
        capability_hash=_digest("capability", predicate.capability_id),
        flow_digest=flow_digest, flow_epoch=0, context_version=1)
    requirements = derive_preconditions(context, arguments, registry)
    if not requirements.authorizable:
        return result("refused", requirements.incomplete_reason)
    pre = requirements.preconditions[0]
    request = VerificationRequest(
        request_id=f"req:{pre.precondition_id}", context_hash=context.context_hash,
        evidence_revision=1, precondition_id=pre.precondition_id, resolver_id=resolver_id,
        subject_ref=pre.subject_ref, deadline_ms=1_000, budget_ref="control_eval")
    try:
        evidence = run_request(request, context, registry=registry,
                               resolvers={resolver_id: _SnapshotResolver(predicate, snapshot)},
                               held_capabilities=frozenset({predicate.capability_id}),
                               now_s=_NOW_S)
    except ResolverRefused as refusal:
        return result("refused", str(refusal))
    checked = check_preconditions(context, requirements, [evidence],
                                  issued={request.request_id: request}, registry=registry,
                                  verifiers={_VERIFIER_ID: _FoundVerifier()},
                                  now_s=_NOW_S, evidence_revision=1)
    outcome = checked.result(pre.precondition_id)
    return result(checked.state(pre.precondition_id),
                  outcome.reason_code if outcome is not None else "no_result")
