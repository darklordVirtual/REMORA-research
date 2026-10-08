# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Idempotency keys on assess are reserved, scoped and bound (code review of
898758f, findings 3 and 4).

Finding 3: two concurrent requests with one key both missed the cache, both
assessed, and both returned an executable grant. Finding 4: a cached answer
was returned before the assess permission was checked, and the cache was
keyed on the tenant only, so another principal's answer, token included,
came back to anyone in the tenant who sent the same key.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from remora.persistence.idempotency import (
    IdempotencyConflict,
    IdempotencyStore,
    SQLiteIdempotencyStore,
    idempotency_scope,
)


@pytest.fixture
def api_world(monkeypatch, tmp_path):
    import os

    from fastapi.testclient import TestClient

    from remora.enforcement.gate import EnforcementGate
    from remora.enforcement.lease import GovernedToolDispatcher
    from remora.enforcement.nonce_store import DurableNonceStore
    from remora.enforcement.outbox import SQLiteExecutionOutbox
    from remora.governance.tenant_chain import SQLiteTenantChain
    from remora.policy.decision_engine import RemoraDecisionEngine
    from servers import api
    from servers import execution_api as execution

    for name in tuple(os.environ):
        if name.startswith("REMORA_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "research")
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "idem-test-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "idem-test-lease-key")
    db = str(tmp_path / "idem.db")
    monkeypatch.setenv("REMORA_CHAIN_DB", db)
    monkeypatch.setattr(api, "_TOKEN_TABLE", {
        "idem-operator": ("idem-tenant", "operator"),
        "idem-operator-2": ("idem-tenant", "operator"),
        "idem-viewer": ("idem-tenant", "viewer"),
    })
    api._rate_limiter._buckets.clear()
    monkeypatch.setattr(execution, "_QUEUES", {})
    monkeypatch.setattr(execution, "_ITEM_TENANT", {})
    monkeypatch.setattr(execution, "_CHAIN", SQLiteTenantChain(db))
    monkeypatch.setattr(execution, "_GATE", EnforcementGate(
        strict=True, audience=execution.PEP_AUDIENCE, db_path=db))
    monkeypatch.setattr(execution, "_OUTBOX", SQLiteExecutionOutbox(db))
    monkeypatch.setattr(execution, "_ENGINE", RemoraDecisionEngine(
        execution_profile=True, low_consequence_accept=True))
    store = SQLiteIdempotencyStore(db)
    monkeypatch.setattr(execution, "_idempotency_store", lambda: store)
    calls: list[dict] = []
    dispatcher = GovernedToolDispatcher(
        expected_policy_bundle_hash=execution._current_policy_bundle_hash(),
        nonce_store=DurableNonceStore(db_path=db))
    dispatcher.register("read_telemetry", lambda args: calls.append(args) or {"ok": True})
    monkeypatch.setattr(execution, "_DISPATCHER", dispatcher)
    return TestClient(api.app), execution, store, calls


def _as(who):
    return {"Authorization": f"Bearer idem-{who}"}


def _proposal(**extra):
    return {"tool_name": "read_telemetry", "arguments": {"asset": "P-1"},
            "target_environment": "staging", "idempotency_key": "same-retry-key", **extra}


def test_concurrent_requests_with_one_key_mint_one_grant(api_world, monkeypatch):
    client, _execution, store, calls = api_world
    original = store._insert_raw
    both_missed = Barrier(2)
    first_two = [True, True]

    def race(tenant, key, raw):
        if first_two:  # both first attempts reach the reservation together;
            first_two.pop()  # the loser's later polls go straight through
            both_missed.wait(timeout=10)
        return original(tenant, key, raw)

    monkeypatch.setattr(store, "_insert_raw", race)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(client.post, "/v1/execution/assess",
                               json=_proposal(), headers=_as("operator"))
                   for _ in range(2)]
        replies = [future.result(timeout=30) for future in pending]
    assert [r.status_code for r in replies] == [200, 200], [r.text for r in replies]
    bodies = [r.json() for r in replies]
    assert bodies[0] == bodies[1]
    assert bodies[0]["decision"] == "accept"
    token = bodies[0]["execution_token"]
    run = client.post("/v1/execution/execute-accepted", headers=_as("operator"),
                      json={"execution_token": token, "tool_call": _proposal()})
    assert run.status_code == 200 and run.json()["tool_execution"]["executed"]
    assert len(calls) == 1


def test_a_stored_answer_still_requires_the_assess_permission(api_world):
    client, *_ = api_world
    first = client.post("/v1/execution/assess", json=_proposal(), headers=_as("operator"))
    assert first.status_code == 200 and first.json()["decision"] == "accept"
    replay = client.post("/v1/execution/assess", json=_proposal(), headers=_as("viewer"))
    assert replay.status_code == 403
    assert "execution_token" not in replay.text


def test_one_principals_key_never_answers_another_principal(api_world):
    client, *_ = api_world
    first = client.post("/v1/execution/assess", json=_proposal(), headers=_as("operator"))
    other = client.post("/v1/execution/assess", json=_proposal(), headers=_as("operator-2"))
    assert first.status_code == other.status_code == 200
    assert other.json()["proposal_id"] != first.json()["proposal_id"]
    assert other.json()["execution_token"] != first.json()["execution_token"]


