# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The envelope reaches the effect, and never past what was recorded (#37).

The DecisionEnvelope is the canonical governance contract, but the execution
path never built one: it appended lifecycle records and left ``EffectBlock`` at
its defaults, so the contract described assessments while the chain described
executions and nothing joined them.

The binding is a projection rather than a second store, and these tests pin
both halves of that choice. It must reach the effect — executed, outcome,
ledger anchor, verifier — and it must not exceed the records: an unassessed
field stays empty rather than being guessed, because an envelope that invented
a risk tier would be worse evidence than one that admits it has none.
"""
from __future__ import annotations

import pytest

from remora.execution.projections import envelope_projection


def _event(seq: int, name: str, payload: dict) -> dict:
    return {
        "sequence_no": seq,
        "entry_hash": f"hash-{seq}",
        "event": name,
        "actor": payload.get("actor"),
        "payload": {"event": name, **payload},
    }


ASSESSED = _event(0, "assessed", {
    "proposal_id": "p-1",
    "actor": "employee-1",
    "tool_name": "update_work_order",
    "tool_call_hash": "tch-1",
    "target_environment": "prod",
    "risk_tier": "high",
    "action_type": "production_write",
    "decision": "verify",
    "reasons": ["production_write_verify"],
    "policy_version": "v4",
    "tool_contract_bundle_hash": "bundle-1",
})
AUTHORIZED = _event(2, "execution_authorized", {
    "proposal_id": "p-1", "grant_jti": "jti-1", "pep_allowed": True,
})
RESULT = _event(3, "execution_result", {
    "proposal_id": "p-1", "executed": True, "tool_call_hash": "tch-1",
})
DISPATCH = {
    "outbox_id": "ob-1", "state": "SUCCEEDED", "attempt_no": 1,
    "worker_id": "w-1", "detail": "", "terminal": True,
}


def _project(events, dispatch=None):
    return envelope_projection(
        events, dispatch, proposal_id="p-1", tenant="acme",
    )


def test_the_envelope_reaches_the_effect() -> None:
    envelope = _project([ASSESSED, AUTHORIZED, RESULT], DISPATCH)
    assert envelope.effect.executed is True
    assert envelope.effect.tool_call_hash == "tch-1"
    assert envelope.effect.ledger_entry["grant_jti"] == "jti-1"
    assert envelope.effect.ledger_entry["outbox_id"] == "ob-1"
    assert envelope.effect.ledger_entry["entry_hash"] == "hash-3"


def test_the_decision_and_its_reasons_come_from_the_record() -> None:
    envelope = _project([ASSESSED])
    assert envelope.gate.outcome == "verify"
    assert envelope.assessment.policy_triggers == ["production_write_verify"]
    assert envelope.request.risk_tier == "high"
    assert envelope.request.proposed_action == "update_work_order"
    assert envelope.audit.policy_version == "v4"
    assert envelope.audit.tool_contract_bundle_hash == "bundle-1"


def test_an_unexecuted_proposal_says_so_rather_than_defaulting_to_true() -> None:
    envelope = _project([ASSESSED])
    assert envelope.effect.executed is False
    assert envelope.effect.effect_outcome  # a state, never None


def test_a_dispatch_that_did_not_succeed_is_not_reported_as_executed() -> None:
    failed = {**DISPATCH, "state": "FAILED"}
    envelope = _project([ASSESSED, AUTHORIZED], failed)
    assert envelope.effect.executed is False


def test_a_verified_effect_outranks_the_dispatch_verdict() -> None:
    """"The dispatcher returned" and "the change is present" differ."""
    verified = _event(4, "effect_verified", {
        "proposal_id": "p-1",
        "status": "EFFECT_VERIFIED",
        "reason_code": "MATCH",
        "verified_at": "2026-08-20T12:00:00+00:00",
        "verifier_identity": "cmms-reader",
        "expected_sha256": "e", "observed_sha256": "e",
    })
    envelope = _project([ASSESSED, AUTHORIZED, RESULT, verified], DISPATCH)
    assert envelope.effect.effect_outcome == "EFFECT_VERIFIED"
    assert envelope.effect.ledger_entry["effect_verifier_identity"] == "cmms-reader"


def test_a_mismatch_is_carried_not_smoothed() -> None:
    mismatch = _event(4, "effect_verified", {
        "proposal_id": "p-1",
        "status": "EFFECT_MISMATCH",
        "reason_code": "VALUE_DIFFERS",
        "verified_at": "2026-08-20T12:00:00+00:00",
        "verifier_identity": "cmms-reader",
        "expected_sha256": "e", "observed_sha256": "o",
    })
    envelope = _project([ASSESSED, AUTHORIZED, RESULT, mismatch], DISPATCH)
    assert envelope.effect.effect_outcome == "EFFECT_MISMATCH"
    assert envelope.effect.executed is True, (
        "a mismatch does not mean nothing was dispatched — the two facts are "
        "separate and both belong in the envelope"
    )


def test_nothing_is_invented_for_a_field_with_no_record() -> None:
    """The half that keeps this honest."""
    bare = _event(0, "assessed", {"proposal_id": "p-1"})
    envelope = _project([bare])
    assert envelope.request.risk_tier == ""
    assert envelope.request.action_type == ""
    assert envelope.gate.outcome == ""
    assert envelope.audit.tool_contract_bundle_hash is None
    assert envelope.assessment.oracle_votes == []


def test_the_execution_surface_claims_no_oracle_assessment() -> None:
    """Empty is the honest value: /v1/execution runs no oracle swarm."""
    envelope = _project([ASSESSED, AUTHORIZED, RESULT], DISPATCH)
    assert envelope.assessment.oracle_votes == []
    assert envelope.assessment.thermodynamic == {}
    assert envelope.assessment.evidence_quality == {}


def test_the_envelope_serialises() -> None:
    envelope = _project([ASSESSED, AUTHORIZED, RESULT], DISPATCH)
    body = envelope.to_dict()
    assert body["effect"]["executed"] is True
    assert body["request"]["request_id"] == "p-1"


def test_the_effect_block_docstring_no_longer_claims_it_is_unpopulated() -> None:
    """The block documented itself as RESERVED with no producer. There is one
    now, and a docstring that says otherwise is a false claim in the contract."""
    from remora.governance.envelope import EffectBlock

    doc = EffectBlock.__doc__ or ""
    assert "RESERVED" not in doc
    assert "envelope_projection" in doc


# ── through the API ──────────────────────────────────────────────────────────

@pytest.fixture()
def api(monkeypatch):
    from fastapi.testclient import TestClient

    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "exec-api-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role", lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE)
    exec_mod._reset_tool_dispatcher()
    return TestClient(api_mod.app)


PROD_WRITE = {
    "tool_name": "update_work_order",
    "arguments": {"order": "WO-1", "action": "reschedule"},
    "risk_tier": "high",
    "action_type": "production_write",
    "target_environment": "prod",
    "phase": "ordered",
    "trust_score": 0.86,
    "evidence_action": "verify",
    "evidence_confidence": 0.8,
    "schema_valid": True,
    "rollback_available": True,
}


def test_the_endpoint_returns_one_envelope_for_the_whole_lifecycle(api) -> None:
    assessed = api.post("/v1/execution/assess", json=PROD_WRITE).json()
    pid = assessed["proposal_id"]
    item_id = assessed["review_item_id"]
    api.post("/v1/execution/approve",
             json={"item_id": item_id, "approval_ttl_seconds": 900})
    api.post("/v1/execution/execute",
             json={"item_id": item_id, "tool_call": PROD_WRITE})

    body = api.get(f"/v1/execution/proposals/{pid}/envelope").json()

    assert body["request"]["request_id"] == pid
    assert body["gate"]["outcome"] == "verify"
    assert body["audit"]["tenant_id"] == "acme"
    assert body["effect"]["effect_outcome"], "the envelope must reach a state"
    assert body["effect"]["ledger_entry"].get("grant_jti")


def test_an_unknown_proposal_is_a_404_not_an_empty_envelope(api) -> None:
    """An envelope for a proposal that does not exist would be a fabricated
    record with a real-looking shape."""
    assert api.get("/v1/execution/proposals/does-not-exist/envelope").status_code == 404
