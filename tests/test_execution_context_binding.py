# SPDX-License-Identifier: BUSL-1.1
"""Execution context continuity, freshness and historical evidence."""
from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher
from remora.enforcement.runtime_identity import (
    current_runtime_identity_hash, reset_runtime_identity,
)
from remora.governance.execution_identity import (
    ContextAuthority, ContextDataScope, ContextRuntime, ContextSubject,
    ExecutionContextRefused, ExecutionContextV1, ModelInitiator,
    historical_context, observation_binding,
)
from remora.policy.observation import PolicyObservation, canonical_tool_call_hash

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "ctx-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}
BUILD = "a" * 64


class Provider:
    def __init__(self) -> None:
        self.model_id = "model-A"
        self.build = BUILD
        self.classification = "internal"
        self.valid = True
        self.captures = 0

    def capture(self, *, proposal_id: str, tenant: str, principal: str,
                tool_call_hash: str) -> ExecutionContextV1:
        self.captures += 1
        return ExecutionContextV1(
            context_id=str(uuid4()), proposal_id=proposal_id, tenant_id=tenant,
            tool_call_hash=tool_call_hash, captured_at=datetime.now(UTC).isoformat(),
            subject=ContextSubject(principal, ContextAuthority(
                "deployment", "deployment-1", "authenticated-session-1")),
            model_initiator=ModelInitiator("provider-1", self.model_id, ContextAuthority(
                "inference_gateway", "gateway-1", "inference-event-1")),
            runtime=ContextRuntime(current_runtime_identity_hash(), self.build,
                                   ContextAuthority("deployment", "deployment-1", "build-1")),
            data_scope=ContextDataScope(
                self.classification, ("proposal_input", "declared_tool_access"),
                ContextAuthority("deployment_policy", "policy-1", "classification-1")),
        )

    def data_scope_valid(self, context: ExecutionContextV1) -> bool:
        return self.valid and context.data_scope.classification == self.classification

    def current_build_provenance_digest(self) -> str:
        return self.build


@pytest.fixture()
def provider(monkeypatch):
    monkeypatch.setenv("REMORA_RUNTIME_KIND", "test-worker")
    monkeypatch.setenv("REMORA_DEPLOYMENT_GENERATION", "generation-1")
    reset_runtime_identity()
    yield Provider()
    reset_runtime_identity()


def context_for(provider: Provider) -> ExecutionContextV1:
    return provider.capture(
        proposal_id=str(uuid4()), tenant="acme", principal="employee-1",
        tool_call_hash=canonical_tool_call_hash(
            name=CALL["tool_name"], arguments=CALL["arguments"],
            tenant="acme", target="prod"))


def test_canonical_context_roundtrip_and_observation_binding(provider):
    context = context_for(provider)
    canonical = context.canonical_bytes().decode()
    assert ExecutionContextV1.from_canonical(canonical) == context
    obs = PolicyObservation(
        question="test", tool_call_hash=context.tool_call_hash,
        proposal_id=context.proposal_id, execution_context_hash=context.digest())
    assert observation_binding(obs) != context.tool_call_hash
    assert observation_binding(dataclasses.replace(obs, execution_context_hash="")) == context.tool_call_hash
    changed = dataclasses.replace(context, model_initiator=dataclasses.replace(
        context.model_initiator, model_id="model-B"))
    assert changed.digest() != context.digest()
    assert observation_binding(dataclasses.replace(
        obs, execution_context_hash=changed.digest())) != observation_binding(obs)


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(metadata={"free": "text"}),
    lambda d: d["model_initiator"].update(provider=1.0),
    lambda d: d["model_initiator"]["authority"].update(kind="model_self_report"),
    lambda d: d["runtime"].update(build_provenance_digest="commit-not-a-digest"),
    lambda d: d["data_scope"].update(scope=["unknown_downstream_data"]),
    lambda d: d["data_scope"].update(ceiling="all_data"),
    lambda d: d["data_scope"].update(classification=False),
    lambda d: d.update(captured_at="2026-10-06T00:00:00"),
    lambda d: d["subject"].update(authority={}),
])
def test_context_rejects_untyped_extensions_and_overclaims(provider, mutation):
    raw = context_for(provider).to_dict()
    mutation(raw)
    with pytest.raises(ExecutionContextRefused):
        ExecutionContextV1.from_dict(raw)


