# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The async worker decides again what can change after the 202.

Companion to tests/test_pre_federation_async_authority_adversarial.py, which
proves the two defects. This suite pins the fix from both sides: the refusals
spend nothing and say why, the fail-closed edges hold, and a legitimate
pending intent with an unchanged spec and a clean observation still runs.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.enforcement.outbox import OutboxState  # noqa: E402
from remora.toolcall.toolspec import sign_bundle  # noqa: E402

KEY = "async-regate-toolspec-key"
IDENTITY = "async-regate-signer-v1"

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "async-regate-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


def _spec(version: int, allowed_targets: list[str] | None = None) -> dict:
    return {
        "tool_id": "store_artifact",
        "version": version,
        "callable_digest": "sha256:" + ("a" if version == 1 else "b") * 64,
        "implementation_identity": f"regate-runtime-v{version}",
        "description": "Persist an artifact.",
        "argument_schema": {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string"},
                "content": {"type": "object"},
            },
            "required": ["artifact_id"],
            "additionalProperties": False,
        },
        "risk_tier": "medium",
        "action_type": "write",
        "domain": "general",
        "capabilities": ["artifact_management"],
        "semantic_contract": {
            "capability": "artifact_management",
            "effect": "create",
            "resource_type": "artifact",
            "mutation": True,
            "argument_roles": {"artifact_id": "target_resource"},
        },
        "credential_scope": ["artifacts:write"],
        "allowed_targets": allowed_targets or ["prod"],
        "idempotency_contract": {
            "safe_to_retry": True,
            "key_derivation": "canonical_args",
        },
        "postcondition_reader": None,
        "compensation_tool": None,
        "timeout_policy": {"dispatch_timeout_seconds": 10},
        "network_policy": {"egress": "none"},
        "signing_identity": IDENTITY,
    }


def _bundle(tmp_path, name: str, spec: dict):
    raw = sign_bundle(
        {"schema_version": 1, "tool_specs": [spec]},
        key=KEY,
        signing_identity=IDENTITY,
        signed_at="2026-10-06T00:00:00Z",
    )
    path = tmp_path / name
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def _exec_mod():
    import servers.execution_api as exec_mod

    return exec_mod


def _use_bundle(monkeypatch, path) -> None:
    exec_mod = _exec_mod()
    if path is None:
        monkeypatch.delenv("REMORA_TOOLSPEC_BUNDLE", raising=False)
    else:
        monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE", str(path))
    exec_mod._reset_toolspec_bundle()
    exec_mod._reset_tool_dispatcher()


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "async-regate-pdp")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "async-regate-lease")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_ASYNC_DISPATCH", "1")
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE",
                       str(_bundle(tmp_path, "bundle-v1.json", _spec(1))))
    monkeypatch.setenv("REMORA_TOOLSPEC_SIGNING_KEY", KEY)
    monkeypatch.setenv("REMORA_TOOLSPEC_TRUSTED_IDENTITIES", IDENTITY)
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)

    import servers.api as api_mod
    from remora.governance.tenant_chain import TenantAuditChain

    exec_mod = _exec_mod()
    monkeypatch.setattr(api_mod, "_authenticate",
                        lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role",
                        lambda **kwargs: None)

    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    exec_mod._reset_toolspec_bundle()
    return TestClient(api_mod.app)


def _pending(client) -> tuple[str, str]:
    assessed = client.post("/v1/execution/assess", json=CALL)
    assert assessed.status_code == 200, assessed.text
    item = assessed.json()["review_item_id"]
    assert client.post(
        "/v1/execution/approve", json={"item_id": item}).status_code == 200
    pending = client.post(
        "/v1/execution/execute", json={"item_id": item, "tool_call": CALL})
    assert pending.status_code == 202, pending.text
    return item, pending.json()["proposal_id"]


def _events(event: str) -> list[dict]:
    return [e.payload for e in _exec_mod()._CHAIN.entries("acme")
            if e.payload.get("event") == event]


def _assert_refused_and_unspent(item: str, proposal_id: str,
                                reason: str) -> dict:
    """Refused before anything was minted: no grant, no authorization
    event, the row settled REFUSED and the item terminal."""
    exec_mod = _exec_mod()
    results = exec_mod.dispatch_pending_intents("acme", worker_id="w-1")
    assert len(results) == 1
    te = results[0]["tool_execution"]
    assert te["executed"] is False
    assert te["dispatch_began"] is False
    assert te["refusal_reason"] == reason
    assert _events("execution_authorized") == [], (
        "a grant was minted and PEP-consumed for a refused dispatch")
    [record] = _events("execution_result")
    assert record["grant_jti"] == ""
    assert record["tool_refusal_reason"] == reason
    row = exec_mod._outbox().rows_for_proposal("acme", proposal_id)[0]
    assert row.state is OutboxState.REFUSED
    status = exec_mod._queue("acme").item(item).status.value
    assert status != "authorized", "a refused dispatch left the item AUTHORIZED"
    # The settled row is never picked up again.
    assert exec_mod.dispatch_pending_intents("acme", worker_id="w-2") == []
    return record


