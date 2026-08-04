# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""SHELF-020 closure: /v1/execution runs the authoritative context builder.

With ``REMORA_SEMANTIC_BUNDLE_MODULE`` configured, ``/v1/execution/assess``
builds its observation through ``build_full_observation`` — the same function
the benchmarks lock — with a registered, hashed contract bundle and an intent
resolved from a deployment-declared source (``task_intent_authority_v1.md``).
The bundle and intent-authority hashes bind into the audit chain at assess
time and into the ExecutionLease at execute time.

The invariants under test:
- no caller can set ``tool_matches_goal`` (or deliver an intent) in the request;
- an unresolved/absent intent yields ``None`` fields, never a fabricated value;
- the hashes recorded are the computed bundle hashes, not client input.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402


TASK_TEXT = "Read the telemetry for asset P-1."


@pytest.fixture()
def intent_file(tmp_path):
    """A deployment-declared workflow-intent source (approved template file)."""
    path = tmp_path / "workflow_intents.json"
    path.write_text(json.dumps({
        "wo-telemetry-1": {
            "task_text": TASK_TEXT,
            "operation": "read",
            "resource_type": "telemetry",
            "requested_effect": "read",
            "target_entities": [],
            "source_spans": ["telemetry"],
            "action_spans": ["read the telemetry"],
        },
        "wo-artifact-1": {
            "task_text": "Create an artifact named wired-1 with the run summary.",
            "operation": "create",
            "resource_type": "artifact",
            "requested_effect": "create",
            "target_entities": ["target_resource"],
            "source_spans": ["artifact"],
            "action_spans": ["create an artifact"],
        },
    }), encoding="utf-8")
    return path


@pytest.fixture()
def client(monkeypatch, tmp_path, intent_file):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "semantic-wiring-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv(
        "REMORA_SEMANTIC_BUNDLE_MODULE", "servers.semantic_bundle_research"
    )
    monkeypatch.setenv("REMORA_INTENT_SOURCE_FILE", str(intent_file))
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role",
                        lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE)
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_semantic_bundle()
    yield TestClient(api_mod.app)
    exec_mod._reset_semantic_bundle()


def _chain():
    import servers.execution_api as exec_mod

    return exec_mod._CHAIN


def _bundle_hash() -> str:
    from remora.toolcall.semantic_bundle import load_semantic_bundle

    return load_semantic_bundle().bundle_hash


# ---------------------------------------------------------------------------
# Assess: the semantic layer runs, and its hashes are recorded
# ---------------------------------------------------------------------------

def test_assess_records_computed_bundle_hash(client) -> None:
    r = client.post("/v1/execution/assess", json={
        "tool_name": "read_telemetry",
        "arguments": {},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["semantic"]["tool_contract_bundle_hash"] == _bundle_hash()
    record = _chain().entries("acme")[-1].payload
    assert record["tool_contract_bundle_hash"] == _bundle_hash()
    assert len(record["state_hash"]) == 64


def test_resolved_workflow_intent_establishes_goal_match(client) -> None:
    """A read call under a matching template intent: the goal-match authority
    (contract + verbatim spans) establishes tool_matches_goal=True. The
    intent-authority hash is recorded so the decision names its source."""
    r = client.post("/v1/execution/assess", json={
        "tool_name": "read_telemetry",
        "arguments": {},
        "intent_ref": "wo-telemetry-1",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["semantic"]["tool_matches_goal"] is True
    assert len(body["semantic"]["intent_authority_hash"]) == 64
    record = _chain().entries("acme")[-1].payload
    assert record["intent_authority_hash"] == body["semantic"]["intent_authority_hash"]


def test_wrong_tool_under_intent_is_established_contradiction(client) -> None:
    """store_artifact under a read-telemetry intent is the §34 residue case:
    well-formed call, wrong resource and effect — UNSUPPORTED, and the
    decision cannot be ACCEPT."""
    r = client.post("/v1/execution/assess", json={
        "tool_name": "store_artifact",
        "arguments": {"artifact_id": "a-1", "content": {"x": 1}},
        "intent_ref": "wo-telemetry-1",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["semantic"]["tool_matches_goal"] is False
    assert body["decision"] != "accept"


def test_unknown_intent_ref_yields_none_not_a_value(client) -> None:
    r = client.post("/v1/execution/assess", json={
        "tool_name": "read_telemetry",
        "arguments": {},
        "intent_ref": "no-such-ref",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["semantic"]["tool_matches_goal"] is None
    assert body["semantic"]["intent_authority_hash"] == ""


def test_caller_cannot_inject_goal_match_or_intent(client) -> None:
    """The request is a proposal: extra fields asserting semantic verdicts or
    carrying an inline intent are ignored (authority doc §2.3 — an intent
    cannot be delivered inside the tool call request)."""
    r = client.post("/v1/execution/assess", json={
        "tool_name": "read_telemetry",
        "arguments": {},
        "tool_matches_goal": True,
        "expected_effect_matches": True,
        "intent": {
            "operation": "read",
            "resource_type": "telemetry",
            "requested_effect": "read",
            "source_spans": ["telemetry"],
            "action_spans": ["read the telemetry"],
        },
        "task_text": TASK_TEXT,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["semantic"]["tool_matches_goal"] is None
    assert body["semantic"]["intent_authority_hash"] == ""


def test_without_bundle_module_behavior_is_unchanged(client, monkeypatch) -> None:
    """No bundle configured → the legacy registry-only path, explicitly
    labelled: absent semantics are absent, not defaulted."""
    import servers.execution_api as exec_mod

    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE")
    exec_mod._reset_semantic_bundle()
    r = client.post("/v1/execution/assess", json={
        "tool_name": "read_telemetry",
        "arguments": {},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["semantic"]["tool_contract_bundle_hash"] == ""
    assert body["semantic"]["tool_matches_goal"] is None


# ---------------------------------------------------------------------------
# Execute: the hashes bind into the lease and the audit chain
# ---------------------------------------------------------------------------

def test_execution_lease_binds_bundle_and_intent_hashes(client) -> None:
    call = {
        "tool_name": "store_artifact",
        "arguments": {"artifact_id": "wired-1", "content": {"ok": True}},
        "target_environment": "prod",
        "intent_ref": "wo-artifact-1",
    }
    assess = client.post("/v1/execution/assess", json=call).json()
    assert assess["semantic"]["tool_matches_goal"] is True, assess
    item_id = assess.get("review_item_id")
    assert item_id, assess
    approve = client.post("/v1/execution/approve", json={"item_id": item_id})
    assert approve.status_code == 200, approve.text
    execute = client.post("/v1/execution/execute", json={
        "item_id": item_id,
        "tool_call": call,
    })
    assert execute.status_code == 200, execute.text
    body = execute.json()
    assert body["outcome"] == "execute", body

    authorized = [
        e.payload for e in _chain().entries("acme")
        if e.payload.get("event") == "execution_authorized"
    ]
    assert authorized, "no execution_authorized record on the chain"
    record = authorized[-1]
    assert record["tool_contract_bundle_hash"] == _bundle_hash()
    assert len(record["intent_authority_hash"]) == 64
