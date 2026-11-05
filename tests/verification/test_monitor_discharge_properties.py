# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Property tests over typed monitor-veto discharge (test plan item 5, 2026-11-04).

Random receipts with random bindings, keys, states and times: a crossing is
discharged only when every binding matches, the signer is trusted and
unrevoked, the state is PROVED and the receipt is current; and a discharged
view never differs from the legacy record anywhere but the monitor cap.
"""
from __future__ import annotations

from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st

from remora.crypto.domain_signing import SignatureDomain, SigningKey, sign
from remora.decision_providers.composition_adapter import MonitorMode, assess_monitor_response
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
from tests.verification._ws1 import NOW_S, REGISTRY, base_report, context, h, profile, response, scripted_checked

PROVED = {"target_belongs_to_work_order": LogicalState.PROVED, "customer_relation": LogicalState.PROVED}
CONTRACT_KEY = SigningKey.from_text("a1" * 32, [SignatureDomain.MONITOR_DISCHARGE_CONTRACT])
RECEIPT_KEY = SigningKey.from_text("b2" * 32, [SignatureDomain.MONITOR_DISCHARGE_RECEIPT])
OTHER_KEY = SigningKey.from_text("c3" * 32, [SignatureDomain.MONITOR_DISCHARGE_RECEIPT])


def _setup():
    prof = profile(MonitorMode.REQUIRED)
    ctx, args = context(monitor_profile=prof)
    reqs = derive_preconditions(ctx, args, REGISTRY)
    checked = scripted_checked(ctx, reqs, PROVED)
    raw = response(ctx, checked.evidence_digest, prof=prof, scores={"injection": 0.0, "target_mismatch": 0.9})
    assessment = assess_monitor_response(raw, profile=prof, context_hash=ctx.context_hash,
                                         evidence_digest=checked.evidence_digest, input_digest=h("in"), now_s=NOW_S)
    contract = DischargeContract("ws2-prop", prof.profile_hash, (
        CoveredQuestion("target_mismatch", "obligation:target", "pred:target", "intent-verifier", "intent-source",
                        ("set_port_profile",)),))
    signed = SignedContract(contract, sign(SignatureDomain.MONITOR_DISCHARGE_CONTRACT, contract.payload(), CONTRACT_KEY))
    return prof, ctx, reqs, checked, assessment, verify_contract(signed, [CONTRACT_KEY.verification_key()])


ENV = _setup()


@st.composite
def receipts(draw):
    prof, ctx, reqs, checked, assessment, contract = ENV
    covered = contract.covered[0]
    wrong = lambda good, alt: draw(st.sampled_from([good, alt]))  # noqa: E731
    fields = dict(
        question_id=wrong("target_mismatch", "injection"),
        risk_obligation=wrong(covered.risk_obligation, "obligation:other"),
        verifier_id=wrong(covered.verifier_id, "other-verifier"),
        contract_hash=wrong(contract.contract_hash, h("other-contract")),
        context_hash=wrong(ctx.context_hash, h("other-context")),
        evidence_digest=wrong(checked.evidence_digest, h("other-evidence")),
        profile_hash=wrong(prof.profile_hash, h("other-profile")),
        state=draw(st.sampled_from(list(LogicalState))),
        issued_at=draw(st.integers(min_value=NOW_S - 100, max_value=NOW_S + 100)),
        valid_until=draw(st.integers(min_value=NOW_S - 100, max_value=NOW_S + 100)),
    )
    key = draw(st.sampled_from([RECEIPT_KEY, OTHER_KEY]))
    tamper = draw(st.booleans())
    receipt = DischargeReceipt(**fields)
    signature = sign(SignatureDomain.MONITOR_DISCHARGE_RECEIPT, receipt.payload(), key)
    if tamper:
        receipt = replace(receipt, state=LogicalState.PROVED)
    return SignedReceipt(receipt, signature), key is RECEIPT_KEY and not tamper


def _exact(signed: SignedReceipt) -> bool:
    prof, ctx, reqs, checked, assessment, contract = ENV
    r, c = signed.receipt, contract.covered[0]
    return (r.question_id == "target_mismatch" and r.risk_obligation == c.risk_obligation
            and r.verifier_id == c.verifier_id and r.contract_hash == contract.contract_hash
            and r.context_hash == ctx.context_hash and r.evidence_digest == checked.evidence_digest
            and r.profile_hash == prof.profile_hash and r.state is LogicalState.PROVED
            and r.issued_at <= NOW_S < r.valid_until)


@settings(max_examples=500, deadline=None)
@given(st.lists(receipts(), min_size=0, max_size=3), st.booleans())
def test_discharge_only_with_an_exact_trusted_proved_current_receipt_and_no_contradiction(items, legacy_veto):
    prof, ctx, reqs, checked, assessment, contract = ENV
    signed = [s for s, _ in items]
    trace = compose_with_monitor_discharge(
        base_report(), ctx, reqs, checked, assessment, prof, now_s=NOW_S,
        ledger=MonitorVetoLedger(legacy_untyped_veto=legacy_veto), attempt_family_id="fam",
        contract=contract, receipts=signed, receipt_keys=[RECEIPT_KEY.verification_key()])
    proving = [s for s, honest in items if honest and _exact(s)]
    # a validly signed, fully bound receipt that is not PROVED contradicts
    contradicting = [s for s, honest in items if honest and s.receipt.question_id == "target_mismatch"
                     and _exact(replace(s, receipt=replace(s.receipt, state=LogicalState.PROVED)))
                     and s.receipt.state is not LogicalState.PROVED]
    should = bool(proving) and not contradicting and not legacy_veto
    assert ("target_mismatch" in trace.discharge.discharged) == should, (trace.discharge.reasons, [i[0].receipt for i in items])
    if not should:
        assert trace.discharged_view is None
        assert trace.final_action == trace.legacy.final_action == "escalate"
    else:
        legacy_other = [c for c in trace.legacy.all_caps if c.source != "monitor"]
        view_other = [c for c in trace.discharged_view.all_caps if c.source != "monitor"]
        assert view_other == legacy_other
        assert trace.final_action == "accept"
