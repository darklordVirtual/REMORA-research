# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REMORA computes the effect verdict from a signed receipt (CAPR-07, CAPR-08).

``POST /v1/execution/proposals/{id}/effect-receipt`` takes a receipt signed
under ``REMORA/EFFECT-RECEIPT/v1`` and the approved call's arguments. The
server checks the signature against the verifier key registry, checks the
arguments against the dispatched call hash, instantiates the contract from
the signed ToolSpec v5 ``postcondition`` block, runs ``verify_declared_delta``
itself, and derives the vantage from the key record.

Each test below is a row of SDD §4.4
(``docs/design/compositional-authority-preservation-v1.md``) and names the
link that failed if it does not hold.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("cryptography")

from fastapi.testclient import TestClient  # noqa: E402

from remora.crypto import SignatureDomain, SigningKey, sign  # noqa: E402
from remora.governance.effect_receipt_signing import (  # noqa: E402
    RECEIPT_DOMAIN,
    EffectReceipt,
    sign_receipt,
)
from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402
from remora.toolcall.callable_digest import source_digest  # noqa: E402
from remora.toolcall.toolspec import sign_bundle  # noqa: E402
from servers import tool_registry_research  # noqa: E402

KEY = "capr-toolspec-key"
IDENTITY = "deploy@capr"
EXECUTOR_DOMAIN = "remora-acme"
VERIFIER = SigningKey.generate({RECEIPT_DOMAIN})
CONTENT = {"n": 1}
CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "rec-1", "content": CONTENT},
    "target_environment": "prod",
    "schema_valid": True,
}
POSTCONDITION = {
    "target_selector": {"artifact_id": {"$arg": "artifact_id"}},
    "expected_fields": {"content": {"$arg": "content"}},
    "comparison_rules": {"content": "hash"},
}


def _spec(with_postcondition: bool = True) -> dict:
    spec = {
        "tool_id": "store_artifact", "version": 1,
        "callable_digest": source_digest(tool_registry_research.store_artifact),
        "implementation_identity": "research-profile@test",
        "description": "Persist an artifact under the sandboxed directory.",
        "argument_schema": {
            "type": "object",
            "properties": {"artifact_id": {"type": "string"},
                           "content": {"type": "object"}},
            "required": ["artifact_id"], "additionalProperties": False,
        },
        "risk_tier": "medium", "action_type": "write", "domain": "general",
        "capabilities": ["artifact_management"],
        "semantic_contract": {
            "capability": "artifact_management", "effect": "create",
            "resource_type": "artifact", "mutation": True,
            "argument_roles": {"artifact_id": "target_resource"},
        },
        "credential_scope": ["artifacts:write"],
        "allowed_targets": ["staging", "prod"],
        "idempotency_contract": {"safe_to_retry": True,
                                 "key_derivation": "canonical_args"},
        "postcondition_reader": "artifact_reader", "compensation_tool": None,
        "timeout_policy": {"dispatch_timeout_seconds": 10},
        "network_policy": {"egress": "none"}, "signing_identity": IDENTITY,
    }
    if with_postcondition:
        spec["postcondition"] = POSTCONDITION
    return spec


def _verifier_keys(*, key: SigningKey = VERIFIER, control_domain="acme-observer",
                   scope="read_only") -> str:
    return json.dumps([{
        "public_key": key.verification_key().public_bytes.hex(),
        "control_domain": control_domain, "credential_scope": scope,
        "tenants": ["acme"],
    }])


