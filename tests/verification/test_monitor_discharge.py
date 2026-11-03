# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""WS2-B typed monitor-veto discharge, unwired prototype (WS2 SDD v1.4 §3, §6).

Each test names the SDD §6 row it covers. The legacy composer is the oracle:
every path that does not discharge must return its record unchanged, and the
discharged view must differ from it only in the monitor cap.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from remora.crypto.domain_signing import SignatureDomain, SigningKey, sign
from remora.decision_providers.composition_adapter import MonitorMode, assess_monitor_response
from remora.policy.report import DecisionAction, DecisionReason
from remora.verification.compose import compose_authorized_decision
from remora.verification.monitor_discharge import (
    CoveredQuestion,
    DischargeContract,
    DischargeReceipt,
    MonitorVetoLedger,
    SignedContract,
    SignedReceipt,
    compose_with_monitor_discharge,
    verify_contract,
)
from remora.verification.preconditions import LogicalState, derive_preconditions
from tests.verification._ws1 import (
    NOW_S,
    REGISTRY,
    base_report,
    context,
    h,
    profile,
    response,
    scripted_checked,
)

PROVED = {"target_belongs_to_work_order": LogicalState.PROVED,
          "customer_relation": LogicalState.PROVED}
FAMILY = "family-1"
CONTRACT_KEY = SigningKey.from_text("a1" * 32, [SignatureDomain.MONITOR_DISCHARGE_CONTRACT])
RECEIPT_KEY = SigningKey.from_text("b2" * 32, [SignatureDomain.MONITOR_DISCHARGE_RECEIPT])
OTHER_KEY = SigningKey.from_text("c3" * 32, [SignatureDomain.MONITOR_DISCHARGE_RECEIPT])


def _setup(scores=None, *, states=PROVED, mode=MonitorMode.REQUIRED, uncertainty=()):
    prof = profile(mode)
    ctx, args = context(monitor_profile=prof)
    reqs = derive_preconditions(ctx, args, REGISTRY)
    checked = scripted_checked(ctx, reqs, states)
    raw = response(ctx, checked.evidence_digest, prof=prof,
                   scores=scores or {"injection": 0.0, "target_mismatch": 0.9},
                   uncertainty_codes=list(uncertainty))
    assessment = assess_monitor_response(raw, profile=prof, context_hash=ctx.context_hash,
                                         evidence_digest=checked.evidence_digest,
                                         input_digest=h("in"), now_s=NOW_S)
    return prof, ctx, reqs, checked, assessment


def _contract(prof, questions=("target_mismatch",), *, tools=("set_port_profile",),
              key=CONTRACT_KEY):
    contract = DischargeContract(
        contract_id="ws2-test", pinned_monitor_profile_hash=prof.profile_hash,
        covered=tuple(CoveredQuestion(q, f"obligation:{q}", f"pred:{q}", "intent-verifier",
                                      "intent-source", tools) for q in questions))
    signed = SignedContract(contract, sign(SignatureDomain.MONITOR_DISCHARGE_CONTRACT,
                                           contract.payload(), key))
    return verify_contract(signed, [CONTRACT_KEY.verification_key()])


def _receipt(contract, ctx, checked, prof, question="target_mismatch", *,
             state=LogicalState.PROVED, key=RECEIPT_KEY, **overrides):
    covered = next(c for c in contract.covered if c.question_id == question)
    fields = dict(question_id=question, risk_obligation=covered.risk_obligation,
                  verifier_id=covered.verifier_id, contract_hash=contract.contract_hash,
                  context_hash=ctx.context_hash, evidence_digest=checked.evidence_digest,
                  profile_hash=prof.profile_hash, state=state,
                  issued_at=NOW_S - 1, valid_until=NOW_S + 60)
    fields.update(overrides)
    receipt = DischargeReceipt(**fields)
    return SignedReceipt(receipt, sign(SignatureDomain.MONITOR_DISCHARGE_RECEIPT,
                                       receipt.payload(), key))


def _run(prof, ctx, reqs, checked, assessment, *, contract=None, receipts=(),
         ledger=None, base=None, family=FAMILY):
    return compose_with_monitor_discharge(
        base or base_report(), ctx, reqs, checked, assessment, prof, now_s=NOW_S,
        ledger=ledger or MonitorVetoLedger(), attempt_family_id=family, contract=contract,
        receipts=receipts, receipt_keys=[RECEIPT_KEY.verification_key()])


def _legacy(prof, ctx, reqs, checked, assessment, *, veto=False, base=None):
    return compose_authorized_decision(base or base_report(), ctx, reqs, checked, assessment,
                                       prof, now_s=NOW_S, monitor_veto_on_record=veto)


