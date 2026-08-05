# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""What a product consumer sees of ToolSpec identity and effect verification.

Handoff gate §2.4/PR 5. The consuming product must be able to build a
postcondition, verify it with its own reader, read the spec identity that
authorized the action, and see the verdict on a proposal — all through
``remora.sdk`` and nothing else. That constraint is the point: a product
that reaches into ``remora.governance`` or ``remora.enforcement`` is
coupled to internals we intend to keep changing.

So the SDK owns its own vocabulary rather than re-exporting the internal
enum. The cost is a possible drift between two definitions, which is why
``test_sdk_status_vocabulary_matches_the_frozen_contract`` compares the
SDK's statuses against the frozen schema on disk instead of against the
internal class it happens to wrap today.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from remora import sdk

CONTRACT = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "schemas"
     / "postcondition_contract_v1.yaml").read_text(encoding="utf-8")
)


# ── The surface exists and is reachable without touching internals ─────────

def test_the_effect_surface_is_exported_from_remora_sdk() -> None:
    for name in ("EffectStatus", "EffectVerificationView", "PostconditionSpec",
                 "ToolSpecIdentity", "build_postcondition", "verify_effect"):
        assert hasattr(sdk, name), f"{name} missing from the SDK surface"
        assert name in sdk.__all__, f"{name} is reachable but not published"


def test_the_effect_surface_needs_no_internal_imports() -> None:
    """The whole verification path must work from ``remora.sdk`` alone.

    AAE is contractually forbidden from importing ``remora.governance``,
    ``remora.policy`` or ``remora.enforcement``; if this test needs one of
    them, so would the product.
    """
    spec = sdk.build_postcondition(
        tool_id="create_github_issue",
        target_selector={"repository": "acme/ops"},
        expected_fields={"title": "Valve drift", "state": "open"},
    )
    result = sdk.verify_effect(
        spec, {"title": "Valve drift", "state": "open", "updated_at": "now"},
        proposal_id="p-1", execution_id="e-1", toolspec_hash="d" * 64,
        verifier_identity="acme.reader/v1",
    )
    assert result.status is sdk.EffectStatus.VERIFIED
    assert isinstance(result, sdk.EffectVerificationView)


# ── The vocabulary matches the frozen contract, not just the internals ─────

def test_sdk_status_vocabulary_matches_the_frozen_contract() -> None:
    published = {entry["status"] for entry in CONTRACT["statuses"]}
    assert {s.value for s in sdk.EffectStatus} == published


def test_terminality_matches_the_frozen_contract() -> None:
    """UNOBSERVABLE and VERIFIER_FAILED mean "we do not know yet". A
    product that treated them as terminal would close incidents that are
    still open."""
    by_status = {e["status"]: e for e in CONTRACT["statuses"]}
    for status in sdk.EffectStatus:
        assert status.is_terminal is by_status[status.value]["terminal"]


# ── The distinctions survive the crossing ──────────────────────────────────

def test_an_unreadable_object_is_unobservable_not_a_mismatch() -> None:
    spec = sdk.build_postcondition(
        tool_id="create_github_issue", target_selector={"repository": "a/b"},
        expected_fields={"title": "x"},
    )
    result = sdk.verify_effect(
        spec, None, proposal_id="p-1", execution_id="e-1",
        toolspec_hash="d" * 64, verifier_identity="acme.reader/v1",
    )
    assert result.status is sdk.EffectStatus.UNOBSERVABLE
    assert result.status.is_terminal is False


def test_a_declared_field_that_differs_is_a_mismatch() -> None:
    spec = sdk.build_postcondition(
        tool_id="create_github_issue", target_selector={"repository": "a/b"},
        expected_fields={"title": "approved"},
    )
    result = sdk.verify_effect(
        spec, {"title": "something else"}, proposal_id="p-1",
        execution_id="e-1", toolspec_hash="d" * 64,
        verifier_identity="acme.reader/v1",
    )
    assert result.status is sdk.EffectStatus.MISMATCH
    assert result.reason_code == "postcondition_field_mismatch"


def test_undeclared_fields_are_out_of_scope() -> None:
    """Declared delta, never global unchangedness — the decision the
    architect review made binding."""
    spec = sdk.build_postcondition(
        tool_id="t", target_selector={}, expected_fields={"title": "x"},
    )
    result = sdk.verify_effect(
        spec, {"title": "x", "someone_elses_column": "changed"},
        proposal_id="p-1", execution_id="e-1", toolspec_hash="d" * 64,
        verifier_identity="acme.reader/v1",
    )
    assert result.status is sdk.EffectStatus.VERIFIED