def test_noncanonical_history_is_refused(provider):
    with pytest.raises(ExecutionContextRefused, match="noncanonical"):
        ExecutionContextV1.from_canonical(json.dumps(context_for(provider).to_dict()))


def test_persisted_canonical_context_survives_restart(provider, tmp_path):
    from remora.governance.tenant_chain import SQLiteTenantChain

    path = str(tmp_path / "context-chain.db")
    context = context_for(provider)
    chain = SQLiteTenantChain(path)
    chain.append("acme", {
        "event": "assessed", "proposal_id": context.proposal_id,
        "actor": "employee-1", "tool_call_hash": context.tool_call_hash,
        "execution_context_hash": context.digest(),
        "execution_context_canonical": context.canonical_bytes().decode(),
    })
    restored = SQLiteTenantChain(path)
    assert historical_context(restored, "acme", context.proposal_id) == context
    assert historical_context(restored, "another-tenant", context.proposal_id) is None
    assert restored.verify("acme")[0]


def make_dispatch(provider, monkeypatch):
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "context-test-lease")
    monkeypatch.setenv("REMORA_LEASE_ACCEPT_HMAC", "1")
    context = context_for(provider)
    lease = ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="employee-1",
        tool_name=CALL["tool_name"], arguments=CALL["arguments"],
        target_environment="prod", policy_bundle_hash="policy-1",
        issued_at=datetime.now(UTC).isoformat(), proposal_id=context.proposal_id,
        grant_jti=str(uuid4()), execution_context=context)
    dispatcher = GovernedToolDispatcher(
        "policy-1", require_execution_context=True,
        execution_context_provider=provider)
    effects = []
    dispatcher.register(CALL["tool_name"], lambda args: effects.append(args))

    def dispatch(ctx=context, authorization=lease):
        return dispatcher.dispatch(
            authorization, CALL["tool_name"], CALL["arguments"],
            tenant_id="acme", target_environment="prod",
            actor_identity="employee-1", execution_context=ctx)

    return context, lease, dispatch, effects


def test_dispatch_requires_same_context_and_preserves_nonce(provider, monkeypatch):
    context, lease, dispatch, effects = make_dispatch(provider, monkeypatch)
    changed = dataclasses.replace(context, context_id=str(uuid4()))
    assert dispatch(changed).refusal_reason == "execution_context_hash_mismatch"
    assert not effects
    assert dispatch(None).refusal_reason == "execution_context_missing"
    result = dispatch()
    assert result.executed and effects == [CALL["arguments"]]
    assert result.execution_context_hash == context.digest()
    assert result.execution_id == lease.grant_jti
    assert result.dispatch_check["result"] == "matched"
    assert dispatch().refusal_reason == "nonce_already_consumed"


def test_lease_context_is_signed(provider, monkeypatch):
    context, lease, dispatch, effects = make_dispatch(provider, monkeypatch)
    assert ExecutionLease.from_dict(lease.to_dict()) == lease
    forged = dataclasses.replace(lease, execution_context_hash="b" * 64)
    assert not dispatch(context, forged).executed
    assert not effects
    assert dispatch().executed


@pytest.mark.parametrize("change,reason", [
    ("runtime", "runtime_identity_mismatch"),
    ("build", "build_provenance_mismatch"),
    ("data", "execution_context_data_scope_invalid"),
])
def test_dispatch_freshness_comes_from_deployment(provider, monkeypatch, change, reason):
    context, lease, dispatch, effects = make_dispatch(provider, monkeypatch)
    if change == "runtime":
        monkeypatch.setenv("REMORA_DEPLOYMENT_GENERATION", "generation-2")
        reset_runtime_identity()
    elif change == "build":
        provider.build = "b" * 64
    else:
        provider.valid = False
    result = dispatch()
    assert result.refusal_reason == reason
    assert not effects
    assert result.dispatch_check["result"] == "refused"
    assert result.execution_context_hash == context.digest()