def test_unchanged_spec_and_clean_observation_still_execute(client) -> None:
    """The fix must not turn the async path into a refusal machine: the spec
    the chain recorded is the spec in force, the fresh decision is no
    stricter, and the worker dispatches under the same hash."""
    _item, proposal_id = _pending(client)
    results = _exec_mod().dispatch_pending_intents("acme", worker_id="w-1")
    assert len(results) == 1
    te = results[0]["tool_execution"]
    assert te["executed"] is True, te
    [assessed] = _events("assessed")
    assert assessed["toolspec_hash"]
    [authorized] = _events("execution_authorized")
    assert authorized["grant_jti"] and authorized["pep_allowed"] is True
    row = _exec_mod()._outbox().rows_for_proposal("acme", proposal_id)[0]
    assert row.state is OutboxState.SUCCEEDED


def test_spec_drift_refuses_and_records_both_hashes(
        client, monkeypatch, tmp_path) -> None:
    item, proposal_id = _pending(client)
    [assessed] = _events("assessed")
    _use_bundle(monkeypatch, _bundle(tmp_path, "bundle-v2.json", _spec(2)))
    record = _assert_refused_and_unspent(
        item, proposal_id,
        "toolspec_changed_between_authorization_and_dispatch")
    detail = record["refusal_detail"]
    assert detail["authorized_toolspec_hash"] == assessed["toolspec_hash"]
    assert detail["current_toolspec_hash"] not in (
        "", assessed["toolspec_hash"])
    assert detail["current_toolspec_version"] == 2


def test_spec_the_bundle_refuses_at_dispatch_settles_under_its_code(
        client, monkeypatch, tmp_path) -> None:
    """A bundle that now refuses the call outright must settle the row, not
    escape the worker loop as an HTTP 409."""
    item, proposal_id = _pending(client)
    _use_bundle(monkeypatch, _bundle(
        tmp_path, "bundle-v2-staging.json", _spec(2, ["staging"])))
    _assert_refused_and_unspent(item, proposal_id,
                                "toolspec_target_not_allowed")


def test_removing_the_bundle_after_authorization_refuses(
        client, monkeypatch) -> None:
    """Authorized under a signed spec, dispatched under none: the spec that
    was checked is no longer the one in force."""
    item, proposal_id = _pending(client)
    _use_bundle(monkeypatch, None)
    _assert_refused_and_unspent(
        item, proposal_id,
        "toolspec_changed_between_authorization_and_dispatch")


def test_an_item_without_a_recorded_hash_fails_closed_under_a_bundle(
        client, monkeypatch, tmp_path) -> None:
    """Assessed and authorized with no bundle, so the chain records no hash;
    a bundle enforced at dispatch cannot be matched against nothing. The
    same branch covers an item whose assessed record is missing."""
    bundle = _bundle(tmp_path, "bundle-v1-late.json", _spec(1))
    _use_bundle(monkeypatch, None)
    item, proposal_id = _pending(client)
    [assessed] = _events("assessed")
    assert assessed["toolspec_hash"] == ""
    _use_bundle(monkeypatch, bundle)
    _assert_refused_and_unspent(
        item, proposal_id,
        "toolspec_changed_between_authorization_and_dispatch")


def test_no_bundle_then_and_now_is_the_unenforced_research_path(
        client, monkeypatch) -> None:
    _use_bundle(monkeypatch, None)
    _item, _proposal = _pending(client)
    results = _exec_mod().dispatch_pending_intents("acme", worker_id="w-1")
    assert results[0]["tool_execution"]["executed"] is True


def test_a_fresh_hard_guard_refuses_before_any_grant(
        client, monkeypatch) -> None:
    item, proposal_id = _pending(client)
    exec_mod = _exec_mod()
    real_builder = exec_mod._observation_with_context

    def now_adversarial(tool_call, tenant):
        obs, semantic = real_builder(tool_call, tenant)
        return dataclasses.replace(obs, adversarial_detected=True), semantic

    monkeypatch.setattr(exec_mod, "_observation_with_context", now_adversarial)
    record = _assert_refused_and_unspent(item, proposal_id,
                                         "fresh_regate_refused")
    detail = record["refusal_detail"]
    assert detail["regate_decision"] == "approval_invalidated"
    assert detail["fresh_action"] not in ("accept", "verify")


def test_regate_authorized_is_read_only_and_requires_authorization() -> None:
    """The queue method decides and records nothing: racing workers must not
    leave two log entries for one decision, and the caller settles."""
    from datetime import timedelta

    from remora.governance.review_queue import ExecutionDecision, ReviewQueue
    from remora.policy.decision_engine import RemoraDecisionEngine
    from remora.policy.observation import PolicyObservation
    from remora.policy.report import DecisionAction

    obs = PolicyObservation(question="q", tool_call_hash="h1",
                            risk_tier="medium", action_type="write")
    queue = ReviewQueue(engine=RemoraDecisionEngine(), tenant_id="acme")
    item = queue.enqueue(obs, DecisionAction.ESCALATE)
    with pytest.raises(ValueError):
        queue.regate_authorized(item.item_id, obs)
    queue.approve(item.item_id, "reviewer", timedelta(minutes=5))
    assert queue.execute(
        item.item_id, obs).decision is ExecutionDecision.EXECUTE
    assert queue.item(item.item_id).status.value == "authorized"
    before = len(queue.events)
    mutated = dataclasses.replace(obs, tool_call_hash="h2")
    assert queue.regate_authorized(
        item.item_id, mutated).decision is ExecutionDecision.BINDING_REFUSED
    hostile = dataclasses.replace(obs, adversarial_detected=True)
    outcome = queue.regate_authorized(item.item_id, hostile)
    assert outcome.decision is ExecutionDecision.APPROVAL_INVALIDATED
    assert len(queue.events) == before
    assert queue.item(item.item_id).status.value == "authorized"
