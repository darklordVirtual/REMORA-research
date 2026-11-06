# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests added for the mutants that survived the 2026-11-04 mutmut sweep.

The sweep (docs/assurance/ws1_utility_test_plan_v1.md, item 1) left 110 of
330 mutants of monitor_discharge.py alive. Most changed a serialised key, a
reason string or a trace field that no test pinned. These tests pin them:
the exact dictionaries the hashes are taken over, the exact reasons and sets
a decision carries, the trace fields, and three boundary behaviours
(``issued_at == now``, several questions in one decision, a revoked contract
key).
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from remora.crypto.domain_signing import SignatureDomain, sign
from remora.decision_providers.composition_adapter import MonitorMode
from remora.verification.monitor_discharge import (
    CONTRACT_SCHEMA,
    RECEIPT_SCHEMA,
    CoveredQuestion,
    CrossingEvent,
    DischargeContract,
    DischargeDecision,
    DischargeReceipt,
    MonitorVetoLedger,
    SignedContract,
    verify_contract,
)
from remora.verification.preconditions import LogicalState
from tests.verification._ws1 import NOW_S, base_report
from tests.verification.test_monitor_discharge import (
    CONTRACT_KEY,
    FAMILY,
    RECEIPT_KEY,
    _contract,
    _legacy,
    _receipt,
    _run,
    _setup,
)

Q = "target_mismatch"


# --- serialisation: the dictionaries the hashes are taken over -------------

def test_covered_question_serialises_every_field_under_its_own_key():
    c = CoveredQuestion("q", "obligation:q", "pred:q", "verifier", "source", ("b_tool", "a_tool"))
    assert c.to_dict() == {
        "question_id": "q", "risk_obligation": "obligation:q", "predicate_id": "pred:q",
        "verifier_id": "verifier", "source_authority_id": "source",
        "eligible_tools": ["a_tool", "b_tool"],
    }


def test_contract_serialises_its_schema_id_profile_and_sorted_coverage():
    c1 = CoveredQuestion("zeta", "o", "p", "v", "s", ("t",))
    c2 = CoveredQuestion("alpha", "o", "p", "v", "s", ("t",))
    contract = DischargeContract("cid", "profile-hash", (c1, c2))
    assert contract.to_dict() == {
        "schema": CONTRACT_SCHEMA, "contract_id": "cid",
        "pinned_monitor_profile_hash": "profile-hash",
        "covered": [c2.to_dict(), c1.to_dict()],
    }
    assert contract.entry("alpha") is c2 and contract.entry("missing") is None


def test_receipt_serialises_every_binding_and_the_state_value():
    r = DischargeReceipt("q", "obligation:q", "verifier", "c-hash", "ctx-hash", "ev-digest",
                         "prof-hash", LogicalState.PROVED, 100, 200)
    assert r.to_dict() == {
        "schema": RECEIPT_SCHEMA, "question_id": "q", "risk_obligation": "obligation:q",
        "verifier_id": "verifier", "contract_hash": "c-hash", "context_hash": "ctx-hash",
        "evidence_digest": "ev-digest", "profile_hash": "prof-hash", "state": "proved",
        "issued_at": 100, "valid_until": 200,
    }


def test_crossing_event_serialises_every_binding():
    e = CrossingEvent("fam", "prop", "q", "assess", "ctx-hash", "prof-hash", 123)
    assert e.to_dict() == {
        "attempt_family_id": "fam", "proposal_id": "prop", "question_id": "q",
        "assessment_id": "assess", "context_hash": "ctx-hash", "profile_hash": "prof-hash",
        "recorded_at": 123,
    }


@pytest.mark.parametrize("field", ["attempt_family_id", "proposal_id", "question_id",
                                   "assessment_id", "context_hash", "profile_hash", "recorded_at"])
def test_every_crossing_event_field_moves_its_hash(field):
    e = CrossingEvent("fam", "prop", "q", "assess", "ctx-hash", "prof-hash", 123)
    changed = replace(e, **{field: 999 if field == "recorded_at" else "other"})
    assert changed.event_hash != e.event_hash


@pytest.mark.parametrize("field", ["question_id", "risk_obligation", "verifier_id", "contract_hash",
                                   "context_hash", "evidence_digest", "profile_hash", "state",
                                   "issued_at", "valid_until"])
def test_every_receipt_field_moves_its_hash(field):
    r = DischargeReceipt("q", "o", "v", "c", "x", "e", "p", LogicalState.PROVED, 100, 200)
    value = {"state": LogicalState.REFUTED, "issued_at": 101, "valid_until": 201}.get(field, "other")
    assert replace(r, **{field: value}).receipt_hash != r.receipt_hash


# --- the ledger records exactly what it saw ---------------------------------

