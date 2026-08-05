# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""SHELF-020 follow-up: /v1/assess runs the semantic authority when given a tool call.

``/v1/assess`` is the DecisionEnvelope producer, but until this wiring the
envelope's ``tool_contract_bundle_hash`` / ``intent_authority_hash`` fields
had no producer (research_shelf_v1.yaml admitted it). With an optional
``tool_call`` block in the request and ``REMORA_SEMANTIC_BUNDLE_MODULE``
configured, the assess path now builds the same authoritative observation
as ``/v1/execution/assess`` (``build_full_observation``) and records the
computed hashes and semantic verdicts into the envelope's audit block.

Invariants under test:
- the recorded hashes are computed server-side, never client input;
- a caller cannot smuggle ``tool_matches_goal`` (or any semantic verdict)
  through the ``tool_call`` block — unknown fields are rejected;
- without a ``tool_call`` the endpoint behaves exactly as before
  (hashes stay None — recorded absence, not a fabricated value);
- without a configured bundle the hashes stay None even when a
  ``tool_call`` is present;
- the semantic verdicts are RECORDED on this path (audit truth), and the
  gate decision itself is produced by the question-based engine pipeline —
  decision impact of semantic verdicts on /v1/assess is out of scope here.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


TASK_TEXT = "Read the telemetry for asset P-1."


@pytest.fixture()
def intent_file(tmp_path):
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
    }), encoding="utf-8")
    return path


def _make_client(monkeypatch, tmp_path, semantic_module: str | None, intent_file=None):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "assess-semantic-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    if semantic_module:
        monkeypatch.setenv("REMORA_SEMANTIC_BUNDLE_MODULE", semantic_module)
    else:
        monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    if intent_file is not None:
        monkeypatch.setenv("REMORA_INTENT_SOURCE_FILE", str(intent_file))
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "operator"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    exec_mod._reset_semantic_bundle()
    return TestClient(api_mod.app)


@pytest.fixture()
def semantic_client(monkeypatch, tmp_path, intent_file):
    client = _make_client(
        monkeypatch, tmp_path, "servers.semantic_bundle_research", intent_file
    )
    yield client
    import servers.execution_api as exec_mod
    exec_mod._reset_semantic_bundle()


@pytest.fixture()
def bare_client(monkeypatch, tmp_path):
    client = _make_client(monkeypatch, tmp_path, None)
    yield client
    import servers.execution_api as exec_mod
    exec_mod._reset_semantic_bundle()


def _bundle_hash() -> str:
    from remora.toolcall.semantic_bundle import load_semantic_bundle

    return load_semantic_bundle().bundle_hash


def _assess(client, **overrides):
    payload = {"question": TASK_TEXT, "domain": "general", "risk_tier": "low"}
    payload.update(overrides)
    r = client.post("/v1/assess", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_tool_call_records_computed_bundle_and_intent_hashes(semantic_client):
    body = _assess(semantic_client, tool_call={
        "tool_name": "read_telemetry",
        "arguments": {"asset": "P-1"},
        "intent_ref": "wo-telemetry-1",
    })
    audit = body["envelope"]["audit"]
    assert audit["tool_contract_bundle_hash"] == _bundle_hash()
    assert audit["intent_authority_hash"], "resolved intent must record its authority hash"
    semantic = body["semantic"]
    assert semantic["tool_contract_bundle_hash"] == _bundle_hash()
    assert semantic["tool_matches_goal"] is True


def test_without_tool_call_hashes_stay_none(semantic_client):
    body = _assess(semantic_client)
    audit = body["envelope"]["audit"]
    assert audit["tool_contract_bundle_hash"] is None
    assert audit["intent_authority_hash"] is None
    assert body.get("semantic") is None


def test_without_bundle_hashes_stay_none_even_with_tool_call(bare_client):
    body = _assess(bare_client, tool_call={
        "tool_name": "read_telemetry",
        "arguments": {},
    })
    audit = body["envelope"]["audit"]
    assert audit["tool_contract_bundle_hash"] is None
    assert audit["intent_authority_hash"] is None
    assert body.get("semantic") is None


def test_caller_cannot_smuggle_semantic_verdicts(semantic_client):
    r = semantic_client.post("/v1/assess", json={
        "question": TASK_TEXT,
        "tool_call": {
            "tool_name": "read_telemetry",
            "arguments": {},
            "tool_matches_goal": True,
        },
    })
    assert r.status_code == 422, (
        "unknown tool_call fields must be rejected, not silently dropped"
    )


def test_tool_call_binds_canonical_args_hash(semantic_client):
    from remora.policy.observation import canonical_tool_call_hash

    body = _assess(semantic_client, tool_call={
        "tool_name": "read_telemetry",
        "arguments": {"asset": "P-1"},
    })
    audit = body["envelope"]["audit"]
    # Same preimage as the execution path and the ExecutionLease: the
    # registry's target_environment override wins (read_telemetry → staging).
    assert audit["tool_args_hash"] == canonical_tool_call_hash(
        name="read_telemetry",
        arguments={"asset": "P-1"},
        tenant="acme",
        target="staging",
    )
