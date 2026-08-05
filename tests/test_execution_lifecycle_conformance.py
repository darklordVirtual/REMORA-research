# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""FT-01: the live /v1/execution transitions conform to the lifecycle model.

Defense-in-depth: the review queue's own guards remain the primary
refusal path; the lifecycle check catches MODEL DRIFT — an endpoint
performing a transition the declared machine does not allow is an
internal inconsistency surfaced as HTTP 500 (fail-closed, logged), never
a silent divergence between schema and runtime.

Scope (realized subset, honest): assess/review/authorize stages only.
Dispatch-stage conformance arrives with the FT-02 outbox — the schema
declares those states ahead of implementation, and this suite does not
pretend otherwise.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.lifecycle import (  # noqa: E402
    ITEM_STATUS_STATE,
    IllegalTransition,
    check_transition,
)


# ── Unit: check_transition ──────────────────────────────────────────────────

def test_check_transition_accepts_declared_chain() -> None:
    assert check_transition("PROPOSED", "engine_decision") == "ASSESSED"
    assert check_transition("ASSESSED", "verify_or_escalate") == "REVIEW_PENDING"
    assert check_transition("REVIEW_PENDING", "human_approval") == "AUTHORIZED"


def test_check_transition_refuses_undeclared_move() -> None:
    with pytest.raises(IllegalTransition):
        check_transition("PROPOSED", "human_approval")


def test_item_status_map_covers_every_item_status() -> None:
    from remora.governance.review_queue import ItemStatus

    assert set(ITEM_STATUS_STATE) == {s.value for s in ItemStatus}


# ── Integration: green paths conform, drift turns into 500 ─────────────────

TASK_TEXT = "Create an artifact named wired-1 with the run summary."


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "lifecycle-conformance-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
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
    return TestClient(api_mod.app)


def test_review_loop_conforms_end_to_end(client) -> None:
    r = client.post("/v1/execution/assess", json={
        "tool_name": "store_artifact",
        "arguments": {"artifact_id": "wired-1", "content": {}},
        "target_environment": "prod",
        "schema_valid": True,
    })
    assert r.status_code == 200, r.text
    item_id = r.json()["review_item_id"]
    assert item_id

    r = client.post("/v1/execution/approve", json={"item_id": item_id})
    assert r.status_code == 200, r.text

    r = client.post("/v1/execution/execute", json={
        "item_id": item_id,
        "tool_call": {
            "tool_name": "store_artifact",
            "arguments": {"artifact_id": "wired-1", "content": {}},
            "target_environment": "prod",
            "schema_valid": True,
        },
    })
    assert r.status_code == 200, r.text


def test_abstain_path_conforms(client) -> None:
    r = client.post("/v1/execution/assess", json={
        "tool_name": "read_telemetry",
        "arguments": {"asset": "P-1"},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "abstain"
    assert body.get("review_item_id") is None


def test_model_drift_is_a_loud_500(client, monkeypatch) -> None:
    """A model that no longer admits the runtime's transition must refuse."""
    from remora.governance import lifecycle as lc

    model = lc.default_model()
    crippled = lc.LifecycleModel(
        states=model.states,
        terminal_states=model.terminal_states,
        transitions={k: v for k, v in model.transitions.items()
                     if k != ("ASSESSED", "verify_or_escalate")},
        version=model.version,
    )
    monkeypatch.setattr(lc, "_DEFAULT_MODEL", crippled)

    r = client.post("/v1/execution/assess", json={
        "tool_name": "store_artifact",
        "arguments": {"artifact_id": "wired-1", "content": {}},
        "target_environment": "prod",
    })
    assert r.status_code == 500
    assert "lifecycle" in json.dumps(r.json()).lower()