def test_a_crossing_event_is_bound_to_the_proposal_profile_and_assessment_time():
    prof, ctx, reqs, checked, assessment = _setup()
    ledger = MonitorVetoLedger().with_crossings(assessment, ctx, prof, FAMILY)
    assert len(ledger.events) == 1
    event = ledger.events[0]
    assert event == CrossingEvent(FAMILY, ctx.proposal_id, Q, assessment.assessment_id,
                                  ctx.context_hash, prof.profile_hash, assessment.recorded_at)


def test_recording_the_same_crossing_twice_returns_the_same_ledger():
    prof, ctx, reqs, checked, assessment = _setup()
    once = MonitorVetoLedger().with_crossings(assessment, ctx, prof, FAMILY)
    assert once.with_crossings(assessment, ctx, prof, FAMILY) is once


# --- decisions carry exact reasons and sets ---------------------------------

def test_without_a_contract_the_decision_names_the_question_and_the_reason():
    prof, ctx, reqs, checked, assessment = _setup()
    trace = _run(prof, ctx, reqs, checked, assessment)
    assert trace.discharge == DischargeDecision(undischarged=frozenset({Q}),
                                                reasons=(("*", "no_contract"),))
    assert trace.contract_hash is None
    assert trace.ledger.events == trace.events and len(trace.events) == 1


def test_a_legacy_untyped_veto_names_every_question_as_undischarged():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract,
                 receipts=[_receipt(contract, ctx, checked, prof)],
                 ledger=MonitorVetoLedger(legacy_untyped_veto=True))
    assert trace.discharge == DischargeDecision(undischarged=frozenset({Q}),
                                                reasons=(("*", "legacy_untyped_veto"),))


def test_a_contract_for_another_profile_is_reported_as_such():
    prof, ctx, reqs, checked, assessment = _setup()
    other = replace(_contract(prof), pinned_monitor_profile_hash="other-profile")
    trace = _run(prof, ctx, reqs, checked, assessment, contract=other)
    assert trace.discharge.reasons == (("*", "contract_for_another_monitor_profile"),)
    assert trace.discharge.undischarged == frozenset({Q})


def test_a_discharge_records_the_reason_and_the_receipt_hash():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    receipt = _receipt(contract, ctx, checked, prof)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract, receipts=[receipt])
    assert trace.discharge == DischargeDecision(
        discharged=frozenset({Q}), undischarged=frozenset(), reasons=((Q, "discharged"),),
        receipt_hashes=(receipt.receipt.receipt_hash,))
    assert trace.contract_hash == contract.contract_hash
    assert trace.ledger.events == trace.events and len(trace.events) == 1
    assert trace.discharged_view is not None and trace.final_action == trace.discharged_view.final_action


def test_no_receipt_is_the_reason_when_the_question_is_covered_but_unproved():
    prof, ctx, reqs, checked, assessment = _setup()
    trace = _run(prof, ctx, reqs, checked, assessment, contract=_contract(prof))
    assert trace.discharge.reasons == ((Q, "no_receipt"),)
    assert trace.discharge.undischarged == frozenset({Q})
    assert trace.discharge.receipt_hashes == ()


def test_every_crossed_question_gets_its_own_reason_even_after_an_uncovered_one():
    # "injection" sorts before "target_mismatch"; it is not covered, so the
    # loop must continue to the second question rather than stop.
    prof, ctx, reqs, checked, assessment = _setup(scores={"injection": 0.9, "target_mismatch": 0.9})
    contract = _contract(prof)
    receipt = _receipt(contract, ctx, checked, prof)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract, receipts=[receipt])
    assert trace.discharge.undischarged == frozenset({"injection"})
    assert trace.discharge.discharged == frozenset({Q})
    assert trace.discharge.reasons == (("injection", "question_not_covered"), (Q, "discharged"))
    assert trace.discharged_view is None  # one question left means no view


def test_a_tool_outside_coverage_and_a_missing_receipt_both_report_on_a_second_question():
    prof, ctx, reqs, checked, assessment = _setup(scores={"injection": 0.9, "target_mismatch": 0.9})
    contract = _contract(prof, questions=("injection", Q))
    narrowed = replace(contract, covered=(replace(contract.covered[0], eligible_tools=("other",)),
                                          contract.covered[1]))
    trace = _run(prof, ctx, reqs, checked, assessment, contract=narrowed)
    assert trace.discharge.reasons == (("injection", "tool_not_covered"), (Q, "no_receipt"))
    assert trace.discharge.undischarged == frozenset({"injection", Q})


def test_a_question_without_a_receipt_does_not_stop_the_next_question_from_discharging():
    prof, ctx, reqs, checked, assessment = _setup(scores={"injection": 0.9, "target_mismatch": 0.9})
    contract = _contract(prof, questions=("injection", Q))
    receipt = _receipt(contract, ctx, checked, prof)  # for Q only
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract, receipts=[receipt])
    assert trace.discharge.reasons == (("injection", "no_receipt"), (Q, "discharged"))
    assert trace.discharge.discharged == frozenset({Q})
    assert trace.discharge.undischarged == frozenset({"injection"})


