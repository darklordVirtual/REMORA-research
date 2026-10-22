# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Versioned WS1 evidence receipts and the admission-time check (M4.1b).

A WS1 evaluation proves a call's preconditions at one instant: the re-gate.
Nothing carried that proof further, so evidence that lapsed between the
re-gate and the grant's consumption still let the call run (control 2b,
``tests/test_ws1_gate_controls.py``). A receipt is the part of the proof that
admission needs to check again, inside its own transaction
(docs/architecture/ADR-ws1-m4-admission-topology.md):

- which precondition was PROVED, under which WS1 binding and tenant,
- until when the evidence holds, and
- at which authority epoch the subject it depends on stood when it was read.

A receipt is data, not authority. It is built here, from a composition
record the deterministic gate produced, and never from a request or a tool
result. ``admission_refusal`` is a pure function: the caller supplies the
database instant, the declared clock skew and the epochs it read under lock,
so the same inputs always give the same answer.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from remora.verification.preconditions import LogicalState, ProcessingStatus, tagged_digest
from remora.verification.records import CompositionRecord

__all__ = [
    "MAX_CLOCK_SKEW_MS",
    "NO_EVIDENCE_EXPIRY_MS",
    "EvidenceReceiptV1",
    "admission_refusal",
    "earliest_valid_until_ms",
    "receipt_set_digest",
    "receipts_from_record",
]

SCHEMA = "remora-ws1-evidence-receipt/v1"

#: The largest clock skew a deployment may declare. A larger value would let
#: evidence count as fresh long after it lapsed, which is the hole receipts
#: close; a deployment whose clocks drift further must fix its clocks.
MAX_CLOCK_SKEW_MS = 5_000

#: ``valid_until_ms`` of a receipt for a REVIEW precondition. An approval
#: carries no evidence expiry; its own lifetime is the review queue's, which
#: re-checks it before the admission transaction. Admission still checks the
#: ``review:<role>`` subject's epoch, so revoking the role refuses.
NO_EVIDENCE_EXPIRY_MS = 2**63 - 1


@dataclass(frozen=True)
class EvidenceReceiptV1:
    """One PROVED precondition, as admission re-checks it. Times are epoch ms."""

    tenant_id: str
    binding_hash: str
    precondition_id: str
    #: The authority subject the evidence depends on, e.g. ``source:crm``.
    subject_key: str
    #: The subject's authority epoch when the evidence was read.
    source_epoch: int
    source_version: str
    evidence_refs: tuple[str, ...]
    verified_at_ms: int
    valid_until_ms: int
    verifier_profile_hash: str

    def body(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "tenant_id": self.tenant_id,
                "binding_hash": self.binding_hash,
                "precondition_id": self.precondition_id,
                "subject_key": self.subject_key, "source_epoch": self.source_epoch,
                "source_version": self.source_version,
                "evidence_refs": list(self.evidence_refs),
                "verified_at_ms": self.verified_at_ms,
                "valid_until_ms": self.valid_until_ms,
                "verifier_profile_hash": self.verifier_profile_hash}

    @property
    def digest(self) -> str:
        return tagged_digest("ws1-evidence-receipt", self.body())


def receipts_from_record(
    record: CompositionRecord,
    *,
    tenant_id: str,
    binding_hash: str,
    subject_of: Mapping[str, str],
    epochs: Mapping[str, int],
) -> tuple[EvidenceReceiptV1, ...]:
    """One receipt per PROVED, completed precondition in ``record``.

    ``subject_of`` maps each precondition to the authority subject its
    evidence depends on; ``epochs`` is that subject's epoch as read before the
    lookups ran. A PROVED result without a subject, an epoch or an expiry
    raises: a receipt that admission cannot check is not a receipt.
    """
    if not tenant_id or not binding_hash:
        raise ValueError("a receipt needs a tenant and a WS1 binding hash")
    out: list[EvidenceReceiptV1] = []
    for result in record.all_precondition_results:
        if (result.get("logical_state") != LogicalState.PROVED.value
                or result.get("processing_status") != ProcessingStatus.COMPLETED.value):
            continue
        pid = str(result["precondition_id"])
        subject = subject_of.get(pid)
        if not subject:
            raise ValueError(f"precondition {pid} has no authority subject")
        if subject not in epochs:
            raise ValueError(f"no epoch was read for subject {subject}")
        verified_at, valid_until = result.get("verified_at"), result.get("valid_until")
        reviewed = subject.startswith("review:") and valid_until is None
        if verified_at is None or (valid_until is None and not reviewed):
            raise ValueError(f"precondition {pid} was PROVED without an expiry")
        out.append(EvidenceReceiptV1(
            tenant_id=tenant_id, binding_hash=binding_hash, precondition_id=pid,
            subject_key=subject, source_epoch=int(epochs[subject]),
            source_version=str(result.get("source_version") or ""),
            evidence_refs=tuple(str(r) for r in result.get("evidence_refs") or ()),
            verified_at_ms=int(verified_at) * 1000,
            valid_until_ms=(NO_EVIDENCE_EXPIRY_MS if valid_until is None
                            else int(valid_until) * 1000),
            verifier_profile_hash=record.profile_hash))
    return tuple(sorted(out, key=lambda r: r.precondition_id))


def receipt_set_digest(receipts: Sequence[EvidenceReceiptV1]) -> str:
    """Order-independent digest of a receipt set, for binding into admission."""
    return tagged_digest("ws1-evidence-receipt-set",
                         sorted(r.digest for r in receipts))


def earliest_valid_until_ms(receipts: Sequence[EvidenceReceiptV1]) -> int | None:
    return min((r.valid_until_ms for r in receipts), default=None)


def admission_refusal(
    receipts: Sequence[EvidenceReceiptV1],
    *,
    tenant_id: str,
    binding_hash: str,
    expected_set_digest: str,
    required_preconditions: Collection[str],
    now_ms: int,
    max_clock_skew_ms: int,
    epochs: Mapping[str, tuple[int, bool]],
) -> str | None:
    """The reason admission must refuse, or None when every receipt holds.

    ``now_ms`` is the database instant read inside the admission transaction.
    ``epochs`` maps each subject to ``(epoch, revoked)`` as read there under
    lock. Evidence counts as expired once ``valid_until_ms - max_clock_skew_ms``
    is at or before ``now_ms``: equality is expired (M4-T10).
    """
    if (isinstance(max_clock_skew_ms, bool) or not isinstance(max_clock_skew_ms, int)
            or not 0 <= max_clock_skew_ms <= MAX_CLOCK_SKEW_MS):
        raise ValueError(
            f"max_clock_skew_ms must be an int from 0 to {MAX_CLOCK_SKEW_MS}")
    if receipt_set_digest(receipts) != expected_set_digest:
        return "evidence_receipt_modified"
    by_id: dict[str, EvidenceReceiptV1] = {}
    for receipt in receipts:
        if receipt.tenant_id != tenant_id or receipt.binding_hash != binding_hash:
            return "evidence_receipt_foreign"
        if receipt.precondition_id in by_id:
            return "evidence_receipt_duplicate"
        by_id[receipt.precondition_id] = receipt
    if any(pid not in by_id for pid in required_preconditions):
        return "evidence_receipt_missing"
    for receipt in receipts:
        if receipt.valid_until_ms - max_clock_skew_ms <= now_ms:
            return "evidence_expired_at_admission"
        current = epochs.get(receipt.subject_key)
        if current is None:
            return "authority_epoch_unread"
        epoch, revoked = current
        if revoked:
            return "authority_revoked"
        if epoch != receipt.source_epoch:
            return "authority_epoch_stale"
    return None
