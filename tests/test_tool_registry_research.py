# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the research-profile tool registry (issue #13 follow-up).

The registry must stay side-effect-bounded: writes cannot escape the
sandbox directory, reads are explicit about missing sources, and the
end-to-end API path dispatches through it under governance.
"""
from __future__ import annotations

import json

import pytest

from servers.tool_registry_research import (
    read_telemetry,
    register_tools,
    store_artifact,
)


def test_register_tools_registers_only_bounded_tools() -> None:
    seen: dict = {}
    register_tools(lambda name, fn: seen.__setitem__(name, fn))
    assert set(seen) == {"store_artifact", "read_telemetry"}
    # Destructive/critical tools must never appear in the research profile.
    assert "delete_production_database" not in seen
    assert "update_work_order" not in seen


def test_store_artifact_writes_inside_sandbox(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path))
    out = store_artifact({"artifact_id": "run-42.summary", "content": {"n": 544}})
    assert out["stored"] is True
    written = json.loads((tmp_path / "run-42.summary.json").read_text(encoding="utf-8"))
    assert written["content"] == {"n": 544}
    assert len(out["sha256"]) == 64


@pytest.mark.parametrize("bad_id", [
    "../escape", "..", "a/b", "a\\b", ".hidden", "", "x" * 200,
])
def test_store_artifact_rejects_unsafe_artifact_ids(bad_id, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        store_artifact({"artifact_id": bad_id, "content": {}})
    assert list(tmp_path.iterdir()) == []


def test_read_telemetry_without_source_is_explicit(monkeypatch) -> None:
    monkeypatch.delenv("REMORA_TELEMETRY_FILE", raising=False)
    out = read_telemetry({})
    assert out["source"] == "none"
    assert out["reading"] is None


def test_read_telemetry_reads_configured_file(tmp_path, monkeypatch) -> None:
    f = tmp_path / "telemetry.json"
    f.write_text(json.dumps({"asset": "P-1", "temp_c": 61.5}), encoding="utf-8")
    monkeypatch.setenv("REMORA_TELEMETRY_FILE", str(f))
    out = read_telemetry({"asset": "P-1"})
    assert out["reading"]["temp_c"] == 61.5


def test_end_to_end_execute_dispatches_research_tool(tmp_path, monkeypatch) -> None:
    """Full governed chain with the research registry: assess -> approve ->
    execute -> store_artifact writes inside the sandbox."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "research-registry-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "researcher-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role", lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE)
    exec_mod._reset_tool_dispatcher()
    client = TestClient(api_mod.app)

    call = {
        "tool_name": "store_artifact",
        "arguments": {"artifact_id": "e2e-research", "content": {"ok": True}},
        "risk_tier": "medium",
        "action_type": "write",
        "target_environment": "staging",
        "phase": "ordered",
        "trust_score": 0.85,
        "evidence_action": "verify",
        "evidence_confidence": 0.8,
        "schema_valid": True,
        "rollback_available": True,
    }
    r = client.post("/v1/execution/assess", json=call)
    assert r.status_code == 200, r.text
    item_id = r.json().get("review_item_id")
    if item_id:  # verify/escalate path: approve then execute
        assert client.post("/v1/execution/approve",
                           json={"item_id": item_id, "approval_ttl_seconds": 900}
                           ).status_code == 200
        body = client.post("/v1/execution/execute",
                           json={"item_id": item_id, "tool_call": call}).json()
        assert body["outcome"] == "execute", body
        assert body["tool_execution"]["executed"] is True, body
        assert (tmp_path / "e2e-research.json").exists()