def test_a_body_can_be_compared_by_hash_without_storing_it() -> None:
    spec = sdk.build_postcondition(
        tool_id="t", target_selector={},
        expected_fields={"body": sdk.content_digest("the approved text")},
        comparison_rules={"body": "hash"},
    )
    ok = sdk.verify_effect(
        spec, {"body": "the approved text"}, proposal_id="p-1",
        execution_id="e-1", toolspec_hash="d" * 64,
        verifier_identity="acme.reader/v1",
    )
    tampered = sdk.verify_effect(
        spec, {"body": "the approved text, plus admin access"},
        proposal_id="p-1", execution_id="e-1", toolspec_hash="d" * 64,
        verifier_identity="acme.reader/v1",
    )
    assert ok.status is sdk.EffectStatus.VERIFIED
    assert tampered.status is sdk.EffectStatus.MISMATCH
    assert "the approved text" not in str(dict(spec.expected_fields))


# ── The record is exportable and hashes both sides ─────────────────────────

def test_the_view_carries_both_hashes_and_serializes(sdk_result=None) -> None:
    spec = sdk.build_postcondition(
        tool_id="t", target_selector={}, expected_fields={"a": 1},
    )
    result = sdk.verify_effect(
        spec, {"a": 1}, proposal_id="p-1", execution_id="e-1",
        toolspec_hash="d" * 64, verifier_identity="acme.reader/v1",
    )
    payload = result.to_dict()
    assert len(payload["expected_sha256"]) == 64
    assert len(payload["observed_sha256"]) == 64
    assert payload["verifier_identity"] == "acme.reader/v1"
    assert payload["status"] == "EFFECT_VERIFIED"


# ── ToolSpec identity travels with the decision ────────────────────────────

def test_assessment_exposes_the_toolspec_that_authorized_it() -> None:
    result = sdk.AssessmentResult.from_payload({
        "proposal_id": "p-1", "decision": "accept", "reasons": [],
        "tool_call_hash": "h", "semantic": {}, "audit": {"sequence_no": 1, "entry_hash": "e" * 64},
        "toolspec": {"tool_id": "create_github_issue", "version": 3,
                     "hash": "a" * 64, "enforced": True},
    })
    assert result.toolspec == sdk.ToolSpecIdentity(
        tool_id="create_github_issue", version=3, hash="a" * 64, enforced=True,
    )


def test_an_unenforced_toolspec_is_visible_as_such() -> None:
    """A deployment running without signed specs must be able to SEE that
    from the response rather than infer it from an empty hash."""
    result = sdk.AssessmentResult.from_payload({
        "proposal_id": "p-1", "decision": "accept", "reasons": [],
        "tool_call_hash": "h", "semantic": {}, "audit": {"sequence_no": 1, "entry_hash": "e" * 64},
        "toolspec": {"tool_id": "t", "version": 0, "hash": "",
                     "enforced": False},
    })
    assert result.toolspec is not None
    assert result.toolspec.enforced is False


def test_a_response_without_a_toolspec_section_is_not_an_error() -> None:
    """Older servers omit it entirely; the client must stay usable."""
    result = sdk.AssessmentResult.from_payload({
        "proposal_id": "p-1", "decision": "accept", "reasons": [],
        "tool_call_hash": "h", "semantic": {}, "audit": {"sequence_no": 1, "entry_hash": "e" * 64},
    })
    assert result.toolspec is None


# ── The verdict is visible on the proposal ─────────────────────────────────

def test_a_proposal_view_carries_the_effect_verdict() -> None:
    view = sdk.ProposalView.from_payload({
        "proposal_id": "p-1", "decision": "verify", "current_state":
        "EFFECT_MISMATCH", "event_count": 5,
        "effect": {"status": "EFFECT_MISMATCH",
                   "reason_code": "postcondition_field_mismatch",
                   "verified_at": "2026-08-05T12:00:00+00:00",
                   "verifier_identity": "acme.reader/v1",
                   "expected_sha256": "a" * 64, "observed_sha256": "b" * 64,
                   "history": [{"status": "EFFECT_MISMATCH"}]},
    })
    assert view.effect is not None
    assert view.effect.status is sdk.EffectStatus.MISMATCH
    assert view.effect.reason_code == "postcondition_field_mismatch"


def test_a_proposal_with_no_verification_reports_none_not_verified() -> None:
    """The absence of a verdict must never read as a passing one."""
    view = sdk.ProposalView.from_payload({
        "proposal_id": "p-1", "decision": "accept",
        "current_state": "SUCCEEDED", "event_count": 3,
        "effect": {"status": None, "history": []},
    })
    assert view.effect is None