def test_a_replay_returns_the_same_answer(api_world):
    client, *_ = api_world
    first = client.post("/v1/execution/assess", json=_proposal(), headers=_as("operator"))
    again = client.post("/v1/execution/assess", json=_proposal(), headers=_as("operator"))
    assert again.status_code == 200 and again.json() == first.json()


def test_the_same_key_with_a_different_request_is_a_conflict(api_world):
    client, *_ = api_world
    first = client.post("/v1/execution/assess", json=_proposal(), headers=_as("operator"))
    assert first.status_code == 200
    changed = client.post("/v1/execution/assess", headers=_as("operator"),
                          json=_proposal(arguments={"asset": "P-2"}))
    assert changed.status_code == 409
    assert "request_mismatch" in changed.json()["detail"]


def test_a_failed_assessment_releases_the_key(api_world, monkeypatch):
    client, execution, *_ = api_world
    real = execution._assess_proposal_with_loop_state
    failures = [RuntimeError("engine down")]

    def flaky(**kwargs):
        if failures:
            raise failures.pop()
        return real(**kwargs)

    monkeypatch.setattr(execution, "_assess_proposal_with_loop_state", flaky)
    with pytest.raises(RuntimeError):
        client.post("/v1/execution/assess", json=_proposal(), headers=_as("operator"))
    retry = client.post("/v1/execution/assess", json=_proposal(), headers=_as("operator"))
    assert retry.status_code == 200 and retry.json()["decision"] == "accept"


# ── the store's reservation, on both backends ─────────────────────────────────

@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return IdempotencyStore()
    return SQLiteIdempotencyStore(str(tmp_path / "s.db"))


def test_the_first_claim_owns_and_the_next_sees_the_answer(store):
    claim = store.claim("t", "k", "fp")
    assert claim.owned and claim.response is None
    assert store.complete(claim, {"proposal_id": "p-1"}) is True
    again = store.claim("t", "k", "fp")
    assert not again.owned and again.response == {"proposal_id": "p-1"}


def test_a_held_key_is_in_progress_after_the_wait(store):
    store.claim("t", "k", "fp")
    started = time.monotonic()
    with pytest.raises(IdempotencyConflict) as refused:
        store.claim("t", "k", "fp", wait_s=0.2, poll_s=0.02)
    assert refused.value.reason == "in_progress"
    assert time.monotonic() - started >= 0.2


def test_a_held_key_with_another_fingerprint_is_a_mismatch(store):
    store.claim("t", "k", "fp")
    with pytest.raises(IdempotencyConflict) as refused:
        store.claim("t", "k", "other", wait_s=0)
    assert refused.value.reason == "request_mismatch"


def test_a_released_key_can_be_claimed_again(store):
    store.release(store.claim("t", "k", "fp"))
    assert store.claim("t", "k", "fp", wait_s=0).owned


def test_a_stale_reservation_is_taken_over_and_the_old_owner_cannot_complete(store):
    stale = store.claim("t", "k", "fp")
    time.sleep(0.05)
    fresh = store.claim("t", "k", "fp", stale_after_s=0.01)
    assert fresh.owned
    assert store.complete(stale, {"proposal_id": "late"}) is False
    assert store.complete(fresh, {"proposal_id": "p-2"}) is True
    assert store.claim("t", "k", "fp").response == {"proposal_id": "p-2"}


def test_a_waiting_claim_returns_the_owners_answer(store):
    owner = store.claim("t", "k", "fp")
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(store.claim, "t", "k", "fp", wait_s=5, poll_s=0.01)
        time.sleep(0.05)
        store.complete(owner, {"proposal_id": "p-1"})
        assert waiting.result(timeout=5).response == {"proposal_id": "p-1"}


def test_the_scope_names_the_principal_and_ignores_the_key_in_the_body():
    a, fp_a = idempotency_scope("alice", "k", {"tool": "x", "arguments": {"n": 1}})
    b, fp_b = idempotency_scope("bob", "k", {"arguments": {"n": 1}, "tool": "x"})
    assert a != b and a.endswith(":k")
    assert fp_a == fp_b
    assert idempotency_scope("alice", "k", {"tool": "y"})[1] != fp_a


def test_the_research_surface_claims_per_principal_and_request(tmp_path, monkeypatch):
    from servers import api

    store = SQLiteIdempotencyStore(str(tmp_path / "r.db"))
    monkeypatch.setattr(api, "_assess_idempotency_store", lambda: store)
    req = api.AssessRequest(question="q", idempotency_key="k" * 8)
    owner = api._assess_idempotency_claim("acme", "alice", req)
    assert owner.owned
    assert api._assess_idempotency_claim("acme", "bob", req).owned
    changed = api.AssessRequest(question="other", idempotency_key="k" * 8)
    store.complete(owner, {"decision": "verify"})
    with pytest.raises(api.HTTPException) as refused:
        api._assess_idempotency_claim("acme", "alice", changed)
    assert refused.value.status_code == 409
