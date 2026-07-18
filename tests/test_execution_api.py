# Author: Stian Skogbrott
# License: Apache-2.0
"""REM-034/035 acceptance: atomic tenant chain + end-to-end execution API."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402


# ---------------------------------------------------------------------------
# TenantAuditChain (REM-034)
# ---------------------------------------------------------------------------

def test_chain_hash_covers_predecessor_tenant_sequence_time() -> None:
    chain = TenantAuditChain()
    first = chain.append("acme", {"event": "a"})
    second = chain.append("acme", {"event": "b"})
    assert second.previous_hash == first.entry_hash
    assert (second.tenant_id, second.sequence_no) == ("acme", 1)
    ok, problems = chain.verify("acme")
    assert ok, problems
    # Tampering with previous_hash now breaks entry_hash verification.
    object.__setattr__(second, "previous_hash", "f" * 64)
    ok, problems = chain.verify("acme")
    assert not ok and any("hash_mismatch" in p or "chain_break" in p for p in problems)


def test_concurrent_appends_cannot_fork_the_chain() -> None:
    """100 racing appends: strictly monotone sequence, one predecessor each."""
    chain = TenantAuditChain()
    barrier = threading.Barrier(20)

    def append(i: int) -> None:
        barrier.wait(timeout=10)
        for j in range(5):
            chain.append("acme", {"event": f"{i}-{j}"})

    with ThreadPoolExecutor(max_workers=20) as pool:
        for f in [pool.submit(append, i) for i in range(20)]:
            f.result(timeout=30)
    entries = chain.entries("acme")
    assert len(entries) == 100
    assert [e.sequence_no for e in entries] == list(range(100))
    ok, problems = chain.verify("acme")
    assert ok, problems  # no forks: every entry chains to exactly one predecessor


def test_tenants_have_independent_chains() -> None:
    chain = TenantAuditChain()
    chain.append("a", {"e": 1})
    chain.append("b", {"e": 2})
    assert chain.entries("a")[0].previous_hash == "0" * 64
    assert chain.entries("b")[0].previous_hash == "0" * 64
    ok, _ = chain.verify_all()
    assert ok


# ---------------------------------------------------------------------------
# Execution API (REM-035)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "exec-api-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role",
                        lambda **kwargs: None)
    # Reset module state between tests.
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._GATE = exec_mod.EnforcementGate(strict=True, audience=exec_mod.PEP_AUDIENCE)
    return TestClient(api_mod.app)


LOW_READ = {
    "tool_name": "read_telemetry",
    "arguments": {"asset": "P-1"},
    "risk_tier": "low",
    "action_type": "read",
    "target_environment": "staging",
    "phase": "ordered",
    "trust_score": 0.92,
    "evidence_action": "answer",
    "evidence_confidence": 0.9,
    "schema_valid": True,
}
PROD_WRITE = {
    "tool_name": "update_work_order",
    "arguments": {"order": "WO-1", "action": "reschedule"},
    "risk_tier": "high",
    "action_type": "production_write",
    "target_environment": "prod",
    "phase": "ordered",
    "trust_score": 0.86,
    "evidence_action": "verify",
    "evidence_confidence": 0.8,
    "schema_valid": True,
    "rollback_available": True,
}


def test_accept_path_issues_signed_short_lived_token(client) -> None:
    r = client.post("/v1/execution/assess", json=LOW_READ)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "accept"
    token = body["execution_token"]
    assert token["audience"] == "pep://remora-execution"
    assert token["expires_at"] is not None and token["jti"]
    assert body["audit"]["sequence_no"] == 0


def test_full_verify_approve_execute_flow_with_one_time_grant(client) -> None:
    # 1. Assess: production write -> VERIFY -> queued.
    r = client.post("/v1/execution/assess", json=PROD_WRITE)
    assert r.json()["decision"] == "verify"
    item_id = r.json()["review_item_id"]
    # 2. Approve (authenticated principal recorded, not client-declared).
    r = client.post("/v1/execution/approve",
                    json={"item_id": item_id, "approval_ttl_seconds": 900})
    assert r.status_code == 200, r.text
    # 3. Execute with the SAME payload: fresh re-gate passes, one-time grant.
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": PROD_WRITE})
    body = r.json()
    assert body["outcome"] == "execute", body
    assert body["pep"]["allowed"] is True
    # 4. Audit chain verifies end to end and carries every transition.
    r = client.get("/v1/execution/audit/verify")
    assert r.json()["valid"] is True
    import servers.execution_api as exec_mod
    events = [e.payload["event"] for e in exec_mod._CHAIN.entries("acme")]
    assert events == ["assessed", "approved", "execution_execute"]


def test_riskier_world_invalidates_approval_at_execution(client) -> None:
    item_id = client.post("/v1/execution/assess", json=PROD_WRITE).json()["review_item_id"]
    client.post("/v1/execution/approve", json={"item_id": item_id})
    # Same payload (same hash), riskier world: rollback no longer available
    # -> the engine escalates, which is stricter than the approved VERIFY.
    riskier = {**PROD_WRITE, "rollback_available": False}
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": riskier})
    assert r.json()["outcome"] == "approval_invalidated"


def test_changed_arguments_are_refused_by_binding(client) -> None:
    item_id = client.post("/v1/execution/assess", json=PROD_WRITE).json()["review_item_id"]
    client.post("/v1/execution/approve", json={"item_id": item_id})
    swapped = {**PROD_WRITE, "arguments": {"order": "WO-999", "action": "cancel"}}
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": swapped})
    assert r.json()["outcome"] == "binding_refused"


def test_cross_tenant_item_access_is_refused(client) -> None:
    item_id = client.post("/v1/execution/assess", json=PROD_WRITE).json()["review_item_id"]
    import servers.api as api_mod
    api_mod._authenticate = lambda request: ("other-tenant", "reviewer")
    r = client.post("/v1/execution/approve", json={"item_id": item_id})
    assert r.status_code == 404


def test_profile_approval_role_is_enforced(client, monkeypatch) -> None:
    """Review-8 finding: a generic reviewer must not approve an item whose
    risk profile reserves approval for a stronger role."""
    import servers.api as api_mod
    from fastapi import HTTPException

    item_id = client.post("/v1/execution/assess", json=PROD_WRITE).json()["review_item_id"]

    def real_enforce(**kwargs):
        # Simulate the tenant profile: high risk requires domain_expert.
        if kwargs["role"] not in {"domain_expert", "senior_authority", "admin"}:
            raise HTTPException(status_code=403, detail="approval role insufficient")

    monkeypatch.setattr(api_mod, "_enforce_review_approval_role", real_enforce)
    # Authenticated as generic "reviewer" (fixture) -> refused.
    r = client.post("/v1/execution/approve", json={"item_id": item_id})
    assert r.status_code == 403
    # Stronger role passes.
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "domain_expert"))
    assert client.post("/v1/execution/approve", json={"item_id": item_id}).status_code == 200


def test_approve_passes_item_risk_tier_to_profile_resolution(client, monkeypatch) -> None:
    """The item's own observation risk tier drives profile selection."""
    import servers.api as api_mod

    seen: dict = {}
    original = api_mod._resolve_tenant_policy_profile

    def spy(tenant, risk_tier):
        seen["risk_tier"] = risk_tier
        return original(tenant, risk_tier)

    monkeypatch.setattr(api_mod, "_resolve_tenant_policy_profile", spy)
    item_id = client.post("/v1/execution/assess", json=PROD_WRITE).json()["review_item_id"]
    client.post("/v1/execution/approve", json={"item_id": item_id})
    assert seen["risk_tier"] == "high"


