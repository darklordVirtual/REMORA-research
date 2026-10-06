# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pre-Federation probes for deep immutability of safety/evidence objects."""
from __future__ import annotations

from remora.governance.effect_verification import (
    EffectStatus,
    EffectVerification,
    PostconditionContract,
    effect_digest,
    verify_declared_delta,
)
from remora.sdk.effects import build_postcondition


def test_effect_verification_content_cannot_drift_after_hashing():
    """The retained object must still hash to the digest stored beside it."""
    nested = {"body": {"mode": "safe"}}
    record = EffectVerification.build(
        proposal_id="p-1",
        execution_id="e-1",
        tool_id="update",
        toolspec_hash="d" * 64,
        status=EffectStatus.VERIFIED,
        reason_code="postcondition_verified",
        verifier_identity="reader",
        expected=nested,
        observed=nested,
    )
    original = record.observed_sha256

    nested["body"]["mode"] = "unsafe"

    assert effect_digest(dict(record.observed)) == original, (
        "nested caller-owned data changed after the verification digest was "
        "computed; the record is no longer self-consistent"
    )


def test_postcondition_contract_cannot_be_rewritten_through_nested_alias():
    """A frozen safety contract must not change when its source mapping changes."""
    declared = {"config": {"mode": "safe"}}
    contract = PostconditionContract(
        tool_id="update",
        reader="reader",
        target_selector={"id": "1"},
        expected_fields=declared,
    )

    declared["config"]["mode"] = "unsafe"

    result = verify_declared_delta(
        contract,
        {"config": {"mode": "unsafe"}},
        proposal_id="p-1",
        execution_id="e-1",
        toolspec_hash="d" * 64,
        verifier_identity="reader",
    )
    assert result.status is EffectStatus.MISMATCH, (
        "the postcondition changed after declaration through a nested alias"
    )


def test_sdk_postcondition_is_deeply_detached_from_caller_input():
    """The public product contract must own its declaration bytes."""
    declared = {"config": {"mode": "safe"}}
    spec = build_postcondition(
        tool_id="update",
        target_selector={"id": "1"},
        expected_fields=declared,
        reader="reader",
    )
    declared["config"]["mode"] = "unsafe"

    assert spec.expected_fields["config"]["mode"] == "safe"


def test_to_dict_remains_recheckable_after_nested_mutation_attempt():
    nested = {"body": {"items": [1, 2]}}
    record = EffectVerification.build(
        proposal_id="p-1",
        execution_id="e-1",
        tool_id="update",
        toolspec_hash="d" * 64,
        status=EffectStatus.VERIFIED,
        reason_code="postcondition_verified",
        verifier_identity="reader",
        expected=nested,
        observed=nested,
    )
    nested["body"]["items"].append(3)

    wire = record.to_dict()
    assert effect_digest(wire["expected"]) == wire["expected_sha256"]
    assert effect_digest(wire["observed"]) == wire["observed_sha256"]
