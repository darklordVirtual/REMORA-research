# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The frozen postcondition contract, pinned before anything implements it.

Handoff gate §2.2/§2.3. The decision this suite exists to protect is the
one the architect review made binding:

    verify the DECLARED DELTA against the version your own write produced,
    never global unchangedness.

A system of record has other legitimate writers. Checking that nothing
else changed makes EFFECT_MISMATCH a noise channel, and a signal
operators learn to ignore costs attention while providing nothing. That
choice is easy to erode later ("just also check updated_at"), so it is
asserted here rather than left in prose.
"""
from __future__ import annotations

from pathlib import Path

import yaml

CONTRACT = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "schemas"
     / "postcondition_contract_v1.yaml").read_text(encoding="utf-8")
)


def test_contract_is_frozen_and_dated() -> None:
    assert CONTRACT["schema_version"] == 1
    assert CONTRACT["status"] == "frozen"
    assert CONTRACT["frozen_at"] == "2026-08-05"


def test_comparison_is_declared_delta_not_global_unchangedness() -> None:
    """The architect review's binding decision."""
    semantics = CONTRACT["comparison_semantics"]
    assert semantics["mode"] == "declared_delta_against_own_version"
    assert semantics["forbidden_mode"] == "global_unchangedness"
    assert semantics["rationale"] and semantics["forbidden_rationale"]


def test_unobservable_is_never_a_mismatch() -> None:
    """Failing to READ a result is not evidence the wrong thing happened —
    and collapsing them would make a real mismatch indistinguishable from
    a network timeout."""
    invariants = CONTRACT["invariants"]
    assert invariants["unobservable_is_not_mismatch"] is True
    assert invariants["unobservable_rationale"]


def test_verification_never_re_executes_the_action() -> None:
    assert CONTRACT["invariants"]["verification_never_re_executes"] is True


def test_required_fields_cover_the_handoff_gate_list() -> None:
    required = set(CONTRACT["required_contract_fields"])
    for field in (
        "tool_id", "reader", "target_selector", "expected_fields",
        "comparison_rules", "observation_deadline_seconds", "repeatable",
        "evidence_fields", "unobservable_is_not_mismatch",
    ):
        assert field in required, f"handoff gate §2.2 requires {field}"


# ── The five statuses ──────────────────────────────────────────────────────

EXPECTED_STATUSES = {
    "EFFECT_VERIFIED", "EFFECT_MISMATCH", "EFFECT_UNOBSERVABLE",
    "EFFECT_VERIFIER_FAILED", "EFFECT_UNSUPPORTED",
}


def test_statuses_are_exactly_the_published_five() -> None:
    """Collapsing any pair loses a distinction an operator needs in order
    to decide what to do next."""
    actual = {entry["status"] for entry in CONTRACT["statuses"]}
    assert actual == EXPECTED_STATUSES, {
        "added": actual - EXPECTED_STATUSES,
        "removed": EXPECTED_STATUSES - actual,
    }


def test_every_status_states_terminality_and_an_operator_action() -> None:
    for entry in CONTRACT["statuses"]:
        assert "terminal" in entry, f"{entry['status']}: terminality unstated"
        assert entry.get("operator_action"), (
            f"{entry['status']}: a status nobody can act on is a label"
        )


def test_unobservable_and_verifier_failure_are_not_terminal() -> None:
    """Both mean 'we do not know yet'. Marking them terminal would freeze
    an unknown into a verdict."""
    by_status = {e["status"]: e for e in CONTRACT["statuses"]}
    assert by_status["EFFECT_UNOBSERVABLE"]["terminal"] is False
    assert by_status["EFFECT_VERIFIER_FAILED"]["terminal"] is False


def test_unsupported_is_recorded_rather_than_omitted() -> None:
    """A tool with no contract must produce a status, not silence: absence
    of verification has to be visible."""
    by_status = {e["status"]: e for e in CONTRACT["statuses"]}
    assert by_status["EFFECT_UNSUPPORTED"]["terminal"] is True


# ── Reason codes ───────────────────────────────────────────────────────────

EXPECTED_REASON_CODES = {
    "postcondition_verified",
    "postcondition_field_mismatch",
    "postcondition_object_absent",
    "postcondition_version_not_advanced",
    "postcondition_read_timeout",
    "postcondition_reader_error",
    "postcondition_reader_unauthorized",
    "postcondition_not_declared",
}


def test_reason_codes_are_exactly_the_published_set() -> None:
    actual = {entry["code"] for entry in CONTRACT["reason_codes"]}
    assert actual == EXPECTED_REASON_CODES, {
        "added": actual - EXPECTED_REASON_CODES,
        "removed": EXPECTED_REASON_CODES - actual,
    }


def test_read_failures_have_distinct_codes_from_content_failures() -> None:
    """A timeout, an unauthorized reader and a wrong value are three
    different problems with three different fixes."""
    codes = {entry["code"] for entry in CONTRACT["reason_codes"]}
    assert {"postcondition_read_timeout", "postcondition_reader_error",
            "postcondition_reader_unauthorized"} <= codes
    assert {"postcondition_field_mismatch",
            "postcondition_object_absent"} <= codes


# ── Lifecycle integration ──────────────────────────────────────────────────

def test_lifecycle_states_are_declared_with_terminality() -> None:
    lifecycle = CONTRACT["lifecycle"]
    added = set(lifecycle["added_states"])
    assert added == {"EFFECT_PENDING", "EFFECT_VERIFIED", "EFFECT_MISMATCH",
                     "EFFECT_UNKNOWN"}
    assert set(lifecycle["terminal_states"]) <= added
    assert set(lifecycle["non_terminal_states"]) <= added
    assert not (set(lifecycle["terminal_states"])
                & set(lifecycle["non_terminal_states"]))


def test_effect_unknown_resolves_without_rewriting_history() -> None:
    """Same discipline as dispatch UNKNOWN: the uncertainty happened."""
    assert "never rewrites" in CONTRACT["lifecycle"]["unknown_resolution"]


# ── Evidence ───────────────────────────────────────────────────────────────

def test_evidence_hashes_both_sides_and_never_overwrites() -> None:
    """A verification that could edit the record it verifies proves
    nothing; hashing both sides lets a later reader check the comparison
    instead of trusting the verdict."""
    evidence = CONTRACT["evidence"]
    assert evidence["hashes_expected_and_observed"] is True
    assert evidence["appends_to_audit_chain"] is True
    assert evidence["included_in_evidence_export"] is True
    assert evidence["never_overwrites_history"] is True


def test_realization_does_not_overclaim() -> None:
    realization = CONTRACT["realization"]
    assert realization["contract"] == "frozen"
    assert realization["runtime"] == "not_implemented"
    assert realization["sdk_surface"] == "not_implemented"
    assert realization["first_integration"] == "github_issue_creation"