def _client(monkeypatch, tmp_path, *, with_postcondition: bool = True):
    bundle = sign_bundle({"schema_version": 5,
                          "tool_specs": [_spec(with_postcondition)]},
                         key=KEY, signing_identity=IDENTITY,
                         signed_at="2026-10-18T00:00:00Z")
    path = tmp_path / "bundle-v5.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE", str(path))
    monkeypatch.setenv("REMORA_TOOLSPEC_SIGNING_KEY", KEY)
    monkeypatch.setenv("REMORA_TOOLSPEC_TRUSTED_IDENTITIES", IDENTITY)
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "capr-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "capr-lease-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.delenv("REMORA_RUNTIME_PROFILE", raising=False)
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    monkeypatch.setenv("REMORA_EFFECT_VERIFIER_KEYS", _verifier_keys())
    monkeypatch.setenv("REMORA_EXECUTOR_CONTROL_DOMAIN", EXECUTOR_DOMAIN)
    monkeypatch.setenv("REMORA_EFFECT_VERIFIER_BINDINGS", "reader-svc=acme.reader/v1")

    import servers.api as api_mod
    import servers.execution_api as exec_mod

    state = {"effect_principal": "reader-svc"}
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(
        api_mod, "_authenticated_principal",
        lambda request: (state["effect_principal"]
                         if "/effect" in request.url.path else "employee-1"))
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
    return TestClient(api_mod.app), state


@pytest.fixture()
def api(monkeypatch, tmp_path):
    return _client(monkeypatch, tmp_path)


def _executed(client) -> tuple[str, dict]:
    assessed = client.post("/v1/execution/assess", json=CALL)
    assert assessed.status_code == 200, assessed.text
    item = assessed.json()["review_item_id"]
    assert client.post("/v1/execution/approve", json={"item_id": item}).status_code == 200
    executed = client.post("/v1/execution/execute",
                           json={"item_id": item, "tool_call": CALL})
    assert executed.status_code == 200, executed.text
    assert executed.json()["outcome"] == "execute", executed.json()
    pid = str(assessed.json()["proposal_id"])
    import servers.execution_api as exec_mod

    result = [e.payload for e in exec_mod._CHAIN.entries("acme")
              if e.payload.get("event") == "execution_result"
              and e.payload.get("proposal_id") == pid][-1]
    return pid, result