def test_initiator_model_is_historical_not_current_executor(provider, monkeypatch):
    _context, _lease, dispatch, _effects = make_dispatch(provider, monkeypatch)
    provider.model_id = "model-B"
    assert dispatch().executed


@pytest.fixture()
def client(provider, monkeypatch, tmp_path):
    from tests.test_effect_record_endpoint import _make_client
    import servers.execution_api as api

    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "research")
    monkeypatch.setenv("REMORA_REQUIRE_EXECUTION_CONTEXT", "1")
    monkeypatch.setenv("REMORA_LEASE_ACCEPT_HMAC", "1")
    monkeypatch.delenv("REMORA_ASYNC_DISPATCH", raising=False)
    client, _state = _make_client(monkeypatch, tmp_path)
    monkeypatch.setattr(api, "context_provider", lambda: provider)
    api._GATE = api.EnforcementGate(strict=True, audience=api.PEP_AUDIENCE)
    yield client
    api._reset_tool_dispatcher()


def assessed(client):
    response = client.post("/v1/execution/assess", json=CALL)
    assert response.status_code == 200, response.text
    return response.json()


def approved(client, body):
    response = client.post("/v1/execution/approve", json={"item_id": body["review_item_id"]})
    assert response.status_code == 200, response.text


def execute(client, body):
    return client.post("/v1/execution/execute", json={
        "item_id": body["review_item_id"], "tool_call": CALL})


def test_review_dispatch_effect_and_historical_export(client, provider):
    import servers.execution_api as api
    from tests.test_effect_record_endpoint import _post

    body = assessed(client)
    context = historical_context(api._CHAIN, "acme", body["proposal_id"], required=True)
    approved(client, body)
    provider.model_id = "model-B"
    result = execute(client, body)
    assert result.status_code == 200, result.text
    execution = result.json()["tool_execution"]
    assert execution["executed"], result.text
    assert execution["execution_context_hash"] == context.digest()
    assert provider.captures == 1
    # Different execution and context identities cannot occupy the receipt slot.
    response = _post(client, body["proposal_id"], execution_id="other-execution",
                     execution_context_hash=context.digest())
    assert response.status_code == 409
    response = _post(client, body["proposal_id"], execution_id=execution["execution_id"],
                     execution_context_hash="b" * 64)
    assert response.status_code == 409
    response = _post(client, body["proposal_id"], execution_id=execution["execution_id"],
                     execution_context_hash=context.digest())
    assert response.status_code == 200, response.text
    provider.classification = "restricted"
    exported = client.get(f"/v1/execution/proposals/{body['proposal_id']}/evidence")
    assert exported.status_code == 200, exported.text
    assert exported.json()["execution_context"]["canonical"] == context.canonical_bytes().decode()
    assert "model-A" in exported.json()["execution_context"]["canonical"]
    assert provider.captures == 1


