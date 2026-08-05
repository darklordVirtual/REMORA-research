# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Reading a proposal's whole life, and exporting it (AAE §12/§16).

One ``proposal_id`` already follows a call from assessment to effect
through the audit chain and the outbox. Until now nothing could read that
back: an integrator could act but not review, and an auditor had no way
to get a proposal's record out of the system.

Three read paths close it:

- ``GET /v1/execution/proposals/{id}`` — the decision and where it stands;
- ``GET /v1/execution/proposals/{id}/lifecycle`` — the ordered event trail;
- ``GET /v1/execution/proposals/{id}/evidence`` — the export bundle.

All three are projections over stores of record (audit chain + outbox),
never a fourth store, so they cannot disagree with what actually
happened. They are tenant-scoped: a proposal belonging to another tenant
is a 404, not a redacted 200.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

WRITE_CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "life-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "lifecycle-read-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
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
    exec_mod._reset_outbox()
    return TestClient(api_mod.app)


def _executed_proposal(client) -> str:
    r = client.post("/v1/execution/assess", json=WRITE_CALL)
    assert r.status_code == 200, r.text
    body = r.json()
    item_id = body["review_item_id"]
    assert client.post("/v1/execution/approve",
                       json={"item_id": item_id}).status_code == 200
    ex = client.post("/v1/execution/execute",
                     json={"item_id": item_id, "tool_call": WRITE_CALL})
    assert ex.status_code == 200, ex.text
    return body["proposal_id"]


# ── The proposal view ──────────────────────────────────────────────────────

def test_get_proposal_reports_decision_and_current_state(client) -> None:
    pid = _executed_proposal(client)
    r = client.get(f"/v1/execution/proposals/{pid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["proposal_id"] == pid
    assert body["decision"] in ("verify", "escalate")
    assert body["tool_name"] == "store_artifact"
    assert body["current_state"], "a proposal must say where it stands"
    assert body["event_count"] >= 3


def test_unknown_proposal_is_404(client) -> None:
    assert client.get("/v1/execution/proposals/not-a-proposal").status_code == 404


def test_another_tenants_proposal_is_not_readable(client, monkeypatch) -> None:
    """Tenant scoping is a 404, not a redacted 200."""
    pid = _executed_proposal(client)
    import servers.api as api_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("globex", "reviewer"))
    assert client.get(f"/v1/execution/proposals/{pid}").status_code == 404


# ── The lifecycle trail ────────────────────────────────────────────────────

def test_lifecycle_is_the_ordered_event_trail(client) -> None:
    pid = _executed_proposal(client)
    r = client.get(f"/v1/execution/proposals/{pid}/lifecycle")
    assert r.status_code == 200, r.text
    body = r.json()
    events = [e["event"] for e in body["events"]]
    assert events[0] == "assessed"
    assert "approved" in events
    assert "execution_authorized" in events
    assert "execution_result" in events
    # Sequence numbers come from the chain and must be non-decreasing.
    seqs = [e["sequence_no"] for e in body["events"]]
    assert seqs == sorted(seqs)


def test_lifecycle_includes_the_dispatch_intent_state(client) -> None:
    """The outbox is a store of record too; the trail must show its verdict."""
    pid = _executed_proposal(client)
    body = client.get(f"/v1/execution/proposals/{pid}/lifecycle").json()
    assert body["dispatch"] is not None
    assert body["dispatch"]["state"] in (
        "SUCCEEDED", "FAILED", "REFUSED", "UNKNOWN",
    )


# ── The evidence bundle ────────────────────────────────────────────────────

def test_evidence_bundle_carries_a_hashed_manifest(client) -> None:
    pid = _executed_proposal(client)
    r = client.get(f"/v1/execution/proposals/{pid}/evidence")
    assert r.status_code == 200, r.text
    bundle = r.json()
    manifest = bundle["manifest"]
    assert manifest["proposal_id"] == pid
    assert manifest["remora_version"]
    assert manifest["event_count"] == len(bundle["lifecycle"]["events"])
    assert manifest["exported_at"]
    # Every section the manifest lists must actually be present and hashed.
    for name, digest in manifest["section_sha256"].items():
        assert name in bundle, f"manifest lists a missing section: {name}"
        assert len(digest) == 64


def test_evidence_hashes_match_the_content(client) -> None:
    """A manifest whose hashes do not cover the payload proves nothing."""
    import hashlib
    import json

    pid = _executed_proposal(client)
    bundle = client.get(f"/v1/execution/proposals/{pid}/evidence").json()
    for name, digest in bundle["manifest"]["section_sha256"].items():
        canonical = json.dumps(bundle[name], sort_keys=True,
                               separators=(",", ":"), default=str)
        assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == digest, name


def test_evidence_states_the_audit_chain_verdict(client) -> None:
    pid = _executed_proposal(client)
    bundle = client.get(f"/v1/execution/proposals/{pid}/evidence").json()
    assert bundle["audit_verification"]["valid"] is True
    assert bundle["audit_verification"]["records_checked"] >= 3


# ── SDK ────────────────────────────────────────────────────────────────────

def test_sdk_exposes_the_three_read_operations(client) -> None:
    from remora.sdk import ProposalView, RemoraClient, ToolCall

    sdk = RemoraClient("http://demo", token="t", http_client=client)
    result = sdk.assess(ToolCall(
        tool_name="store_artifact",
        arguments={"artifact_id": "life-2", "content": {"n": 2}},
        target_environment="prod", schema_valid=True,
    ))
    pid = result.proposal_id

    view = sdk.get_proposal(pid)
    assert isinstance(view, ProposalView)
    assert view.proposal_id == pid
    assert view.current_state

    lifecycle = sdk.get_lifecycle(pid)
    assert lifecycle.proposal_id == pid
    assert lifecycle.events and lifecycle.events[0]["event"] == "assessed"

    evidence = sdk.export_evidence(pid)
    assert evidence["manifest"]["proposal_id"] == pid