def _post(client, pid: str, dispatch: dict, *, observed=None, key: SigningKey = VERIFIER,
          arguments=None, domain=None, **over):
    receipt = EffectReceipt(
        proposal_id=pid, grant_jti=dispatch["grant_jti"],
        tool_call_hash=dispatch["tool_call_hash"], tenant="acme",
        observed=({"artifact_id": "rec-1", "content": CONTENT}
                  if observed is None else observed),
        observed_at=(datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
        **over,
    )
    if domain is None:
        signature = sign_receipt(receipt, key)
    else:
        signature = sign(domain, receipt.canonical_bytes(), key)
    body = {"receipt": receipt.to_dict(), "signature": signature.to_dict(),
            "arguments": CALL["arguments"] if arguments is None else arguments}
    return client.post(f"/v1/execution/proposals/{pid}/effect-receipt", json=body)


def _state(client, pid: str) -> dict:
    return client.get(f"/v1/execution/proposals/{pid}").json()


# ── the verdict is computed (L7) ────────────────────────────────────────────

def test_an_honest_independent_receipt_verifies_independently(api) -> None:
    client, _ = api
    pid, dispatch = _executed(client)
    r = _post(client, pid, dispatch)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "EFFECT_VERIFIED"
    assert body["verdict_source"] == "computed"
    assert body["vantage"] == "independent"
    assert _state(client, pid)["current_state"] == "EFFECT_VERIFIED"


def test_remora_computes_a_mismatch_whatever_the_receipt_claims(api) -> None:
    """Expected != observed under the contract -> MISMATCH, computed (L7)."""
    client, _ = api
    pid, dispatch = _executed(client)
    r = _post(client, pid, dispatch,
              observed={"artifact_id": "rec-1", "content": {"n": 2}},
              claimed_status="EFFECT_VERIFIED")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "EFFECT_MISMATCH"
    assert body["claimed_status"] == "EFFECT_VERIFIED"
    assert body["claim_disagrees"] is True
    assert _state(client, pid)["current_state"] != "EFFECT_VERIFIED"


def test_an_observation_of_another_target_never_verifies(api) -> None:
    """Receipt for another call's row (L7). The frozen contract reports the
    target as not observed: UNOBSERVABLE, never VERIFIED."""
    client, _ = api
    pid, dispatch = _executed(client)
    r = _post(client, pid, dispatch,
              observed={"artifact_id": "rec-999", "content": CONTENT})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "EFFECT_UNOBSERVABLE"
    assert r.json()["reason_code"] == "postcondition_target_mismatch"


def test_an_unchanged_revision_is_not_an_attributable_effect(api) -> None:
    client, _ = api
    pid, dispatch = _executed(client)
    r = _post(client, pid, dispatch, source_revision="r7", pre_state_revision="r7")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "EFFECT_UNOBSERVABLE"
    assert r.json()["reason_code"] == "postcondition_no_attributable_change"


def test_arguments_other_than_the_dispatched_call_are_refused(api) -> None:
    client, _ = api
    pid, dispatch = _executed(client)
    r = _post(client, pid, dispatch,
              arguments={"artifact_id": "rec-1", "content": {"n": 2}})
    assert r.status_code == 409, r.text
    assert "arguments_not_the_dispatched_call" in r.text


def test_a_receipt_without_a_dispatch_is_refused(api) -> None:
    """A rejected proposal never dispatched: refused by lineage (L7)."""
    client, _ = api
    assessed = client.post("/v1/execution/assess", json=CALL).json()
    assert client.post("/v1/execution/reject", json={
        "item_id": assessed["review_item_id"], "reason": "no"}).status_code == 200
    fake = {"grant_jti": "jti-x", "tool_call_hash": assessed["tool_call_hash"]}
    r = _post(client, assessed["proposal_id"], fake)
    assert r.status_code == 409, r.text
    assert "no_dispatch" in r.text


def test_a_second_settled_receipt_is_a_replay(api) -> None:
    client, _ = api
    pid, dispatch = _executed(client)
    assert _post(client, pid, dispatch).status_code == 200
    r = _post(client, pid, dispatch)
    assert r.status_code == 409, r.text
    assert "receipt_replayed" in r.text


def test_a_tool_without_a_signed_postcondition_is_refused(monkeypatch, tmp_path) -> None:
    client, _ = _client(monkeypatch, tmp_path, with_postcondition=False)
    pid, dispatch = _executed(client)
    r = _post(client, pid, dispatch)
    assert r.status_code == 409, r.text
    assert "postcondition_not_declared" in r.text


# ── who signed it (L8) ──────────────────────────────────────────────────────

def test_a_receipt_signed_with_a_lease_key_is_refused(api, monkeypatch) -> None:
    client, _ = api
    lease_key = SigningKey.generate({SignatureDomain.EXECUTION_LEASE})
    monkeypatch.setenv("REMORA_EFFECT_VERIFIER_KEYS", _verifier_keys(key=lease_key))
    pid, dispatch = _executed(client)
    r = _post(client, pid, dispatch, key=lease_key,
              domain=SignatureDomain.EXECUTION_LEASE)
    assert r.status_code == 409, r.text
    assert "receipt_signature_domain_mismatch" in r.text


def test_an_unregistered_key_is_refused(api) -> None:
    client, _ = api
    pid, dispatch = _executed(client)
    r = _post(client, pid, dispatch, key=SigningKey.generate({RECEIPT_DOMAIN}))
    assert r.status_code == 409, r.text
    assert "receipt_signature_unknown_kid" in r.text


def test_a_verifier_in_the_executors_domain_is_same_deployment(api, monkeypatch) -> None:
    client, _ = api
    monkeypatch.setenv("REMORA_EFFECT_VERIFIER_KEYS",
                       _verifier_keys(control_domain=EXECUTOR_DOMAIN))
    pid, dispatch = _executed(client)
    r = _post(client, pid, dispatch)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "EFFECT_VERIFIED"
    assert r.json()["vantage"] == "same_deployment"


def test_a_verifier_that_can_write_is_same_deployment(api, monkeypatch) -> None:
    client, _ = api
    monkeypatch.setenv("REMORA_EFFECT_VERIFIER_KEYS", _verifier_keys(scope="read_write"))
    pid, dispatch = _executed(client)
    r = _post(client, pid, dispatch)
    assert r.status_code == 200, r.text
    assert r.json()["vantage"] == "same_deployment"


def test_an_undeclared_executor_domain_never_yields_independent(api, monkeypatch) -> None:
    client, _ = api
    monkeypatch.delenv("REMORA_EXECUTOR_CONTROL_DOMAIN", raising=False)
    pid, dispatch = _executed(client)
    r = _post(client, pid, dispatch)
    assert r.status_code == 200, r.text
    assert r.json()["vantage"] == "same_deployment"


def test_the_executor_cannot_submit_a_signed_receipt(api) -> None:
    client, state = api
    pid, dispatch = _executed(client)
    state["effect_principal"] = "employee-1"   # proposed and executed the call
    r = _post(client, pid, dispatch)
    assert r.status_code == 403, r.text
    assert "verifier_is_executor" in r.text


def test_no_registered_verifier_keys_is_unavailable(api, monkeypatch) -> None:
    client, _ = api
    monkeypatch.delenv("REMORA_EFFECT_VERIFIER_KEYS", raising=False)
    pid, dispatch = _executed(client)
    r = _post(client, pid, dispatch)
    assert r.status_code == 503, r.text
    assert "effect_verifier_keys_required" in r.text


# ── owner decision 4: unsigned receipts in the strict profiles ─────────────

def _unsigned(client, pid: str, dispatch: dict, *, with_observation: bool = False):
    body = {
        "execution_id": "e-1", "tool_id": "store_artifact",
        "tool_call_hash": dispatch["tool_call_hash"],
        "grant_jti": dispatch["grant_jti"],
        "status": "EFFECT_VERIFIED", "reason_code": "postcondition_verified",
        "verifier_identity": "acme.reader/v1",
        "expected_sha256": "a" * 64, "observed_sha256": "b" * 64,
        "verified_at": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
    }
    if with_observation:
        body["observed"] = {"artifact_id": "rec-1", "content": CONTENT}
        body["arguments"] = CALL["arguments"]
    return client.post(f"/v1/execution/proposals/{pid}/effect", json=body)


def test_controlled_pilot_refuses_an_unsigned_receipt(api, monkeypatch) -> None:
    client, _ = api
    pid, dispatch = _executed(client)
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "controlled_pilot")
    r = _unsigned(client, pid, dispatch)
    assert r.status_code == 409, r.text
    assert "unsigned_receipt_refused" in r.text


