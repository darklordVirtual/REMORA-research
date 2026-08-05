# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The whole chain, once, as a product would actually drive it.

Handoff gate §3. Every layer below has its own suite, and each passes in
isolation. That is exactly the condition under which a vertical breaks:
the seams are where assumptions differ, and no unit test looks at a seam.

So this suite drives the real ASGI app end to end — signed ToolSpec at
assessment, human review, a lease bound to that spec, dispatch through the
outbox, effect verification against the declared delta, and an evidence
export — and asserts the properties that only exist ACROSS layers:

- **one identity travels the whole chain.** The spec hash recorded at
  assessment is the one bound into the lease and the one carried by the
  effect record. If any layer minted its own, the binding would look
  intact while proving nothing;
- **a refusal stops the chain.** Not "is reported": a refused proposal
  must leave no dispatch behind, because a side effect that happened
  anyway is the failure mode the whole overlay exists to prevent;
- **the unknowns stay unknown.** An effect nobody could observe must not
  become a failure, a success, or a second dispatch.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402
from remora.sdk import (  # noqa: E402
    EffectStatus,
    build_postcondition,
    content_digest,
    verify_effect,
)
from remora.toolcall.toolspec import sign_bundle  # noqa: E402

KEY = "vertical-toolspec-key"
IDENTITY = "vertical-signer/v1"

CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "vertical-1", "content": {"reading": 41.7}},
    "target_environment": "prod",
    "schema_valid": True,
}


def _spec(**overrides) -> dict:
    spec = {
        "tool_id": "store_artifact",
        "version": 1,
        "callable_digest": "sha256:" + "a" * 64,
        "implementation_identity": "research-profile@vertical",
        "description": "Persist an artifact under the sandboxed directory.",
        "argument_schema": {
            "type": "object",
            "properties": {"artifact_id": {"type": "string"},
                           "content": {"type": "object"}},
            "required": ["artifact_id"],
            "additionalProperties": False,
        },
        "risk_tier": "medium",
        "action_type": "write",
        "domain": "general",
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
        "postcondition_reader": "artifacts.read",
        "compensation_tool": None,
        "timeout_policy": {"dispatch_timeout_seconds": 10},
        "network_policy": {"egress": "none"},
        "signing_identity": IDENTITY,
    }
    spec.update(overrides)
    return spec


def _bundle_file(tmp_path, specs=None, name="bundle.json"):
    bundle = sign_bundle(
        {"schema_version": 1, "tool_specs": specs or [_spec()]},
        key=KEY, signing_identity=IDENTITY, signed_at="2026-08-05T00:00:00Z",
    )
    path = tmp_path / name
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


@pytest.fixture()
def vertical(monkeypatch, tmp_path):
    """The real app, with signed specs enforced and a switchable tenant."""
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "vertical-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "vertical-lease-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE",
                       "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE", str(_bundle_file(tmp_path)))
    monkeypatch.setenv("REMORA_TOOLSPEC_SIGNING_KEY", KEY)
    monkeypatch.setenv("REMORA_TOOLSPEC_TRUSTED_IDENTITIES", IDENTITY)

    import servers.api as api_mod
    import servers.execution_api as exec_mod

    state = {"tenant": "acme"}
    monkeypatch.setattr(api_mod, "_authenticate",
                        lambda request: (state["tenant"], "reviewer"))
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
    return TestClient(api_mod.app), state, tmp_path


def _through_dispatch(client) -> dict:
    """assess -> approve -> execute. Returns both responses."""
    assessed = client.post("/v1/execution/assess", json=CALL).json()
    item_id = assessed["review_item_id"]
    assert client.post("/v1/execution/approve",
                       json={"item_id": item_id}).status_code == 200
    executed = client.post("/v1/execution/execute",
                           json={"item_id": item_id, "tool_call": CALL})
    assert executed.status_code == 200, executed.text
    return {"assessed": assessed, "executed": executed.json()}


def _postcondition():
    return build_postcondition(
        tool_id="store_artifact",
        target_selector={"artifact_id": "vertical-1"},
        expected_fields={
            "artifact_id": "vertical-1",
            "content": content_digest({"reading": 41.7}),
        },
        comparison_rules={"content": "hash"},
        reader="artifacts.read",
    )


