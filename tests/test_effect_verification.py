# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Effect verification compares the declared delta, and refuses to guess.

Two conflations this suite exists to prevent, both easy to introduce by
someone tidying the code later:

1. **not observed is not mismatch.** A reader that cannot see the object
   tells us nothing about whether the action was right. Reporting it as a
   mismatch would manufacture incidents and, worse, make a genuine
   mismatch indistinguishable from a timeout.
2. **fields outside the declared delta are not this action's business.**
   Checking global unchangedness makes every concurrent legitimate write
   an EFFECT_MISMATCH, and operators stop reading a channel that is mostly
   noise.
"""
from __future__ import annotations

from datetime import UTC, datetime

from remora.governance.effect_verification import (
    EffectStatus,
    EffectVerification,
    PostconditionContract,
    verify_declared_delta,
)

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def _contract(**overrides) -> PostconditionContract:
    base = dict(
        tool_id="update_work_order",
        reader="get_work_order",
        target_selector={"id": "WO-1"},
        expected_fields={"status": "IN_PROGRESS"},
        comparison_rules={},
    )
    base.update(overrides)
    return PostconditionContract(**base)


def _verify(contract, observed):
    return verify_declared_delta(
        contract, observed, proposal_id="p-1", execution_id="e-1",
        toolspec_hash="d" * 64, verifier_identity="reader@test", now=NOW,
    )


def test_matching_declared_delta_verifies() -> None:
    r = _verify(_contract(), {"status": "IN_PROGRESS", "version": 2})
    assert r.status is EffectStatus.VERIFIED
    assert r.reason_code == "postcondition_verified"
    assert r.status.is_terminal


def test_unrelated_concurrent_change_is_not_a_mismatch() -> None:
    """Another writer touched updated_at. Not this action's problem."""
    r = _verify(_contract(), {
        "status": "IN_PROGRESS", "updated_at": "later", "assignee": "someone",
    })
    assert r.status is EffectStatus.VERIFIED, (
        "checking global unchangedness would drown the signal in noise"
    )


def test_wrong_declared_value_is_a_mismatch() -> None:
    r = _verify(_contract(), {"status": "CLOSED"})
    assert r.status is EffectStatus.MISMATCH
    assert r.reason_code == "postcondition_field_mismatch"
    assert "CLOSED" in r.detail


def test_absent_object_is_unobservable_not_mismatch() -> None:
    """The distinction the whole design turns on."""
    r = _verify(_contract(), None)
    assert r.status is EffectStatus.UNOBSERVABLE
    assert r.status.is_terminal is False, "unknown must not freeze into a verdict"
    assert "not failed" in r.detail


def test_version_increment_rule() -> None:
    contract = _contract(
        expected_fields={"version": 3},
        comparison_rules={"version": "version_increment"},
    )
    assert _verify(contract, {"version": 4}).status is EffectStatus.VERIFIED
    stale = _verify(contract, {"version": 3})
    assert stale.status is EffectStatus.MISMATCH
    assert stale.reason_code == "postcondition_version_not_advanced"


def test_hash_rule_compares_content_not_identity() -> None:
    from remora.governance.effect_verification import _digest

    body = {"text": "a long body"}
    contract = _contract(
        expected_fields={"body": _digest(body)},
        comparison_rules={"body": "hash"},
    )
    assert _verify(contract, {"body": body}).status is EffectStatus.VERIFIED
    assert _verify(contract, {"body": {"text": "different"}}).status is (
        EffectStatus.MISMATCH
    )


def test_presence_and_absence_rules() -> None:
    contract = _contract(
        expected_fields={"id": None, "deleted_at": None},
        comparison_rules={"id": "present", "deleted_at": "absent"},
    )
    assert _verify(contract, {"id": "WO-1"}).status is EffectStatus.VERIFIED
    assert _verify(contract, {"id": "WO-1", "deleted_at": "x"}).status is (
        EffectStatus.MISMATCH
    )


def test_both_sides_are_hashed_for_independent_recheck() -> None:
    """A verdict a reader cannot re-derive is a claim, not evidence."""
    matched = _verify(_contract(), {"status": "IN_PROGRESS"})
    assert len(matched.expected_sha256) == 64
    assert len(matched.observed_sha256) == 64
    # On a match the two digests coincide — that IS the re-derivable claim.
    assert matched.expected_sha256 == matched.observed_sha256

    # On a mismatch they must differ, or the hashes would not witness it.
    diverged = _verify(_contract(), {"status": "CLOSED"})
    assert diverged.expected_sha256 != diverged.observed_sha256


def test_verification_is_immutable() -> None:
    import pytest

    r = _verify(_contract(), {"status": "IN_PROGRESS"})
    with pytest.raises(Exception):
        r.status = EffectStatus.VERIFIED  # type: ignore[misc]
    with pytest.raises(TypeError):
        r.observed["status"] = "tampered"  # type: ignore[index]


def test_unsupported_is_a_status_not_a_silence() -> None:
    """A tool with no contract must still produce a record: absence of
    verification has to be visible, not inferred from a missing field."""
    r = EffectVerification.build(
        proposal_id="p", execution_id="e", tool_id="read_only_tool",
        toolspec_hash="d" * 64, status=EffectStatus.UNSUPPORTED,
        reason_code="postcondition_not_declared",
        verifier_identity="none", now=NOW,
    )
    assert r.status is EffectStatus.UNSUPPORTED
    assert r.to_dict()["reason_code"] == "postcondition_not_declared"


def test_every_reason_code_used_is_published() -> None:
    import pathlib

    import yaml

    contract_file = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parents[1] / "schemas"
         / "postcondition_contract_v1.yaml").read_text(encoding="utf-8")
    )
    published = {e["code"] for e in contract_file["reason_codes"]}
    used = {
        _verify(_contract(), {"status": "IN_PROGRESS"}).reason_code,
        _verify(_contract(), {"status": "CLOSED"}).reason_code,
        _verify(_contract(), None).reason_code,
        _verify(_contract(expected_fields={"version": 3},
                          comparison_rules={"version": "version_increment"}),
                {"version": 3}).reason_code,
    }
    assert used <= published, used - published


def test_statuses_match_the_frozen_contract() -> None:
    import pathlib

    import yaml

    contract_file = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parents[1] / "schemas"
         / "postcondition_contract_v1.yaml").read_text(encoding="utf-8")
    )
    declared = {e["status"] for e in contract_file["statuses"]}
    assert {s.value for s in EffectStatus} == declared
