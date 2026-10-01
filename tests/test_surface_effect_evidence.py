# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
from copy import deepcopy

import pytest

from remora.governance.effect_verification import PostconditionContract
from remora.toolcall.surface_effect_evidence import build_effect_evidence, recheck_effect_evidence

AT = "2026-01-01T00:00:01+00:00"
EVENTS = [{"event": "execution_result", "timestamp": "2026-01-01T00:00:00+00:00",
           "payload": {"proposal_id": "p", "tool_call_hash": "a" * 64,
                       "grant_jti": "g", "tool_executed": True}}]
CONTRACT = PostconditionContract("write", "reader", {"id": "row"}, {"value": 1})


def build(observed, **kwargs):
    fields = dict(contract=CONTRACT, observed=observed, events=EVENTS,
                  proposal_id="p", tool_call_hash="a" * 64, grant_jti="g",
                  verified_at=AT, verifier_identity="reader", principal="reader",
                  trusted_verifiers={"reader": "reader"})
    fields.update(kwargs)
    return build_effect_evidence(**fields)


def check(evidence):
    return recheck_effect_evidence(evidence, contract=CONTRACT, events=EVENTS,
                                   principal="reader", trusted_verifiers={"reader": "reader"})


def test_success_and_bound_receipt_without_readback_does_not_prove_effect():
    evidence = build(None)
    assert evidence["binding_verdict"] == "FRESH_AND_BOUND"
    assert evidence["property_verdict"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize("observation,verdict", [({"value": 1}, "EFFECT_VERIFIED"),
                                                ({"value": 2}, "EFFECT_MISMATCH")])
def test_positive_and_negative_verdicts_recheck_with_same_evidence_burden(observation, verdict):
    evidence = build(observation)
    assert evidence["property_verdict"] == verdict
    assert check(evidence)["property_verdict"] == verdict
    damaged = deepcopy(evidence)
    damaged["observed"]["value"] = 99
    with pytest.raises(ValueError):
        check(damaged)


@pytest.mark.parametrize("change", [{"grant_jti": "wrong"}, {"tool_call_hash": "b" * 64},
                                    {"principal": "attacker"}, {"verified_at": "2025-01-01T00:00:00Z"}])
def test_wrong_execution_principal_action_or_old_observation_cannot_settle(change):
    with pytest.raises(ValueError):
        build({"value": 1}, **change)


def test_receipt_verdict_cannot_be_changed_even_with_same_maps():
    evidence = build({"value": 2})
    evidence["property_verdict"] = "EFFECT_VERIFIED"
    with pytest.raises(ValueError):
        check(evidence)


def test_contract_and_trusted_dispatch_are_required_for_rechecking():
    evidence = build({"value": 1})
    with pytest.raises(ValueError):
        recheck_effect_evidence(evidence, contract=PostconditionContract("write", "reader", {}, {"value": 2}),
                               events=EVENTS, principal="reader", trusted_verifiers={"reader": "reader"})
    with pytest.raises(ValueError):
        recheck_effect_evidence(evidence, contract=CONTRACT, events=[], principal="reader",
                               trusted_verifiers={"reader": "reader"})


def test_empty_contract_unknown_rules_and_late_observations_refuse():
    for contract in (PostconditionContract("write", "reader", {}, {}),
                     PostconditionContract("write", "reader", {}, {"value": 1}, {"value": "guess"})):
        with pytest.raises(ValueError):
            build({"value": 1}, contract=contract)
    with pytest.raises(ValueError, match="deadline_exceeded"):
        build({"value": 1}, verified_at="2026-01-01T00:01:00+00:00")


def test_missing_null_is_mismatch_and_extra_observed_fields_are_allowed():
    assert build({}, contract=PostconditionContract("write", "reader", {}, {"value": None}))["property_verdict"] == "EFFECT_MISMATCH"
    assert build({"value": 1, "unrelated": 2})["property_verdict"] == "EFFECT_VERIFIED"
