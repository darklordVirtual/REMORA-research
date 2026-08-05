# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""DerivationReceipt over the wire (queued slice from the theme-3 mechanism).

The receipt mechanism landed in ``derivation.py``; this slice lets a
deployed agent PROPOSE receipts through the server APIs: an optional
``derivations`` list on ``/v1/execution/assess`` and inside
``/v1/assess``'s ``tool_call`` block, threaded through
``semantic_call_context`` into the episode the authoritative builder
grounds against.

Invariants under test:
- a verified receipt grounds a derived argument value end-to-end
  (observation-level ``argument_values_grounded``), an absent or invalid
  receipt leaves it ungrounded — fail-closed;
- receipt dicts are schema-bound (``extra="forbid"``): unknown keys —
  including smuggled semantic verdicts — are rejected with 422;
- the receipts are proposals; acceptance happens only in
  ``derivation.verify_receipt``'s deterministic re-execution.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


ARTIFACT_TASK = "Create an artifact named wired-1 with the run summary."


@pytest.fixture()
def intent_file(tmp_path):
    path = tmp_path / "workflow_intents.json"
    path.write_text(json.dumps({
        "wo-artifact-1": {
            "task_text": ARTIFACT_TASK,
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
def semantic_env(monkeypatch, tmp_path, intent_file):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "derivation-threading-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv(
        "REMORA_SEMANTIC_BUNDLE_MODULE", "servers.semantic_bundle_research"
    )
    monkeypatch.setenv("REMORA_INTENT_SOURCE_FILE", str(intent_file))
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    import servers.execution_api as exec_mod

    exec_mod._reset_semantic_bundle()
    yield exec_mod
    exec_mod._reset_semantic_bundle()


UPPERCASE_RECEIPT = {
    "argument": "artifact_id",
    "value": "WIRED-1",
    "transform": "uppercase",
    "source_span": "wired-1",
}


def test_verified_receipt_grounds_via_semantic_call_context(semantic_env):
    obs, _context = semantic_env.semantic_call_context(
        tool_name="store_artifact",
        arguments={"artifact_id": "WIRED-1"},
        tenant="acme",
        intent_ref="wo-artifact-1",
        derivations=(UPPERCASE_RECEIPT,),
    )
    assert obs is not None
    assert obs.argument_values_grounded is True


def test_without_receipt_derived_value_stays_ungrounded(semantic_env):
    obs, _context = semantic_env.semantic_call_context(
        tool_name="store_artifact",
        arguments={"artifact_id": "WIRED-1"},
        tenant="acme",
        intent_ref="wo-artifact-1",
    )
    assert obs is not None
    assert obs.argument_values_grounded is False


def test_invalid_receipt_does_not_ground(semantic_env):
    bogus = dict(UPPERCASE_RECEIPT, transform="llm_reasoning")
    obs, _context = semantic_env.semantic_call_context(
        tool_name="store_artifact",
        arguments={"artifact_id": "WIRED-1"},
        tenant="acme",
        intent_ref="wo-artifact-1",
        derivations=(bogus,),
    )
    assert obs is not None
    assert obs.argument_values_grounded is False


# ── Wire surface: both endpoints accept proposals, reject smuggling ─────────

@pytest.fixture()
def client(semantic_env, monkeypatch):
    import servers.api as api_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "operator"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    return TestClient(api_mod.app)


def test_execution_assess_accepts_derivations(client):
    r = client.post("/v1/execution/assess", json={
        "tool_name": "store_artifact",
        "arguments": {"artifact_id": "WIRED-1"},
        "intent_ref": "wo-artifact-1",
        "derivations": [UPPERCASE_RECEIPT],
    })
    assert r.status_code == 200, r.text


def test_execution_assess_rejects_smuggled_verdict_in_receipt(client):
    poisoned = dict(UPPERCASE_RECEIPT, tool_matches_goal=True)
    r = client.post("/v1/execution/assess", json={
        "tool_name": "store_artifact",
        "arguments": {"artifact_id": "WIRED-1"},
        "derivations": [poisoned],
    })
    assert r.status_code == 422, (
        "unknown receipt fields must be rejected, not silently dropped"
    )


def test_assess_tool_call_accepts_derivations(client):
    r = client.post("/v1/assess", json={
        "question": ARTIFACT_TASK,
        "tool_call": {
            "tool_name": "store_artifact",
            "arguments": {"artifact_id": "WIRED-1"},
            "intent_ref": "wo-artifact-1",
            "derivations": [UPPERCASE_RECEIPT],
        },
    })
    assert r.status_code == 200, r.text


def test_assess_tool_call_rejects_smuggled_verdict_in_receipt(client):
    poisoned = dict(UPPERCASE_RECEIPT, expected_effect_matches=True)
    r = client.post("/v1/assess", json={
        "question": ARTIFACT_TASK,
        "tool_call": {
            "tool_name": "store_artifact",
            "arguments": {"artifact_id": "WIRED-1"},
            "derivations": [poisoned],
        },
    })
    assert r.status_code == 422