def test_sqlite_chain_is_durable_atomic_and_fork_free(tmp_path) -> None:
    """REM-034 durable adapter: same contract, survives 'restart', and 40
    racing appends across two connections-per-thread serialise fork-free."""
    from remora.governance.tenant_chain import SQLiteTenantChain

    db = str(tmp_path / "chain.db")
    chain = SQLiteTenantChain(db)
    chain.append("acme", {"event": "a"})
    chain.append("acme", {"event": "b"})
    # Restart: a NEW adapter instance sees the same verified chain.
    reopened = SQLiteTenantChain(db)
    assert len(reopened.entries("acme")) == 2
    ok, problems = reopened.verify("acme")
    assert ok, problems
    # Concurrency: BEGIN IMMEDIATE serialises predecessor read + insert.
    import threading
    from concurrent.futures import ThreadPoolExecutor

    barrier = threading.Barrier(8)

    def hammer(i: int) -> None:
        local = SQLiteTenantChain(db)
        barrier.wait(timeout=10)
        for j in range(5):
            local.append("acme", {"event": f"{i}-{j}"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        for f in [pool.submit(hammer, i) for i in range(8)]:
            f.result(timeout=60)
    final = SQLiteTenantChain(db)
    entries = final.entries("acme")
    assert len(entries) == 42
    assert [e.sequence_no for e in entries] == list(range(42))
    ok, problems = final.verify("acme")
    assert ok, problems


def test_execution_api_uses_durable_chain_when_configured(tmp_path, monkeypatch) -> None:
    import servers.execution_api as exec_mod
    from remora.governance.tenant_chain import SQLiteTenantChain

    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "exec.db"))
    chain = exec_mod._build_chain()
    assert isinstance(chain, SQLiteTenantChain)
    monkeypatch.delenv("REMORA_CHAIN_DB")
    assert isinstance(exec_mod._build_chain(), TenantAuditChain)


@pytest.mark.skipif("not __import__('os').environ.get('REMORA_PG_DSN')",
                    reason="REMORA_PG_DSN not set — Postgres contract test skipped")
def test_postgres_chain_contract() -> None:
    import os

    from remora.governance.tenant_chain import PostgresTenantChain

    chain = PostgresTenantChain(os.environ["REMORA_PG_DSN"])
    entry = chain.append("contract-test", {"event": "pg"})
    assert entry.sequence_no >= 0
    ok, problems = chain.verify("contract-test")
    assert ok, problems
