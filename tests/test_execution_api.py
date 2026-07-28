# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REM-034/035 acceptance: atomic tenant chain + end-to-end execution API."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("fastapi")
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
    exec_mod._reset_tool_dispatcher()
    return TestClient(api_mod.app)


# Issue #34 (trust boundary): the payloads deliberately KEEP the legacy
# client-asserted trust fields (trust_score/phase/evidence_*/risk_tier/...)
# to prove the API now ignores them — the request is a PROPOSAL, all
# authoritative signals are server-side.
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


def test_client_asserted_trust_cannot_buy_accept(client) -> None:
    """Issue #34: the pre-fix happy path — a client claiming ordered phase,
    trust 0.92, high-confidence evidence and schema_valid — must NOT yield
    ACCEPT. With no server-side signals, a low-risk read falls to the safe
    default (abstain) and no execution token is issued."""
    r = client.post("/v1/execution/assess", json=LOW_READ)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "abstain", body
    assert "execution_token" not in body


def test_asserted_trust_fields_do_not_change_the_decision(client) -> None:
    """The decision must be identical with and without the legacy trust
    fields — they are ignored, not merely discounted."""
    bare = {
        "tool_name": "read_telemetry",
        "arguments": {"asset": "P-1"},
        "target_environment": "staging",
    }
    d_bare = client.post("/v1/execution/assess", json=bare).json()["decision"]
    d_asserted = client.post("/v1/execution/assess", json=LOW_READ).json()["decision"]
    assert d_bare == d_asserted


def test_request_true_cannot_elevate_unpinned_registry_fields(client) -> None:
    """Downgrade-only rule: for a tool whose registry entry does not pin
    rollback_available, a request claiming True must NOT surface as True —
    it stays unknown. (update_work_order pins True in the registry, so use
    store_artifact, which pins neither schema_valid nor rollback.)"""
    import servers.execution_api as exec_mod

    req = exec_mod.ToolCallRequest(
        tool_name="store_artifact",
        arguments={"artifact_id": "x", "content": {}},
        target_environment="staging",
        schema_valid=True,
        rollback_available=True,
    )
    obs = exec_mod._observation(req, "acme")
    assert obs.schema_valid is None
    assert obs.rollback_available is None


def test_request_false_still_downgrades(client) -> None:
    """A request may LOWER trust: rollback_available=False must override the
    registry's pinned True for update_work_order."""
    import servers.execution_api as exec_mod

    req = exec_mod.ToolCallRequest(
        tool_name="update_work_order",
        arguments={"order": "WO-1", "action": "reschedule"},
        target_environment="prod",
        rollback_available=False,
    )
    obs = exec_mod._observation(req, "acme")
    assert obs.rollback_available is False
    assert obs.trust_score is None and obs.phase is None
    assert obs.evidence_action is None and obs.evidence_confidence is None


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
    # 4. Audit chain verifies end to end and carries every transition —
    # including the intent record written BEFORE any side effect and the
    # result record written after (external review 2026-07-27).
    r = client.get("/v1/execution/audit/verify")
    assert r.json()["valid"] is True
    import servers.execution_api as exec_mod
    events = [e.payload["event"] for e in exec_mod._CHAIN.entries("acme")]
    assert events == ["assessed", "approved", "execution_authorized", "execution_result"]


def _approved_item(client, payload=PROD_WRITE) -> str:
    item_id = client.post("/v1/execution/assess", json=payload).json()["review_item_id"]
    client.post("/v1/execution/approve", json={"item_id": item_id, "approval_ttl_seconds": 900})
    return item_id


