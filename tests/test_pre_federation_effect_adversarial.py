# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pre-Federation adversarial probes for effect-verification fail-closed semantics.

These tests deliberately exercise the core/SDK path, not only the stricter
surface-effect-evidence wrapper.  A Federation-facing property should not
change merely because one caller used a wrapper that adds extra validation.
"""
from __future__ import annotations

import pytest

from remora.governance.effect_verification import (
    EffectStatus,
    PostconditionContract,
    verify_declared_delta,
)
from remora.sdk.effects import build_postcondition, verify_effect


def _core(contract: PostconditionContract, observed):
    return verify_declared_delta(
        contract,
        observed,
        proposal_id="p-1",
        execution_id="e-1",
        toolspec_hash="d" * 64,
        verifier_identity="reader@test",
    )


def test_exact_null_requires_field_presence_in_core_verifier():
    """Missing is not the same observation as an explicitly present JSON null."""
    contract = PostconditionContract(
        tool_id="update",
        reader="reader@test",
        target_selector={"id": "1"},
        expected_fields={"deleted_at": None},
        comparison_rules={"deleted_at": "exact"},
    )
    missing = _core(contract, {})
    explicit_null = _core(contract, {"deleted_at": None})

    assert missing.status is EffectStatus.MISMATCH
    assert explicit_null.status is EffectStatus.VERIFIED


def test_exact_null_requires_field_presence_through_public_sdk():
    """The product-facing SDK must preserve the core missing-vs-null distinction."""
    spec = build_postcondition(
        tool_id="update",
        target_selector={"id": "1"},
        expected_fields={"deleted_at": None},
        comparison_rules={"deleted_at": "exact"},
        reader="reader@test",
    )
    result = verify_effect(
        spec,
        {},
        proposal_id="p-1",
        execution_id="e-1",
        toolspec_hash="d" * 64,
        verifier_identity="reader@test",
    )
    assert result.status.value == "EFFECT_MISMATCH"


def test_unknown_comparison_rule_cannot_silently_become_exact():
    """A typo in a safety contract must fail closed, not change semantics."""
    contract = PostconditionContract(
        tool_id="update",
        reader="reader@test",
        target_selector={"id": "1"},
        expected_fields={"status": "closed"},
        comparison_rules={"status": "excat"},
    )
    with pytest.raises(ValueError):
        _core(contract, {"status": "closed"})


def test_public_sdk_rejects_unknown_comparison_rule():
    """The documented SDK is a product boundary and must validate the vocabulary."""
    with pytest.raises(ValueError):
        build_postcondition(
            tool_id="update",
            target_selector={"id": "1"},
            expected_fields={"status": "closed"},
            comparison_rules={"status": "excat"},
            reader="reader@test",
        )


def test_rule_for_undeclared_field_is_not_silently_ignored():
    """A malformed rule map must not be accepted with an unused safety clause."""
    with pytest.raises(ValueError):
        build_postcondition(
            tool_id="update",
            target_selector={"id": "1"},
            expected_fields={"status": "closed"},
            comparison_rules={"status": "exact", "owner": "exact"},
            reader="reader@test",
        )