def test_review_records_an_unsigned_receipt_at_same_deployment(api, monkeypatch) -> None:
    client, _ = api
    pid, dispatch = _executed(client)
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "review")
    # Decision 4: review records an unsigned receipt, capped at
    # same_deployment. The tool declares a postcondition, so the receipt must
    # carry the observation and REMORA computes the verdict (SDD L7).
    bare = _unsigned(client, pid, dispatch)
    assert bare.status_code == 409, bare.text
    assert "postcondition_observation_required" in bare.text
    r = _unsigned(client, pid, dispatch, with_observation=True)
    assert r.status_code == 200, r.text
    assert r.json()["vantage"] == "same_deployment"
    assert r.json()["verdict_source"] == "computed"
    assert r.json()["status"] == "EFFECT_VERIFIED"


# ── P0-4A on the signed path, real tokens ───────────────────────────────────

def test_p0_4a_an_operator_cannot_use_the_signed_path(monkeypatch, tmp_path) -> None:
    from tests.test_effect_lineage_and_audit_projection import (
        _alice_crashed_call,
        _as,
        _token_client,
    )

    client = _token_client(monkeypatch, tmp_path)
    monkeypatch.setenv("REMORA_EFFECT_VERIFIER_KEYS", _verifier_keys())
    pid = _alice_crashed_call(client)
    receipt = EffectReceipt(proposal_id=pid, grant_jti="x", tool_call_hash="c" * 64,
                            tenant="acme", observed={"artifact_id": "rec-1"},
                            observed_at=datetime.now(UTC).isoformat())
    r = client.post(f"/v1/execution/proposals/{pid}/effect-receipt", json={
        "receipt": receipt.to_dict(),
        "signature": sign_receipt(receipt, VERIFIER).to_dict(),
        "arguments": CALL["arguments"],
    }, headers=_as("tok-alice"))
    assert r.status_code == 403, r.text
    view = client.get(f"/v1/execution/proposals/{pid}", headers=_as("tok-alice")).json()
    assert view["current_state"] != "EFFECT_VERIFIED"