def test_execute_invokes_registered_tool_via_dispatcher(client, monkeypatch) -> None:
    """Issue #13: after gate + PEP-consume the API must actually dispatch the
    tool through the app-lifecycle GovernedToolDispatcher and report the
    real outcome — never claim execute with no side effect."""
    import tests.dispatcher_registry_fixture as reg

    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "exec-api-lease-key")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "tests.dispatcher_registry_fixture")
    reg.CALLS.clear()
    reg.RAISE["update_work_order"] = False

    item_id = _approved_item(client)
    r = client.post("/v1/execution/execute",
                    json={"item_id": item_id, "tool_call": PROD_WRITE})
    body = r.json()
    assert body["outcome"] == "execute", body
    assert body["pep"]["allowed"] is True
    assert body["tool_execution"]["executed"] is True, body
    assert body["tool_execution"]["result"]["status"] == "rescheduled"
    assert reg.CALLS == [PROD_WRITE["arguments"]]
    # The audit record carries the real execution outcome, and the item's
    # terminal state is EXECUTED only because the side effect was confirmed.
    import servers.execution_api as exec_mod
    from remora.governance.review_queue import ItemStatus
    last = exec_mod._CHAIN.entries("acme")[-1]
    assert last.payload["tool_executed"] is True
    assert exec_mod._queue("acme").item(item_id).status is ItemStatus.EXECUTED


def test_execute_without_registered_tool_is_explicitly_not_executed(client, monkeypatch) -> None:
    """Empty registry (research default): the governance verdict may be
    execute, but tool_execution must say executed=false/unknown_tool."""
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "exec-api-lease-key")
    monkeypatch.delenv("REMORA_TOOL_REGISTRY_MODULE", raising=False)

    item_id = _approved_item(client)
    body = client.post("/v1/execution/execute",
                       json={"item_id": item_id, "tool_call": PROD_WRITE}).json()
    assert body["outcome"] == "execute"
    assert body["tool_execution"]["executed"] is False
    assert body["tool_execution"]["refusal_reason"] == "unknown_tool"
    # The persisted state must NOT claim execution (review finding 1).
    import servers.execution_api as exec_mod
    from remora.governance.review_queue import ItemStatus
    assert exec_mod._queue("acme").item(item_id).status is ItemStatus.DISPATCH_REFUSED


def test_execute_without_any_signing_key_fails_closed(client, monkeypatch) -> None:
    """With no signing keys at all, the strict PEP refuses the unsigned
    grant and the dispatcher is never reached — nothing executes silently.
    (REMORA_PDP_SIGNING_KEY is the documented fallback lease key, so the
    lease path alone cannot be key-less while the PDP path is signed.)"""
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "tests.dispatcher_registry_fixture")
    import tests.dispatcher_registry_fixture as reg
    reg.CALLS.clear()
    reg.RAISE["update_work_order"] = False

    item_id = _approved_item(client)
    monkeypatch.delenv("REMORA_PDP_SIGNING_KEY", raising=False)
    monkeypatch.delenv("REMORA_LEASE_SIGNING_KEY", raising=False)
    body = client.post("/v1/execution/execute",
                       json={"item_id": item_id, "tool_call": PROD_WRITE}).json()
    assert body["tool_execution"]["executed"] is False
    assert body["tool_execution"]["refusal_reason"] == "pep_denied"
    assert body["pep"]["allowed"] is False
    assert reg.CALLS == []


def test_tool_exception_burns_nonce_and_is_reported(client, monkeypatch) -> None:
    """A tool that raises must surface as executed=false with the nonce
    burned (fail-closed), while the audit chain still records the attempt."""
    import tests.dispatcher_registry_fixture as reg

    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "exec-api-lease-key")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "tests.dispatcher_registry_fixture")
    reg.CALLS.clear()
    reg.RAISE["update_work_order"] = True
    try:
        item_id = _approved_item(client)
        r = client.post("/v1/execution/execute",
                        json={"item_id": item_id, "tool_call": PROD_WRITE})
        assert r.status_code == 200
        body = r.json()
        assert body["tool_execution"]["executed"] is False
        assert body["tool_execution"]["refusal_reason"] == "tool_failed_nonce_burned"
        import servers.execution_api as exec_mod
        from remora.governance.review_queue import ItemStatus
        last = exec_mod._CHAIN.entries("acme")[-1]
        assert last.payload["tool_executed"] is False
        assert exec_mod._queue("acme").item(item_id).status is ItemStatus.DISPATCH_FAILED
        assert client.get("/v1/execution/audit/verify").json()["valid"] is True
    finally:
        reg.RAISE["update_work_order"] = False


def _restart_client(monkeypatch, db_path: str):
    """Fresh client with SQLite-durable queue state; call again to simulate
    a process restart (all in-memory module state wiped, DB kept)."""
    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "exec-api-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_CHAIN_DB", db_path)
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role", lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = exec_mod._build_chain()
    exec_mod._GATE = exec_mod.EnforcementGate(
        strict=True, audience=exec_mod.PEP_AUDIENCE, db_path=db_path
    )
    exec_mod._reset_tool_dispatcher()
    return TestClient(api_mod.app)