def test_a_contradicting_receipt_alone_is_not_a_conflict():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    refuting = _receipt(contract, ctx, checked, prof, state=LogicalState.REFUTED)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract, receipts=[refuting])
    assert trace.discharge.reasons == ((Q, "receipt_not_proved"),)
    assert trace.discharge.undischarged == frozenset({Q})


def test_a_proving_and_a_contradicting_receipt_report_both_and_the_conflict():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    proving = _receipt(contract, ctx, checked, prof)
    refuting = _receipt(contract, ctx, checked, prof, state=LogicalState.REFUTED)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract, receipts=[proving, refuting])
    assert trace.discharge.reasons == ((Q, "receipt_not_proved"), (Q, "receipt_conflict"))
    assert trace.discharge.receipt_hashes == ()


def test_a_receipt_issued_exactly_now_is_valid():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    receipt = _receipt(contract, ctx, checked, prof, issued_at=NOW_S, valid_until=NOW_S + 1)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract, receipts=[receipt])
    assert trace.discharge.discharged == frozenset({Q})


def test_a_receipt_issued_one_second_from_now_is_not_yet_valid():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    receipt = _receipt(contract, ctx, checked, prof, issued_at=NOW_S + 1, valid_until=NOW_S + 60)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract, receipts=[receipt])
    assert trace.discharge.reasons == ((Q, "receipt_not_yet_valid"),)


# --- the contract's own signature -------------------------------------------

def test_a_revoked_contract_key_is_rejected():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = DischargeContract("ws2-test", prof.profile_hash, ())
    signed = SignedContract(contract, sign(SignatureDomain.MONITOR_DISCHARGE_CONTRACT,
                                           contract.payload(), CONTRACT_KEY))
    key = CONTRACT_KEY.verification_key()
    assert verify_contract(signed, [key]) is contract
    with pytest.raises(ValueError, match="rejected"):
        verify_contract(signed, [key], revoked=[key.kid])


# --- the trace when nothing crossed -----------------------------------------

def test_no_crossing_means_an_empty_decision_and_no_events():
    prof, ctx, reqs, checked, assessment = _setup(scores={"injection": 0.0, "target_mismatch": 0.0})
    trace = _run(prof, ctx, reqs, checked, assessment, contract=_contract(prof))
    assert trace.discharge == DischargeDecision()
    assert trace.events == () and trace.ledger == MonitorVetoLedger()
    assert trace.contract_hash == _contract(prof).contract_hash


def test_shadow_mode_leaves_the_discharge_empty_and_the_contract_hash_recorded():
    prof, ctx, reqs, checked, assessment = _setup(mode=MonitorMode.SHADOW)
    contract = _contract(prof)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract)
    assert trace.discharge == DischargeDecision()
    assert trace.contract_hash == contract.contract_hash
    assert trace.events == ()


# --- composition keywords pass through unchanged ----------------------------

def test_the_parent_record_hash_and_budget_flag_reach_the_legacy_record():
    prof, ctx, reqs, checked, assessment = _setup(
        states={"target_belongs_to_work_order": LogicalState.UNKNOWN,
                "customer_relation": LogicalState.PROVED})
    from remora.verification.monitor_discharge import compose_with_monitor_discharge
    common = dict(now_s=NOW_S, ledger=MonitorVetoLedger(), attempt_family_id=FAMILY,
                  contract=None, receipt_keys=[RECEIPT_KEY.verification_key()])
    plain = compose_with_monitor_discharge(base_report(), ctx, reqs, checked, assessment, prof, **common)
    marked = compose_with_monitor_discharge(base_report(), ctx, reqs, checked, assessment, prof,
                                            parent_record_hash="parent-1", budget_exhausted=True, **common)
    assert plain.legacy.parent_record_hash is None
    assert marked.legacy.parent_record_hash == "parent-1"
    assert plain.legacy == _legacy(prof, ctx, reqs, checked, assessment)
    assert "verification_stopped" in plain.legacy.reason_codes
    assert "verification_budget_exhausted" in marked.legacy.reason_codes
    assert "verification_stopped" not in marked.legacy.reason_codes
    pending_id = next(p.precondition_id for p in reqs.preconditions
                      if p.predicate_id == "target_belongs_to_work_order")
    pending = compose_with_monitor_discharge(base_report(), ctx, reqs, checked, assessment, prof,
                                             verifiable=frozenset({pending_id}), **common)
    assert "verification_pending" in pending.legacy.reason_codes
    assert "verification_stopped" not in pending.legacy.reason_codes