def _observed(**overrides):
    obj = {"artifact_id": "vertical-1", "content": {"reading": 41.7}}
    obj.update(overrides)
    return obj


# ── 1. The chain closes ────────────────────────────────────────────────────

def test_the_full_vertical_closes_with_a_verified_effect(vertical) -> None:
    client, _state, _tmp = vertical
    run = _through_dispatch(client)
    proposal_id = run["executed"]["proposal_id"]

    result = verify_effect(
        _postcondition(), _observed(),
        proposal_id=proposal_id, execution_id=proposal_id,
        toolspec_hash=run["assessed"]["toolspec"]["hash"],
        verifier_identity="acme.artifact_reader/v1",
    )
    assert result.status is EffectStatus.VERIFIED

    posted = client.post(f"/v1/execution/proposals/{proposal_id}/effect",
                         json=result.to_dict())
    assert posted.status_code == 200, posted.text

    view = client.get(f"/v1/execution/proposals/{proposal_id}").json()
    assert view["current_state"] == "EFFECT_VERIFIED"


# ── 2. One identity, whole chain ───────────────────────────────────────────

def test_one_toolspec_hash_travels_from_assessment_to_the_effect_record(
    vertical,
) -> None:
    """If any layer minted its own, the binding would look intact while
    proving nothing."""
    client, _state, _tmp = vertical
    run = _through_dispatch(client)
    proposal_id = run["executed"]["proposal_id"]
    spec_hash = run["assessed"]["toolspec"]["hash"]
    assert len(spec_hash) == 64
    assert run["executed"]["toolspec"]["hash"] == spec_hash

    result = verify_effect(
        _postcondition(), _observed(), proposal_id=proposal_id,
        execution_id=proposal_id, toolspec_hash=spec_hash,
        verifier_identity="acme.artifact_reader/v1",
    )
    client.post(f"/v1/execution/proposals/{proposal_id}/effect",
                json=result.to_dict())

    trail = client.get(
        f"/v1/execution/proposals/{proposal_id}/lifecycle"
    ).json()
    hashes = {e["payload"]["toolspec_hash"] for e in trail["events"]
              if e["payload"].get("toolspec_hash")}
    assert hashes == {spec_hash}, hashes


# ── 3-6. Refusals stop the chain ───────────────────────────────────────────

def test_a_spec_redeployed_mid_review_refuses_the_stale_approval(
    vertical, monkeypatch,
) -> None:
    client, _state, tmp_path = vertical
    import servers.execution_api as exec_mod

    assessed = client.post("/v1/execution/assess", json=CALL).json()
    item_id = assessed["review_item_id"]
    assert client.post("/v1/execution/approve",
                       json={"item_id": item_id}).status_code == 200

    monkeypatch.setenv("REMORA_TOOLSPEC_BUNDLE", str(_bundle_file(
        tmp_path, [_spec(version=2)], name="bundle2.json")))
    exec_mod._reset_toolspec_bundle()

    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": CALL})
    assert r.status_code == 409
    assert "toolspec_changed_between_assess_and_dispatch" in r.json()["detail"]

    outbox = exec_mod._outbox().rows_for_proposal(
        "acme", assessed["proposal_id"])
    assert not outbox, "a refused proposal must leave no dispatch behind"


@pytest.mark.parametrize("payload,expected_reason", [
    (dict(CALL, arguments={"artifact_id": "a", "unexpected": 1}),
     "toolspec_arguments_schema_invalid"),
    (dict(CALL, target_environment="development"),
     "toolspec_target_not_allowed"),
    ({"tool_name": "read_telemetry", "arguments": {}},
     "toolspec_unknown_tool"),
])
def test_a_spec_violation_is_refused_before_anything_runs(
    vertical, payload, expected_reason,
) -> None:
    """Refused at assessment: there is no review item to approve, so the
    action cannot be reached by a later call either."""
    client, _state, _tmp = vertical
    r = client.post("/v1/execution/assess", json=payload)
    assert r.status_code == 409, r.text
    assert expected_reason in r.json()["detail"]


# ── 7-8. The verdicts, including the ones nobody likes ─────────────────────