def test_accept_context_is_bound_before_grant_consumption(client, monkeypatch):
    import servers.execution_api as api
    from remora.policy.report import DecisionAction

    decide = api._ENGINE.decide
    # This is a plumbing test; policy ACCEPT conditions are tested separately.
    monkeypatch.setattr(api._ENGINE, "decide", lambda obs: dataclasses.replace(
        decide(obs), action=DecisionAction.ACCEPT))
    body = assessed(client)
    original = historical_context(api._CHAIN, "acme", body["proposal_id"])
    record = api._CHAIN.entries("acme")[-1].payload
    altered = dataclasses.replace(original, model_initiator=dataclasses.replace(
        original.model_initiator, model_id="model-B"))
    record["execution_context_canonical"] = altered.canonical_bytes().decode()
    record["execution_context_hash"] = altered.digest()
    request = {"execution_token": body["execution_token"], "tool_call": CALL}
    refused = client.post("/v1/execution/execute-accepted", json=request)
    assert refused.status_code == 409, refused.text
    record["execution_context_canonical"] = original.canonical_bytes().decode()
    record["execution_context_hash"] = original.digest()
    response = client.post("/v1/execution/execute-accepted", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["tool_execution"]["executed"]


def test_review_rejects_context_substitution_between_identical_calls(client):
    import servers.execution_api as api

    first, second = assessed(client), assessed(client)
    first_context = historical_context(api._CHAIN, "acme", first["proposal_id"])
    second_context = historical_context(api._CHAIN, "acme", second["proposal_id"])
    approved(client, first)
    item = api._queue("acme").item(first["review_item_id"])
    item.observation = dataclasses.replace(
        item.observation, execution_context_hash=second_context.digest())
    refused = execute(client, first)
    assert refused.status_code == 200, refused.text
    assert refused.json()["outcome"] == "binding_refused"
    assert first_context.tool_call_hash == second_context.tool_call_hash


def test_missing_historical_bytes_refuses_without_reconstruction(client, provider):
    import servers.execution_api as api

    body = assessed(client)
    approved(client, body)
    api._CHAIN.entries("acme")[0].payload.pop("execution_context_canonical")
    refused = execute(client, body)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "execution_context_history_missing"
    assert provider.captures == 1


def test_async_worker_preserves_context_and_durable_projection(client, monkeypatch):
    import servers.execution_api as api
    from remora.execution.service import _result_record_from_projection

    monkeypatch.setenv("REMORA_ASYNC_DISPATCH", "1")
    body = assessed(client)
    approved(client, body)
    response = execute(client, body)
    assert response.status_code == 202, response.text
    results = api.dispatch_pending_intents("acme", worker_id="context-worker")
    execution = results[0]["tool_execution"]
    assert execution["executed"], execution
    row = api._outbox().rows_for_proposal("acme", body["proposal_id"])[0]
    restored = _result_record_from_projection(json.loads(row.projection_json))
    assert restored["execution_context_hash"] == execution["execution_context_hash"]
    assert restored["dispatch_check"]["result"] == "matched"
    assert restored["execution_id"] == execution["execution_id"]


def test_remote_hop_carries_only_signed_historical_context(provider, monkeypatch):
    from remora.execution import remote_dispatch
    from types import SimpleNamespace

    context, lease, _dispatch, _effects = make_dispatch(provider, monkeypatch)
    sent = []
    monkeypatch.setenv("REMORA_EXECUTION_ENDPOINT", "https://executor.invalid")
    monkeypatch.setattr(remote_dispatch, "_post", lambda url, payload, timeout: (
        sent.append(payload) or {"tool_execution": {
            "executed": True, "execution_context_hash": context.digest(),
            "execution_id": lease.grant_jti, "dispatch_check": {
                "result": "matched",
                "expected_runtime_identity_hash": lease.runtime_identity_hash,
                "observed_runtime_identity_hash": lease.runtime_identity_hash,
            }}}))
    remote_dispatch.remote_dispatch(
        lease=lease, tenant="acme", principal="employee-1",
        tool_call=SimpleNamespace(**CALL), execution_context=context)
    assert sent[0]["execution_context"] == context.to_dict()
    assert sent[0]["lease"]["execution_context_hash"] == context.digest()


def test_required_profile_refuses_absent_provider(client, monkeypatch):
    import servers.execution_api as api

    monkeypatch.setattr(api, "context_provider", lambda: None)
    response = client.post("/v1/execution/assess", json=CALL)
    assert response.status_code == 409, response.text
    assert not api._CHAIN.entries("acme")


def test_request_self_report_cannot_populate_context(client):
    import servers.execution_api as api

    response = client.post("/v1/execution/assess", json={
        **CALL, "model_id": "attacker-model", "data_class": "public",
        "execution_context_hash": "b" * 64})
    assert response.status_code == 200, response.text
    context = historical_context(api._CHAIN, "acme", response.json()["proposal_id"])
    assert context.model_initiator.model_id == "model-A"
    assert context.data_scope.classification == "internal"


def test_tool_failure_retains_context_and_dispatch_check(client, monkeypatch):
    import servers.execution_api as api

    def fail(arguments):
        raise RuntimeError("effect outcome unknown")

    body = assessed(client)
    approved(client, body)
    api._tool_dispatcher().register(CALL["tool_name"], fail)
    response = execute(client, body)
    assert response.status_code == 200, response.text
    execution = response.json()["tool_execution"]
    assert execution["state_unknown"] and execution["dispatch_began"]
    assert execution["dispatch_check"]["result"] == "matched"
    record = api._CHAIN.entries("acme")[-1].payload
    assert record["state_unknown"]
    assert record["execution_context_hash"] == execution["execution_context_hash"]


def test_sdk_context_bound_effect_roundtrip(client):
    from remora.sdk import RemoraClient, build_postcondition, verify_effect

    sdk = RemoraClient("http://test", token="test", http_client=client)
    body = assessed(client)
    approved(client, body)
    response = execute(client, body)
    execution = response.json()["tool_execution"]
    spec = build_postcondition(
        tool_id=CALL["tool_name"], target_selector={},
        expected_fields={"artifact_id": "ctx-1"})
    verification = verify_effect(
        spec, {"artifact_id": "ctx-1"}, proposal_id=body["proposal_id"],
        execution_id=execution["execution_id"], toolspec_hash="",
        verifier_identity="acme.reader/v1",
        execution_context_hash=execution["execution_context_hash"])
    recorded = sdk.record_effect(body["proposal_id"], verification)
    assert recorded.execution_context_hash == execution["execution_context_hash"]
    assert sdk.get_proposal(body["proposal_id"]).current_state == "EFFECT_VERIFIED"


def test_remote_endpoint_checks_context_digest_and_runtime(client, provider, monkeypatch):
    context, lease, _dispatch, _effects = make_dispatch(provider, monkeypatch)
    request = {
        "lease": lease.to_dict(), "tool_call": CALL, "tenant_id": "acme",
        "execution_context": context.to_dict(),
    }
    changed = context.to_dict()
    changed["model_initiator"]["model_id"] = "model-B"
    import servers.execution_api as api
    lease = ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="employee-1",
        tool_name=CALL["tool_name"], arguments=CALL["arguments"],
        target_environment="prod", policy_bundle_hash=api._current_policy_bundle_hash(),
        issued_at=datetime.now(UTC).isoformat(), proposal_id=context.proposal_id,
        grant_jti=str(uuid4()), execution_context=context)
    request["lease"] = lease.to_dict()
    refused = client.post("/v1/execution/dispatch-leased", json={
        **request, "execution_context": changed})
    assert refused.status_code == 200, refused.text
    assert refused.json()["tool_execution"]["refusal_reason"] == "execution_context_hash_mismatch"
    response = client.post("/v1/execution/dispatch-leased", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["tool_execution"]["executed"], response.text


def test_async_missing_context_history_settles_refused(client, monkeypatch):
    import servers.execution_api as api

    monkeypatch.setenv("REMORA_ASYNC_DISPATCH", "1")
    body = assessed(client)
    approved(client, body)
    assert execute(client, body).status_code == 202
    api._CHAIN.entries("acme")[0].payload.pop("execution_context_canonical")
    result = api.dispatch_pending_intents("acme", worker_id="context-worker")[0]
    assert result["tool_execution"]["refusal_reason"] == "execution_context_history_missing"
    row = api._outbox().rows_for_proposal("acme", body["proposal_id"])[0]
    assert row.state.value == "REFUSED"


def test_deployment_provider_configuration_is_fail_closed(monkeypatch):
    from servers.execution_identity import context_provider, context_required

    monkeypatch.setenv("REMORA_REQUIRE_EXECUTION_CONTEXT", "typo")
    with pytest.raises(ExecutionContextRefused, match="requirement_invalid"):
        context_required()
    monkeypatch.setenv("REMORA_REQUIRE_EXECUTION_CONTEXT", "1")
    monkeypatch.delenv("REMORA_EXECUTION_CONTEXT_MODULE", raising=False)
    with pytest.raises(ExecutionContextRefused, match="provider_missing"):
        context_provider()
    monkeypatch.setenv("REMORA_EXECUTION_CONTEXT_MODULE", "no_such_context_module")
    with pytest.raises(ExecutionContextRefused, match="provider_unavailable"):
        context_provider()


def test_legacy_observation_hash_is_unchanged_and_does_not_mutate_input():
    import hashlib
    from remora.enforcement.token import _hash_observation

    obs = PolicyObservation(question="legacy observation")
    old_fields = dataclasses.asdict(obs)
    old_fields.pop("execution_context_hash")
    expected = hashlib.sha256(json.dumps(
        old_fields, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    raw = dataclasses.asdict(obs)
    assert _hash_observation(obs) == _hash_observation(raw) == expected
    assert raw["execution_context_hash"] == ""


def test_review_context_hash_survives_persistence_serialization(client):
    import servers.execution_api as api
    from remora.persistence.execution_state import from_dict, to_dict

    body = assessed(client)
    approved(client, body)
    item = api._queue("acme").item(body["review_item_id"])
    restored = from_dict(json.loads(json.dumps(to_dict(item))), type(item))
    assert restored.observation.execution_context_hash == item.observation.execution_context_hash
    assert restored.approval == item.approval


def test_historical_context_join_refuses_a_different_execution_context(client):
    import servers.execution_api as api

    body = assessed(client)
    approved(client, body)
    assert execute(client, body).json()["tool_execution"]["executed"]
    result = api._CHAIN.entries("acme")[-1].payload
    result["execution_context_hash"] = "b" * 64
    response = client.get(f"/v1/execution/proposals/{body['proposal_id']}/evidence")
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "execution_context_history_join_mismatch"


def test_context_binding_is_not_a_replacement_for_deployment_checks(provider, monkeypatch):
    context, lease, _dispatch, effects = make_dispatch(provider, monkeypatch)
    dispatcher = GovernedToolDispatcher("policy-1", require_execution_context=True)
    dispatcher.register(CALL["tool_name"], lambda args: effects.append(args))
    result = dispatcher.dispatch(
        lease, CALL["tool_name"], CALL["arguments"], tenant_id="acme",
        target_environment="prod", actor_identity="employee-1",
        execution_context=context)
    assert result.refusal_reason == "execution_context_provider_missing"
    assert not effects


def test_required_dispatch_cannot_drop_context_binding(provider, monkeypatch):
    context, _lease, _dispatch, effects = make_dispatch(provider, monkeypatch)
    lease = ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="employee-1",
        tool_name=CALL["tool_name"], arguments=CALL["arguments"],
        target_environment="prod", policy_bundle_hash="policy-1",
        issued_at=datetime.now(UTC).isoformat(), proposal_id=context.proposal_id)
    dispatcher = GovernedToolDispatcher(
        "policy-1", require_execution_context=True, execution_context_provider=provider)
    dispatcher.register(CALL["tool_name"], lambda args: effects.append(args))
    result = dispatcher.dispatch(
        lease, CALL["tool_name"], CALL["arguments"], tenant_id="acme",
        target_environment="prod", actor_identity="employee-1")
    assert result.refusal_reason == "execution_context_missing"
    assert not effects


def test_remote_missing_context_evidence_is_unknown_not_success(client, monkeypatch):
    from remora.execution import remote_dispatch
    from tests.test_effect_record_endpoint import _post

    body = assessed(client)
    approved(client, body)
    monkeypatch.setenv("REMORA_EXECUTION_ENDPOINT", "https://executor.invalid")
    monkeypatch.setattr(remote_dispatch, "_post",
                        lambda url, payload, timeout: {"tool_execution": {"executed": True}})
    response = execute(client, body)
    execution = response.json()["tool_execution"]
    assert not execution["executed"] and execution["state_unknown"]
    assert execution["refusal_reason"] == "execution_domain_unreachable"
    assert execution["execution_context_hash"]
    # A later verifier can still resolve the real effect; no dispatch check
    # is fabricated when the remote evidence was unusable.
    assert "dispatch_check" not in execution
    receipt = _post(client, body["proposal_id"], execution_id=execution["execution_id"],
                    execution_context_hash=execution["execution_context_hash"])
    assert receipt.status_code == 200, receipt.text