def test_item_binding_survives_restart_sqlite(tmp_path, monkeypatch) -> None:
    """Review finding 2a: the item->tenant binding must persist in the SAME
    transaction as the enqueue, or a restarted process 404s a real item."""
    db = str(tmp_path / "state.db")
    client = _restart_client(monkeypatch, db)
    item_id = client.post("/v1/execution/assess", json=PROD_WRITE).json()["review_item_id"]

    client = _restart_client(monkeypatch, db)  # simulated restart
    r = client.post("/v1/execution/approve",
                    json={"item_id": item_id, "approval_ttl_seconds": 900})
    assert r.status_code == 200, r.text


def test_approval_survives_restart_sqlite(tmp_path, monkeypatch) -> None:
    """Review finding 2b: the approval must be written inside the durable
    transaction — previously it lived only in process memory and the next
    transaction's DB load silently discarded it."""
    db = str(tmp_path / "state.db")
    client = _restart_client(monkeypatch, db)
    item_id = client.post("/v1/execution/assess", json=PROD_WRITE).json()["review_item_id"]
    assert client.post("/v1/execution/approve",
                       json={"item_id": item_id, "approval_ttl_seconds": 900}
                       ).status_code == 200

    client = _restart_client(monkeypatch, db)  # simulated restart
    body = client.post("/v1/execution/execute",
                       json={"item_id": item_id, "tool_call": PROD_WRITE}).json()
    assert body["outcome"] == "execute", body
    # No registry configured: authorized but explicitly not executed.
    assert body["tool_execution"]["executed"] is False
    assert body["tool_execution"]["refusal_reason"] == "unknown_tool"


def test_approval_is_durable_in_db_mode_same_process(tmp_path, monkeypatch) -> None:
    """Review finding 2b, same-process variant: even WITHOUT a restart the
    next transaction reloads queue state from the DB, so an unpersisted
    approval would be silently discarded before execute."""
    db = str(tmp_path / "state.db")
    client = _restart_client(monkeypatch, db)
    item_id = client.post("/v1/execution/assess", json=PROD_WRITE).json()["review_item_id"]
    assert client.post("/v1/execution/approve",
                       json={"item_id": item_id, "approval_ttl_seconds": 900}
                       ).status_code == 200
    body = client.post("/v1/execution/execute",
                       json={"item_id": item_id, "tool_call": PROD_WRITE}).json()
    assert body["outcome"] == "execute", body


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


def test_sqlite_transaction_rolls_back_on_exception(tmp_path, monkeypatch) -> None:
    """N1 (external review 2026-07-28): an exception raised inside the SQLite
    db_transaction_state context must roll the transaction back — partially
    mutated queue/tenant state must never be persisted. The Postgres branch
    already had this property via conn.transaction(); the SQLite branch
    committed in `finally` even on exception."""
    import servers.execution_api as exec_mod

    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "state.db"))
    monkeypatch.delenv("REMORA_PG_DSN", raising=False)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        with exec_mod.db_transaction_state("acme"):
            exec_mod._ITEM_TENANT["item-aborted"] = "acme"
            raise _Boom()

    # The aborted mutation must be gone from the in-memory mirror
    # IMMEDIATELY (snapshot restore) — not only after a DB reload. A stale
    # in-memory key would be re-persisted by the next successful commit.
    assert "item-aborted" not in exec_mod._ITEM_TENANT

    # And a fresh context reloading persisted state from the DB must not
    # resurrect it either. Deliberately NO manual clear here: the context
    # itself must deliver the invariant.
    with exec_mod.db_transaction_state("acme"):
        assert "item-aborted" not in exec_mod._ITEM_TENANT

    # And the success path still persists: a mutation committed without an
    # exception is visible to the next context.
    with exec_mod.db_transaction_state("acme"):
        exec_mod._ITEM_TENANT["item-committed"] = "acme"
    exec_mod._ITEM_TENANT.clear()
    with exec_mod.db_transaction_state("acme"):
        assert exec_mod._ITEM_TENANT.get("item-committed") == "acme"


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


