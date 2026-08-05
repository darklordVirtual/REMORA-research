# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""FT-13 slice 1: the stable third-party model surface of ``remora.sdk``.

The SDK models are the public wire contract for external integrators:
immutable, serialisable, and bound 1:1 to the ``/v1/execution/*`` REST
contract. ``DecisionAction`` must be the canonical enum object, never a
parallel vocabulary.
"""
from __future__ import annotations

import dataclasses

import pytest


def test_public_surface_imports() -> None:
    from remora.sdk import (  # noqa: F401
        AssessmentResult,
        DecisionAction,
        RemoraClient,
        RemoraError,
        ToolCall,
    )


def test_decision_action_is_the_canonical_enum() -> None:
    from remora.policy.report import DecisionAction as canonical
    from remora.sdk import DecisionAction

    assert DecisionAction is canonical
    assert {a.value for a in DecisionAction} == {
        "accept", "verify", "abstain", "escalate",
    }


def test_tool_call_is_frozen() -> None:
    from remora.sdk import ToolCall

    call = ToolCall(tool_name="read_telemetry", arguments={"asset": "P-1"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        call.tool_name = "other"  # type: ignore[misc]


def test_tool_call_payload_omits_unset_optionals() -> None:
    from remora.sdk import ToolCall

    call = ToolCall(tool_name="read_telemetry", arguments={"asset": "P-1"})
    payload = call.to_payload()
    assert payload == {
        "tool_name": "read_telemetry",
        "arguments": {"asset": "P-1"},
        "target_environment": "prod",
    }


def test_tool_call_payload_carries_set_optionals() -> None:
    from remora.sdk import ToolCall

    call = ToolCall(
        tool_name="set_valve_position",
        arguments={"valve": "V-18", "position_pct": 35},
        target_environment="production",
        intent_ref="WO-1204",
        idempotency_key="k-1",
        schema_valid=True,
        rollback_available=False,
    )
    payload = call.to_payload()
    assert payload["target_environment"] == "production"
    assert payload["intent_ref"] == "WO-1204"
    assert payload["idempotency_key"] == "k-1"
    assert payload["schema_valid"] is True
    assert payload["rollback_available"] is False
    assert "untrusted_context" not in payload


ACCEPT_PAYLOAD = {
    "proposal_id": "p-1",
    "decision": "accept",
    "reasons": ["low_risk_read"],
    "tool_call_hash": "a" * 64,
    "semantic": {
        "tool_contract_bundle_hash": "b" * 64,
        "state_hash": "c" * 64,
        "intent_authority_hash": "",
        "tool_matches_goal": True,
        "expected_effect_matches": None,
    },
    "execution_token": {"jti": "j-1", "action": "accept"},
    "audit": {"sequence_no": 0, "entry_hash": "d" * 64},
}


def test_assessment_result_from_accept_payload() -> None:
    from remora.sdk import AssessmentResult, DecisionAction

    result = AssessmentResult.from_payload(ACCEPT_PAYLOAD)
    assert result.proposal_id == "p-1"
    assert result.action is DecisionAction.ACCEPT
    assert result.reasons == ("low_risk_read",)
    assert result.tool_call_hash == "a" * 64
    assert result.semantic.tool_matches_goal is True
    assert result.semantic.expected_effect_matches is None
    assert result.execution_token == {"jti": "j-1", "action": "accept"}
    # Conditional keys are absent on the wire, None on the model.
    assert result.review_item_id is None
    assert result.audit.sequence_no == 0
    assert result.raw == ACCEPT_PAYLOAD


def test_assessment_result_from_verify_payload() -> None:
    from remora.sdk import AssessmentResult, DecisionAction

    payload = {
        "proposal_id": "p-2",
        "decision": "verify",
        "reasons": ["production_write", "no_rollback"],
        "tool_call_hash": "e" * 64,
        "semantic": {
            "tool_contract_bundle_hash": "",
            "state_hash": "",
            "intent_authority_hash": "",
            "tool_matches_goal": None,
            "expected_effect_matches": None,
        },
        "review_item_id": "item-7",
        "audit": {"sequence_no": 3, "entry_hash": "f" * 64},
    }
    result = AssessmentResult.from_payload(payload)
    assert result.action is DecisionAction.VERIFY
    assert result.review_item_id == "item-7"
    assert result.execution_token is None
    assert result.reasons == ("production_write", "no_rollback")


def test_assessment_result_is_frozen() -> None:
    from remora.sdk import AssessmentResult

    result = AssessmentResult.from_payload(ACCEPT_PAYLOAD)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.proposal_id = "tampered"  # type: ignore[misc]


def test_error_hierarchy_contract() -> None:
    from remora.sdk import (
        AuthenticationError,
        AuthorizationError,
        ConflictError,
        InvalidRequestError,
        NotFoundError,
        RateLimitedError,
        RemoraError,
        RemoraUnavailableError,
        ServerError,
    )

    for exc_type in (
        AuthenticationError, AuthorizationError, ConflictError,
        InvalidRequestError, NotFoundError, RateLimitedError,
        RemoraUnavailableError, ServerError,
    ):
        assert issubclass(exc_type, RemoraError)

    err = ServerError("boom", request_id="c0ffee00")
    assert err.code == "server_error"
    assert err.request_id == "c0ffee00"
    assert err.retryable is False

    rate = RateLimitedError("slow down", retry_after=60.0)
    assert rate.retryable is True
    assert rate.retry_after == 60.0

    down = RemoraUnavailableError("connect failed")
    assert down.retryable is True
    assert down.request_id is None


def test_derivation_proposal_payload_and_tool_call_threading() -> None:
    from remora.sdk import DerivationProposal, ToolCall

    receipt = DerivationProposal(
        argument="artifact_id", value="WIRED-1",
        transform="uppercase", source_span="wired-1",
    )
    assert receipt.to_payload() == {
        "argument": "artifact_id", "value": "WIRED-1",
        "transform": "uppercase", "source_span": "wired-1",
    }
    call = ToolCall(
        tool_name="store_artifact", arguments={"artifact_id": "WIRED-1"},
        derivations=(receipt,),
    )
    payload = call.to_payload()
    assert payload["derivations"] == [receipt.to_payload()]


def test_tool_call_without_derivations_omits_the_key() -> None:
    from remora.sdk import ToolCall

    payload = ToolCall(tool_name="t", arguments={}).to_payload()
    assert "derivations" not in payload


def test_derivation_proposal_params_ride_when_set() -> None:
    from remora.sdk import DerivationProposal

    receipt = DerivationProposal(
        argument="length_m", value=5000, transform="unit_convert",
        source_span="5 km", params={"from_unit": "km", "to_unit": "m"},
    )
    assert receipt.to_payload()["params"] == {"from_unit": "km", "to_unit": "m"}