def _non_monitor(record):
    return [c for c in record.all_caps if c.source != "monitor"]


# B-01: no contract means the legacy record, unchanged.
def test_b01_without_a_contract_the_legacy_record_is_returned_unchanged():
    prof, ctx, reqs, checked, assessment = _setup()
    trace = _run(prof, ctx, reqs, checked, assessment)
    assert trace.legacy == _legacy(prof, ctx, reqs, checked, assessment)
    assert trace.discharged_view is None
    assert trace.final_action == trace.legacy.final_action == "escalate"


# B-02: typed uncertainty still applies after a crossing is discharged.
def test_b02_unsettled_uncertainty_still_caps_after_discharge():
    prof, ctx, reqs, checked, assessment = _setup(uncertainty=("ambiguous_target",))
    contract = _contract(prof)
    trace = compose_with_monitor_discharge(
        base_report(), ctx, reqs, checked, assessment, prof, now_s=NOW_S,
        ledger=MonitorVetoLedger(), attempt_family_id=FAMILY, contract=contract,
        receipts=[_receipt(contract, ctx, checked, prof)],
        receipt_keys=[RECEIPT_KEY.verification_key()], uncertainty_settled=frozenset())
    assert trace.discharge.discharged == {"target_mismatch"}
    assert trace.final_action == "escalate"
    assert "monitor_uncertain_unsettled" in trace.discharged_view.reason_codes


# B-03: an exact, valid receipt lifts only the monitor cap.
def test_b03_exact_receipt_discharges_only_the_monitor_cap():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract,
                 receipts=[_receipt(contract, ctx, checked, prof)])
    assert trace.legacy.final_action == "escalate"
    assert trace.final_action == "accept"
    assert _non_monitor(trace.discharged_view) == _non_monitor(trace.legacy)
    assert trace.legacy.monitor_assessment["crossed"] == ["target_mismatch"]


# B-04: a crossed question without a mapping stays sticky.
def test_b04_uncovered_question_keeps_the_veto():
    prof, ctx, reqs, checked, assessment = _setup({"injection": 0.9, "target_mismatch": 0.0})
    contract = _contract(prof)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract,
                 receipts=[_receipt(contract, ctx, checked, prof)])
    assert trace.final_action == "escalate"
    assert trace.discharge.undischarged == {"injection"}
    assert ("injection", "question_not_covered") in trace.discharge.reasons


# B-05: two crossings, one resolved: the other still blocks.
def test_b05_one_of_two_crossings_resolved_still_blocks():
    prof, ctx, reqs, checked, assessment = _setup({"injection": 0.9, "target_mismatch": 0.9})
    contract = _contract(prof)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract,
                 receipts=[_receipt(contract, ctx, checked, prof)])
    assert trace.discharge.discharged == {"target_mismatch"}
    assert trace.discharge.undischarged == {"injection"}
    assert trace.final_action == "escalate" and trace.discharged_view is None


# B-06: an untyped historical veto is never discharged.
def test_b06_legacy_untyped_veto_stays_sticky():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract,
                 receipts=[_receipt(contract, ctx, checked, prof)],
                 ledger=MonitorVetoLedger(legacy_untyped_veto=True))
    assert trace.final_action == "escalate"
    assert trace.discharge.reasons == (("*", "legacy_untyped_veto"),)
    assert trace.legacy == _legacy(prof, ctx, reqs, checked, assessment, veto=True)


# B-07: a later low score cannot reset recorded history.
def test_b07_low_score_after_a_crossing_does_not_reset_history():
    prof, ctx, reqs, checked, crossed = _setup()
    first = _run(prof, ctx, reqs, checked, crossed)
    *_, calm = _setup({"injection": 0.0, "target_mismatch": 0.0})
    second = _run(prof, ctx, reqs, checked, calm, ledger=first.ledger)
    assert second.final_action == "escalate"
    assert "monitor_veto_sticky" in second.legacy.reason_codes
    assert second.ledger.questions(FAMILY) == {"target_mismatch"}


# B-08: a bad contract signature is refused when loading.
@pytest.mark.parametrize("key", [OTHER_KEY, SigningKey.from_text(
    "d4" * 32, [SignatureDomain.MONITOR_DISCHARGE_CONTRACT])])