def test_a_mismatch_is_recorded_without_touching_the_execution_record(
    vertical,
) -> None:
    client, _state, _tmp = vertical
    run = _through_dispatch(client)
    proposal_id = run["executed"]["proposal_id"]
    before = client.get(
        f"/v1/execution/proposals/{proposal_id}/lifecycle"
    ).json()["events"]

    result = verify_effect(
        _postcondition(), _observed(content={"reading": 99.9}),
        proposal_id=proposal_id, execution_id=proposal_id,
        toolspec_hash=run["assessed"]["toolspec"]["hash"],
        verifier_identity="acme.artifact_reader/v1",
    )
    assert result.status is EffectStatus.MISMATCH
    client.post(f"/v1/execution/proposals/{proposal_id}/effect",
                json=result.to_dict())

    after = client.get(
        f"/v1/execution/proposals/{proposal_id}/lifecycle"
    ).json()["events"]
    assert after[:len(before)] == before, "verification rewrote history"
    assert len(after) == len(before) + 1


def test_an_unobservable_effect_never_becomes_a_failure_or_a_retry(
    vertical,
) -> None:
    """The one nobody likes and everyone gets wrong: not knowing must not
    collapse into 'failed', and must never trigger a second dispatch of a
    side effect that may already have happened."""
    client, _state, _tmp = vertical
    run = _through_dispatch(client)
    proposal_id = run["executed"]["proposal_id"]
    import servers.execution_api as exec_mod

    dispatches_before = len(
        exec_mod._outbox().rows_for_proposal("acme", proposal_id))

    result = verify_effect(
        _postcondition(), None, proposal_id=proposal_id,
        execution_id=proposal_id,
        toolspec_hash=run["assessed"]["toolspec"]["hash"],
        verifier_identity="acme.artifact_reader/v1",
    )
    assert result.status is EffectStatus.UNOBSERVABLE
    client.post(f"/v1/execution/proposals/{proposal_id}/effect",
                json=result.to_dict())

    view = client.get(f"/v1/execution/proposals/{proposal_id}").json()
    assert view["current_state"] == "EFFECT_UNKNOWN"
    assert view["current_state"] != "FAILED"
    assert len(exec_mod._outbox().rows_for_proposal("acme", proposal_id)) \
        == dispatches_before


# ── 9. Tenancy holds across the whole vertical ─────────────────────────────

def test_another_tenant_can_neither_see_nor_annotate_the_proposal(
    vertical,
) -> None:
    client, state, _tmp = vertical
    run = _through_dispatch(client)
    proposal_id = run["executed"]["proposal_id"]

    state["tenant"] = "other-corp"
    assert client.get(
        f"/v1/execution/proposals/{proposal_id}").status_code == 404
    assert client.get(
        f"/v1/execution/proposals/{proposal_id}/evidence").status_code == 404
    assert client.post(
        f"/v1/execution/proposals/{proposal_id}/effect",
        json={"execution_id": "e", "tool_id": "store_artifact",
              "status": "EFFECT_VERIFIED",
              "reason_code": "postcondition_verified",
              "verifier_identity": "intruder/v1"},
    ).status_code == 404


# ── 10. The evidence an auditor actually receives ──────────────────────────

def test_the_evidence_bundle_carries_the_whole_vertical_and_verifies(
    vertical,
) -> None:
    client, _state, _tmp = vertical
    run = _through_dispatch(client)
    proposal_id = run["executed"]["proposal_id"]
    result = verify_effect(
        _postcondition(), _observed(), proposal_id=proposal_id,
        execution_id=proposal_id,
        toolspec_hash=run["assessed"]["toolspec"]["hash"],
        verifier_identity="acme.artifact_reader/v1",
    )
    client.post(f"/v1/execution/proposals/{proposal_id}/effect",
                json=result.to_dict())

    bundle = client.get(
        f"/v1/execution/proposals/{proposal_id}/evidence").json()
    for section in ("proposal", "lifecycle", "effect_verification",
                    "policy_identity", "audit_verification"):
        assert section in bundle, f"evidence lacks {section}"
        assert section in bundle["manifest"]["section_sha256"]
    assert bundle["audit_verification"]["valid"], bundle["audit_verification"]
    assert bundle["effect_verification"]["status"] == "EFFECT_VERIFIED"
    assert bundle["effect_verification"]["verifier_identity"] == \
        "acme.artifact_reader/v1"