@pytest.mark.skipif("not __import__('os').environ.get('REMORA_PG_DSN')",
                    reason="REMORA_PG_DSN not set — Postgres contract test skipped")
def test_postgres_chain_signs_entries_when_key_configured(monkeypatch) -> None:
    """External review 2026-07-24, F-04: the Postgres append path never wrote
    an HMAC signature, so _verify_generic reported signature_missing for every
    entry once REMORA_AUDIT_SIGNING_KEY was set. Same contract as SQLite."""
    import os
    import uuid

    from remora.governance.tenant_chain import PostgresTenantChain

    monkeypatch.setenv("REMORA_AUDIT_SIGNING_KEY", "pg-contract-sign-key")
    chain = PostgresTenantChain(os.environ["REMORA_PG_DSN"])
    tenant = f"contract-sign-{uuid.uuid4().hex[:12]}"  # fresh, unsigned-free tenant
    entry = chain.append(tenant, {"event": "pg-signed"})
    assert entry.signature, "Postgres append must sign when the key is configured"
    ok, problems = chain.verify(tenant)
    assert ok, problems


def test_durable_chain_signature_tamper_is_detected(tmp_path, monkeypatch) -> None:
    """Review finding: _verify_generic must validate the HMAC signature, so a
    tamper-with-rehash on the durable path is caught."""
    monkeypatch.setenv("REMORA_AUDIT_SIGNING_KEY", "durable-chain-key")
    from remora.governance.tenant_chain import SQLiteTenantChain, compute_entry_hash

    db = str(tmp_path / "signed.db")
    chain = SQLiteTenantChain(db)
    chain.append("acme", {"event": "a"})
    e = chain.append("acme", {"event": "b"})
    assert chain.verify("acme")[0]
    # Attacker edits the payload AND recomputes entry_hash (defeats hash check)
    # but cannot forge the HMAC signature without the key.
    import sqlite3
    conn = sqlite3.connect(db)
    forged_payload = '{"event":"TAMPERED"}'
    forged_hash = compute_entry_hash(e.previous_hash, {"event": "TAMPERED"},
                                     "acme", e.sequence_no, e.timestamp)
    conn.execute("UPDATE tenant_chain_entry SET payload=?, entry_hash=? "
                 "WHERE tenant_id=? AND sequence_no=?",
                 (forged_payload, forged_hash, "acme", e.sequence_no))
    conn.commit(); conn.close()
    ok, problems = SQLiteTenantChain(db).verify("acme")
    assert not ok
    assert any(p.startswith("signature_mismatch") for p in problems)


def test_hash_field_boundaries_are_unambiguous() -> None:
    """Review finding: (tenant='a', seq=12) and (tenant='a1', seq=2) must not
    collide — the separator makes field boundaries injective."""
    from remora.governance.tenant_chain import compute_entry_hash
    h1 = compute_entry_hash("0" * 64, {"e": 1}, "a", 12, "2026-07-18T00:00:00")
    h2 = compute_entry_hash("0" * 64, {"e": 1}, "a1", 2, "2026-07-18T00:00:00")
    assert h1 != h2


def test_idempotency_cache_dedups_and_evicts(monkeypatch):
    """N2 (external review 2026-07-28): the idempotency store is a bounded
    LRU — hits refresh recency, overflow evicts the least-recently-used key,
    and an evicted key simply misses (assess re-runs)."""
    import servers.execution_api as exec_mod

    exec_mod._IDEMPOTENCY.clear()
    monkeypatch.setattr(exec_mod, "_IDEMPOTENCY_MAX_ENTRIES", 3)

    for i in range(3):
        exec_mod._idempotency_put(f"k{i}", {"n": i})
    assert exec_mod._idempotency_get("k0") == {"n": 0}  # refreshes k0

    exec_mod._idempotency_put("k3", {"n": 3})  # overflow: evicts k1 (LRU)
    assert exec_mod._idempotency_get("k1") is None
    assert exec_mod._idempotency_get("k0") == {"n": 0}
    assert exec_mod._idempotency_get("k3") == {"n": 3}
    assert len(exec_mod._IDEMPOTENCY) == 3
    exec_mod._IDEMPOTENCY.clear()
