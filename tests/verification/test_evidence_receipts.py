# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""WS1 evidence receipts and the admission-time check (M4.1b).

The M4-T* names refer to the negative test matrix in
docs/design/ws1-m4-safe-autonomy-recovery-v0.2.md §5. These tests cover the
pure check; wiring it into the admission transaction is M4.1c.
"""
from __future__ import annotations

import dataclasses

import pytest

from remora.verification.receipts import (
    MAX_CLOCK_SKEW_MS,
    admission_refusal,
    earliest_valid_until_ms,
    receipt_set_digest,
    receipts_from_record,
)
from remora.verification.records import CompositionRecord

T, BINDING = "acme", "b" * 64


def _result(pid, state="proved", status="completed", verified_at=1_000, valid_until=1_060):
    return {"precondition_id": pid, "logical_state": state, "processing_status": status,
            "evidence_refs": [f"ref-{pid}"], "reason_code": "", "verified_at": verified_at,
            "valid_until": valid_until, "source_version": "v7", "verifier_version": "1"}


def _record(*results):
    return CompositionRecord(
        context_hash="c", requirements_hash="r", evidence_digest="e", profile_hash="p",
        base_action="accept", base_reasons=(), all_caps=(),
        all_precondition_results=tuple(results), monitor_assessment=None,
        monitor_status="absent", monitor_veto=False, final_action="accept",
        review_class="", reason_codes=(), parent_record_hash=None)


SUBJECTS = {"port_up": "source:noc", "customer_active": "source:crm"}
EPOCHS = {"source:noc": 3, "source:crm": 1}


def _receipts():
    return receipts_from_record(
        _record(_result("port_up"), _result("customer_active", valid_until=1_090),
                _result("not_proved", state="unknown")),
        tenant_id=T, binding_hash=BINDING, subject_of=SUBJECTS, epochs=EPOCHS)


def _check(receipts, *, now_ms=1_000_000, skew=0, epochs=None, digest=None,
           required=("port_up", "customer_active"), tenant=T, binding=BINDING):
    return admission_refusal(
        receipts, tenant_id=tenant, binding_hash=binding,
        expected_set_digest=receipt_set_digest(receipts) if digest is None else digest,
        required_preconditions=required, now_ms=now_ms, max_clock_skew_ms=skew,
        epochs={"source:noc": (3, False), "source:crm": (1, False)} if epochs is None
        else epochs)


def test_only_proved_completed_results_become_receipts_in_ms():
    receipts = _receipts()
    assert [r.precondition_id for r in receipts] == ["customer_active", "port_up"]
    port = receipts[1]
    assert (port.subject_key, port.source_epoch) == ("source:noc", 3)
    assert (port.verified_at_ms, port.valid_until_ms) == (1_000_000, 1_060_000)
    assert earliest_valid_until_ms(receipts) == 1_060_000


def test_fresh_receipts_at_current_epochs_admit():
    assert _check(_receipts(), now_ms=1_059_999) is None


def test_m4_t01_evidence_expired_before_commit_refuses():
    assert _check(_receipts(), now_ms=1_070_000) == "evidence_expired_at_admission"


def test_m4_t10_equality_at_valid_until_is_expired():
    assert _check(_receipts(), now_ms=1_060_000) == "evidence_expired_at_admission"


def test_the_declared_skew_shortens_validity():
    assert _check(_receipts(), now_ms=1_058_000, skew=2_000) == "evidence_expired_at_admission"
    assert _check(_receipts(), now_ms=1_057_999, skew=2_000) is None


@pytest.mark.parametrize("skew", [-1, MAX_CLOCK_SKEW_MS + 1, 1.5, True, None])
def test_the_skew_must_be_declared_and_bounded(skew):
    with pytest.raises(ValueError):
        _check(_receipts(), skew=skew)


def test_m4_t04_a_higher_epoch_refuses_a_stale_receipt():
    epochs = {"source:noc": (4, False), "source:crm": (1, False)}
    assert _check(_receipts(), epochs=epochs) == "authority_epoch_stale"


def test_m4_t03_a_revoked_subject_refuses():
    epochs = {"source:noc": (3, True), "source:crm": (1, False)}
    assert _check(_receipts(), epochs=epochs) == "authority_revoked"


def test_an_epoch_that_was_not_read_refuses():
    assert _check(_receipts(), epochs={"source:noc": (3, False)}) == "authority_epoch_unread"


def test_m4_t09_a_modified_receipt_refuses():
    receipts = _receipts()
    digest = receipt_set_digest(receipts)
    forged = (receipts[0], dataclasses.replace(receipts[1], valid_until_ms=9_999_999_999))
    assert _check(forged, digest=digest) == "evidence_receipt_modified"


def test_m4_t09_a_missing_receipt_refuses():
    receipts = _receipts()[:1]
    assert _check(receipts) == "evidence_receipt_missing"


@pytest.mark.parametrize("field", ["tenant", "binding"])
def test_m4_t07_a_foreign_receipt_refuses(field):
    kwargs = {"tenant": "other"} if field == "tenant" else {"binding": "c" * 64}
    assert _check(_receipts(), **kwargs) == "evidence_receipt_foreign"


def test_a_duplicated_precondition_refuses():
    receipts = _receipts()
    doubled = (receipts[0], receipts[0], receipts[1])
    assert _check(doubled) == "evidence_receipt_duplicate"


def test_the_set_digest_ignores_order_and_changes_with_any_field():
    a, b = _receipts()
    assert receipt_set_digest((a, b)) == receipt_set_digest((b, a))
    assert receipt_set_digest((a, b)) != receipt_set_digest(
        (a, dataclasses.replace(b, source_epoch=b.source_epoch + 1)))


@pytest.mark.parametrize("missing", ["subject", "epoch", "expiry"])
def test_a_proved_result_admission_could_not_check_is_not_a_receipt(missing):
    result = _result("port_up", valid_until=None if missing == "expiry" else 1_060)
    subjects = {} if missing == "subject" else {"port_up": "source:noc"}
    epochs = {} if missing == "epoch" else {"source:noc": 3}
    with pytest.raises(ValueError):
        receipts_from_record(_record(result), tenant_id=T, binding_hash=BINDING,
                             subject_of=subjects, epochs=epochs)


def test_a_review_receipt_has_no_evidence_expiry_but_keeps_its_epoch():
    """An approval closes a REVIEW precondition without an evidence expiry;
    the queue owns the approval's lifetime. Its role's epoch still binds."""
    from remora.verification.receipts import NO_EVIDENCE_EXPIRY_MS

    reviewed = dict(_result("change_approved"), valid_until=None)
    (receipt,) = receipts_from_record(
        _record(reviewed), tenant_id=T, binding_hash=BINDING,
        subject_of={"change_approved": "review:change-manager"},
        epochs={"review:change-manager": 2})
    assert receipt.valid_until_ms == NO_EVIDENCE_EXPIRY_MS
    check = dict(tenant_id=T, binding_hash=BINDING,
                 expected_set_digest=receipt_set_digest((receipt,)),
                 required_preconditions=("change_approved",), now_ms=10**15,
                 max_clock_skew_ms=0)
    assert admission_refusal((receipt,), epochs={"review:change-manager": (2, False)},
                             **check) is None
    assert admission_refusal((receipt,), epochs={"review:change-manager": (3, True)},
                             **check) == "authority_revoked"
    # A source receipt without an expiry is still refused.
    with pytest.raises(ValueError, match="without an expiry"):
        receipts_from_record(_record(reviewed), tenant_id=T, binding_hash=BINDING,
                             subject_of={"change_approved": "source:crm"},
                             epochs={"source:crm": 1})