def test_b08_contract_with_untrusted_or_wrong_domain_signer_is_rejected(key):
    prof = profile()
    contract = DischargeContract("ws2-test", prof.profile_hash, (
        CoveredQuestion("target_mismatch", "o", "p", "v", "s", ("set_port_profile",)),))
    if SignatureDomain.MONITOR_DISCHARGE_CONTRACT not in key.domains:
        with pytest.raises(ValueError):
            sign(SignatureDomain.MONITOR_DISCHARGE_CONTRACT, contract.payload(), key)
        return
    signed = SignedContract(contract, sign(SignatureDomain.MONITOR_DISCHARGE_CONTRACT,
                                           contract.payload(), key))
    with pytest.raises(ValueError, match="unknown_kid"):
        verify_contract(signed, [CONTRACT_KEY.verification_key()])


def test_b08_tampered_contract_is_rejected():
    prof = profile()
    contract = DischargeContract("ws2-test", prof.profile_hash, (
        CoveredQuestion("target_mismatch", "o", "p", "v", "s", ("set_port_profile",)),))
    sig = sign(SignatureDomain.MONITOR_DISCHARGE_CONTRACT, contract.payload(), CONTRACT_KEY)
    widened = replace(contract, covered=contract.covered + (
        CoveredQuestion("injection", "o", "p", "v", "s", ("set_port_profile",)),))
    with pytest.raises(ValueError, match="signature_invalid"):
        verify_contract(SignedContract(widened, sig), [CONTRACT_KEY.verification_key()])


def test_b08_revoked_receipt_key_does_not_discharge():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    trace = compose_with_monitor_discharge(
        base_report(), ctx, reqs, checked, assessment, prof, now_s=NOW_S,
        ledger=MonitorVetoLedger(), attempt_family_id=FAMILY, contract=contract,
        receipts=[_receipt(contract, ctx, checked, prof)],
        receipt_keys=[RECEIPT_KEY.verification_key()], revoked=[RECEIPT_KEY.kid])
    assert trace.final_action == "escalate"
    assert ("target_mismatch", "receipt_key_revoked") in trace.discharge.reasons


def test_b08_contract_pinned_to_another_monitor_profile_does_not_discharge():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(profile(MonitorMode.REQUIRED, calibration_hash=h("other")))
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract,
                 receipts=[_receipt(contract, ctx, checked, prof)])
    assert trace.final_action == "escalate"
    assert trace.discharge.reasons == (("*", "contract_for_another_monitor_profile"),)


# B-09: any binding mismatch on the receipt refuses discharge.
@pytest.mark.parametrize("field, value, reason", [
    ("context_hash", h("another-context"), "receipt_binding_context"),
    ("evidence_digest", h("another-revision"), "receipt_binding_evidence"),
    ("profile_hash", h("another-profile"), "receipt_binding_profile"),
    ("contract_hash", h("another-contract"), "receipt_binding_contract"),
    ("verifier_id", "some-other-verifier", "receipt_binding_verifier"),
    ("risk_obligation", "obligation:other", "receipt_binding_obligation"),
])
def test_b09_receipt_binding_mismatch_does_not_discharge(field, value, reason):
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    receipt = _receipt(contract, ctx, checked, prof, **{field: value})
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract, receipts=[receipt])
    assert trace.final_action == "escalate"
    assert ("target_mismatch", reason) in trace.discharge.reasons


def test_b09_tool_outside_the_contract_does_not_discharge():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof, tools=("send_report",))
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract,
                 receipts=[_receipt(contract, ctx, checked, prof)])
    assert trace.final_action == "escalate"
    assert ("target_mismatch", "tool_not_covered") in trace.discharge.reasons


def test_b09_receipt_signed_by_an_untrusted_verifier_does_not_discharge():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract,
                 receipts=[_receipt(contract, ctx, checked, prof, key=OTHER_KEY)])
    assert trace.final_action == "escalate"
    assert ("target_mismatch", "receipt_unknown_kid") in trace.discharge.reasons


def test_b09_tampered_receipt_does_not_discharge():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    good = _receipt(contract, ctx, checked, prof, state=LogicalState.UNKNOWN)
    forged = SignedReceipt(replace(good.receipt, state=LogicalState.PROVED), good.signature)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract, receipts=[forged])
    assert trace.final_action == "escalate"
    assert ("target_mismatch", "receipt_signature_invalid") in trace.discharge.reasons


# B-10: stale, unproved or conflicting evidence refuses discharge.
@pytest.mark.parametrize("overrides, reason", [
    ({"valid_until": NOW_S}, "receipt_expired"),
    ({"issued_at": NOW_S + 5}, "receipt_not_yet_valid"),
    ({"state": LogicalState.UNKNOWN}, "receipt_not_proved"),
    ({"state": LogicalState.REFUTED}, "receipt_not_proved"),
    ({"state": LogicalState.CONFLICT}, "receipt_not_proved"),
])
def test_b10_stale_or_unproved_receipt_does_not_discharge(overrides, reason):
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract,
                 receipts=[_receipt(contract, ctx, checked, prof, **overrides)])
    assert trace.final_action == "escalate"
    assert ("target_mismatch", reason) in trace.discharge.reasons


