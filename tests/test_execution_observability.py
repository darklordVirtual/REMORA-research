# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The enforcement path must be visible in the metrics.

Found by running the OT pilot in production mode (2026-08-04): after fifteen
governed decisions and six real side effects, `/v1/metrics` still reported
`assess_total: 0` and every `decision_counts` entry at zero. The counters only
covered `/v1/assess`, so the path that actually enforces — the one a pilot
operator watches — was invisible. An operator cannot tell a working enforcement
plane from a dead one by looking at the metrics, which is the whole job of
metrics.

These tests pin that the execution path increments its own counters, that the
two paths stay separately attributable, and that a real side effect is counted
only when it actually happened.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "obs-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "admin"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "op-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda r, t, c: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role", lambda **kw: None)

    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE)
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_semantic_bundle()
    api_mod.reset_metrics()
    return TestClient(api_mod.app)


def _metrics(client) -> dict:
    return client.get("/v1/metrics").json()


def test_execution_assess_is_counted(client) -> None:
    before = _metrics(client)
    assert before["execution_assess_total"] == 0

    client.post("/v1/execution/assess",
                json={"tool_name": "read_telemetry", "arguments": {}})
    after = _metrics(client)
    assert after["execution_assess_total"] == 1


def test_execution_decisions_are_counted_by_action(client) -> None:
    client.post("/v1/execution/assess",
                json={"tool_name": "read_telemetry", "arguments": {}})
    client.post("/v1/execution/assess",
                json={"tool_name": "delete_production_database",
                      "arguments": {"db": "prod"}})
    counts = _metrics(client)["execution_decision_counts"]
    assert sum(counts.values()) == 2
    assert counts["escalate"] >= 1, counts


def test_execution_counters_are_separate_from_assess(client) -> None:
    """The advisory and enforcing paths must stay separately attributable:
    a pilot needs to know which plane produced a decision."""
    client.post("/v1/execution/assess",
                json={"tool_name": "read_telemetry", "arguments": {}})
    m = _metrics(client)
    assert m["execution_assess_total"] == 1
    assert m["assess_total"] == 0


def test_real_side_effect_is_counted_only_when_it_happened(client) -> None:
    call = {"tool_name": "store_artifact",
            "arguments": {"artifact_id": "obs-1", "content": {"x": 1}}}
    body = client.post("/v1/execution/assess", json=call).json()
    item = body.get("review_item_id")
    assert item, body

    assert _metrics(client)["execution_tool_calls_executed"] == 0

    client.post("/v1/execution/approve", json={"item_id": item})
    executed = client.post("/v1/execution/execute",
                           json={"item_id": item, "tool_call": call}).json()
    assert executed["tool_execution"]["executed"] is True

    m = _metrics(client)
    assert m["execution_tool_calls_executed"] == 1
    assert m["execution_approvals_total"] == 1
    assert m["execution_executes_total"] == 1


def test_refused_binding_is_counted_as_a_refusal_not_an_execution(client) -> None:
    call = {"tool_name": "store_artifact",
            "arguments": {"artifact_id": "obs-2", "content": {"x": 1}}}
    item = client.post("/v1/execution/assess", json=call).json()["review_item_id"]
    client.post("/v1/execution/approve", json={"item_id": item})

    tampered = dict(call, arguments={"artifact_id": "obs-2", "content": {"x": 2}})
    out = client.post("/v1/execution/execute",
                      json={"item_id": item, "tool_call": tampered}).json()
    assert out["outcome"] == "binding_refused"

    m = _metrics(client)
    assert m["execution_tool_calls_executed"] == 0
    assert m["execution_refusals"]["binding_refused"] == 1


def test_prometheus_exposes_the_execution_counters(client) -> None:
    client.post("/v1/execution/assess",
                json={"tool_name": "read_telemetry", "arguments": {}})
    body = client.get("/metrics").text
    for metric in ("remora_execution_assess_total",
                   "remora_execution_executes_total",
                   "remora_execution_tool_calls_executed_total"):
        assert metric in body, f"{metric} missing from the Prometheus export"
