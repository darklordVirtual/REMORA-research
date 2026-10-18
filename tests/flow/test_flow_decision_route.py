# SPDX-License-Identifier: BUSL-1.1
"""IFC-05b: ``/v1/execution/assess`` reads the flow verdict (SDD v1.3 §3.7).

With ``REMORA_FLOW_CONTROL=1`` the execution API derives the ``flow_*``
fields from the flow context store and the call's ToolSpec ``flow`` block;
no request field sets them. Off, nothing changes.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.flow.handles import handle_token  # noqa: E402
from remora.flow.label import Integrity, Label  # noqa: E402
from remora.flow.spec import parse_flow  # noqa: E402
from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402

MODEL = "ext://api.provider.example"
USER = "user://acme/alice"
#: read_telemetry sends its query to an external telemetry service.
TELEMETRY_FLOW = parse_flow({
    "provider": "tcb", "arguments": {"asset": {"kind": "text"}},
    "sources": {"default_integrity": "TRUSTED"},
    "sink": {"recipients": {"static": ["ext://telemetry.example"]}, "payload_args": ["asset"]}})
READ = {"tool_name": "read_telemetry", "arguments": {"asset": "P-1"},
        "target_environment": "staging"}
FLOW_CODES = {"flow_state_unavailable", "flow_context_unknown", "flow_handle_invalid",
              "toolspec_flow_policy_missing", "flow_confidentiality_violation",
              "flow_integrity_violation_verify", "flow_integrity_violation_escalate"}


def _mod():
    import servers.execution_api as exec_mod

    return exec_mod


@pytest.fixture()
def principal():
    return {"name": "agent-1"}


@pytest.fixture()
def client(monkeypatch, tmp_path, principal):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "flow-decision-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_FLOW_CONTROL", "1")
    for var in ("REMORA_PG_DSN", "REMORA_CHAIN_DB", "REMORA_STATE_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    policy = tmp_path / "processing.json"
    policy.write_text(json.dumps({"acme": {"default": [MODEL]}}), encoding="utf-8")
    monkeypatch.setenv("REMORA_FLOW_PROCESSING_POLICY", str(policy))
    import servers.api as api_mod

    exec_mod = _mod()
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "operator"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: principal["name"])
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    monkeypatch.setattr(exec_mod, "_CHAIN", TenantAuditChain())
    monkeypatch.setattr(exec_mod, "_FLOW_CONTEXTS", None)
    monkeypatch.setattr(exec_mod, "_FLOW_HANDLES", None)
    monkeypatch.setattr(exec_mod, "_flow_spec",
                        lambda tool: TELEMETRY_FLOW if tool == "read_telemetry" else None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    return TestClient(api_mod.app)


def _context(client) -> str:
    r = client.post("/v1/contexts", json={"user_principal": USER, "model_principal": MODEL})
    assert r.status_code == 200, r.text
    return r.json()["context_id"]


def _assess(client, context_id: str | None = None, **extra):
    body = {**READ, **extra}
    if context_id is not None:
        body.update(context_id=context_id, task_id="task-1")
    r = client.post("/v1/execution/assess", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _flow_reasons(body) -> set[str]:
    return set(body.get("reasons") or ()) & FLOW_CODES


def test_a_call_without_a_context_abstains(client):
    body = _assess(client)
    assert body["decision"] == "abstain"
    assert _flow_reasons(body) == {"flow_context_unknown"}


def test_a_caller_chosen_context_id_abstains(client):
    body = _assess(client, context_id="ctx_" + "a" * 26)
    assert _flow_reasons(body) == {"flow_context_unknown"}


def test_a_context_of_another_principal_abstains(client, principal):
    context_id = _context(client)
    principal["name"] = "agent-2"
    assert _flow_reasons(_assess(client, context_id)) == {"flow_context_unknown"}


def test_a_clean_flow_leaves_the_decision_to_the_rest_of_the_floor(client, monkeypatch):
    context_id = _context(client)
    body = _assess(client, context_id)
    assert not _flow_reasons(body)
    monkeypatch.delenv("REMORA_FLOW_CONTROL")
    assert _assess(client)["decision"] == body["decision"]


def test_data_the_recipient_may_not_read_escalates(client):
    """F4 through the API: once the context holds the user's data, the
    telemetry service is a recipient outside its readers."""
    context_id = _context(client)
    _mod()._flow_contexts().raise_label("acme", "agent-1", context_id,
                                        Label({USER, MODEL}, Integrity.TRUSTED))
    body = _assess(client, context_id)
    assert body["decision"] == "escalate"
    assert _flow_reasons(body) == {"flow_confidentiality_violation"}
    # The agent channel rule: the code, never the recipient.
    assert "telemetry.example" not in json.dumps(body)


def test_an_unknown_handle_abstains(client):
    context_id = _context(client)
    body = _assess(client, context_id, arguments={"asset": handle_token("A" * 16)})
    assert _flow_reasons(body) == {"flow_handle_invalid"}


def test_a_tool_without_a_flow_block_is_not_refused_outside_the_strict_profile(client):
    context_id = _context(client)
    body = client.post("/v1/execution/assess", json={
        "tool_name": "store_artifact", "arguments": {"key": "k", "content": "c"},
        "context_id": context_id, "task_id": "task-1"}).json()
    assert not _flow_reasons(body)


def test_an_unavailable_store_abstains(client, monkeypatch):
    from remora.flow.context import FlowStoreUnavailable

    context_id = _context(client)

    class Down:
        def load(self, *a, **k):
            raise FlowStoreUnavailable("down")

    monkeypatch.setattr(_mod(), "_FLOW_CONTEXTS", Down())
    assert _flow_reasons(_assess(client, context_id)) == {"flow_state_unavailable"}


@pytest.mark.parametrize("smuggled", [
    {"flow_status": "evaluated"},
    {"flow_status": "evaluated", "flow_confidentiality_violation": False},
    {"flow": {"conf_viol": [], "int_viol": [], "ctrl_viol": False}},
])
def test_a_client_supplied_flow_is_ignored(client, smuggled):
    """No request field reaches the flow fields: the smuggled verdict changes nothing."""
    plain = _assess(client)
    r = client.post("/v1/execution/assess", json={**READ, **smuggled})
    assert r.status_code in (200, 422), r.text
    if r.status_code == 200:
        assert r.json()["decision"] == plain["decision"] == "abstain"
        assert _flow_reasons(r.json()) == {"flow_context_unknown"}


def test_with_flow_control_off_no_flow_field_is_set(client, monkeypatch):
    monkeypatch.delenv("REMORA_FLOW_CONTROL")
    from servers.execution_contracts import ToolCallRequest

    obs, _ = _mod()._observation_with_context(ToolCallRequest(**READ), "acme")
    assert obs.flow_status is None and obs.flow_digest is None