def test_b10_a_contradicting_receipt_beside_a_proving_one_does_not_discharge():
    prof, ctx, reqs, checked, assessment = _setup()
    contract = _contract(prof)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract, receipts=[
        _receipt(contract, ctx, checked, prof),
        _receipt(contract, ctx, checked, prof, state=LogicalState.REFUTED)])
    assert trace.final_action == "escalate"
    assert ("target_mismatch", "receipt_conflict") in trace.discharge.reasons


# B-11: a deterministic refusal is never lifted by discharge.
@pytest.mark.parametrize("states, base", [
    ({"target_belongs_to_work_order": LogicalState.REFUTED,
      "customer_relation": LogicalState.PROVED}, None),
    (PROVED, base_report(DecisionAction.ABSTAIN, (DecisionReason.DEFAULT_SAFE_ABSTAIN,))),
])
def test_b11_deterministic_refusal_survives_discharge(states, base):
    prof, ctx, reqs, checked, assessment = _setup(states=states)
    contract = _contract(prof)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=contract, base=base,
                 receipts=[_receipt(contract, ctx, checked, prof)])
    assert trace.discharge.discharged == {"target_mismatch"}
    assert trace.final_action == trace.legacy.final_action == "abstain"


# B-12: history is per attempt family and survives a new proposal id.
def test_b12_new_proposal_in_the_same_family_keeps_history():
    prof, ctx, reqs, checked, crossed = _setup()
    first = _run(prof, ctx, reqs, checked, crossed)
    ctx2, args2 = context(monitor_profile=prof, proposal_id="p-2")
    reqs2 = derive_preconditions(ctx2, args2, REGISTRY)
    checked2 = scripted_checked(ctx2, reqs2, PROVED)
    raw = response(ctx2, checked2.evidence_digest, prof=prof,
                   scores={"injection": 0.0, "target_mismatch": 0.0})
    calm = assess_monitor_response(raw, profile=prof, context_hash=ctx2.context_hash,
                                   evidence_digest=checked2.evidence_digest,
                                   input_digest=h("in"), now_s=NOW_S)
    same = _run(prof, ctx2, reqs2, checked2, calm, ledger=first.ledger)
    other = _run(prof, ctx2, reqs2, checked2, calm, ledger=first.ledger, family="family-2")
    assert same.final_action == "escalate"
    assert other.final_action == "accept"


def test_b12_ledger_is_immutable_and_events_are_hash_bound():
    prof, ctx, reqs, checked, crossed = _setup()
    empty = MonitorVetoLedger()
    after = _run(prof, ctx, reqs, checked, crossed, ledger=empty).ledger
    assert empty.events == ()
    (event,) = after.events
    assert event.assessment_id == crossed.assessment_id
    assert event.context_hash == ctx.context_hash and len(event.event_hash) == 64


# B-14: a monitor outage after discharge is no implicit low-risk reading.
def test_b14_history_discharged_while_monitor_is_unavailable_still_refuses():
    prof, ctx, reqs, checked, crossed = _setup()
    first = _run(prof, ctx, reqs, checked, crossed)
    contract = _contract(prof)
    trace = _run(prof, ctx, reqs, checked, None, contract=contract, ledger=first.ledger,
                 receipts=[_receipt(contract, ctx, checked, prof)])
    assert trace.discharge.discharged == {"target_mismatch"}
    assert trace.final_action == "abstain"
    assert "monitor_not_requested" in trace.discharged_view.reason_codes


# B-17: zero coverage is reported honestly, with no extrapolation.
def test_b17_contract_with_no_covered_questions_discharges_nothing():
    prof, ctx, reqs, checked, assessment = _setup()
    trace = _run(prof, ctx, reqs, checked, assessment, contract=_contract(prof, questions=()))
    assert trace.discharge.discharged == frozenset()
    assert trace.discharge.undischarged == {"target_mismatch"}
    assert trace.final_action == "escalate"


def test_shadow_monitor_needs_no_discharge_and_records_no_history():
    prof, ctx, reqs, checked, assessment = _setup(mode=MonitorMode.SHADOW)
    trace = _run(prof, ctx, reqs, checked, assessment, contract=_contract(prof))
    assert trace.final_action == "accept" and trace.discharged_view is None
    assert trace.ledger.events == ()
