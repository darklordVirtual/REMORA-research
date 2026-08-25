# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Issue #296 slice 1: cross-surface concerns are shared, not duplicated.

Rate limiting guarded only /v1/assess and idempotency keys existed only on
/v1/execution/* — each surface had half of a concern that belongs to both.
These tests pin the sharing from both sides, and pin the isolation rules
that make the sharing safe: separate budgets per surface, namespaced
idempotency keys, and reads staying unlimited.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from servers import api as api_mod


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    monkeypatch.setattr(api_mod, "_rate_limiter", api_mod._InMemoryRateLimiter())


# ── rate limiting on the execution surface ─────────────────────────────────


def test_execution_posts_are_limited_per_tenant(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_EXECUTION_RATE_LIMIT_PER_MIN", "2")
    api_mod._enforce_execution_rate_limit("acme")
    api_mod._enforce_execution_rate_limit("acme")
    with pytest.raises(HTTPException) as caught:
        api_mod._enforce_execution_rate_limit("acme")
    assert caught.value.status_code == 429
    assert caught.value.headers["Retry-After"] == "60"


def test_tenants_have_separate_buckets(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_EXECUTION_RATE_LIMIT_PER_MIN", "1")
    api_mod._enforce_execution_rate_limit("acme")
    # A different tenant is not starved by acme's spend.
    api_mod._enforce_execution_rate_limit("globex")


def test_the_two_surfaces_keep_separate_budgets(monkeypatch) -> None:
    """Exhausting the research surface must not starve enforcement."""
    monkeypatch.setenv("REMORA_ASSESS_RATE_LIMIT_PER_MIN", "1")
    monkeypatch.setenv("REMORA_EXECUTION_RATE_LIMIT_PER_MIN", "5")
    assert api_mod._rate_limiter.is_allowed("assess:acme") is True
    assert api_mod._rate_limiter.is_allowed("assess:acme") is False
    # Execution still has budget: different key, different env var.
    api_mod._enforce_execution_rate_limit("acme")


def test_zero_disables_the_execution_limit(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_EXECUTION_RATE_LIMIT_PER_MIN", "0")
    for _ in range(50):
        api_mod._enforce_execution_rate_limit("acme")


def test_the_auth_choke_point_limits_posts_and_not_reads(monkeypatch) -> None:
    """Applied in _auth so a new POST route cannot forget it; GETs stay
    unlimited because reads have no side effects to protect."""
    from servers import execution_api as exec_mod

    monkeypatch.setenv("REMORA_EXECUTION_RATE_LIMIT_PER_MIN", "1")
    monkeypatch.setattr(api_mod, "_authenticate", lambda r: ("acme", "operator"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda r: "p-1")

    post = SimpleNamespace(method="POST")
    get = SimpleNamespace(method="GET")
    assert exec_mod._auth(post) == ("acme", "operator", "p-1")
    with pytest.raises(HTTPException) as caught:
        exec_mod._auth(post)
    assert caught.value.status_code == 429
    # Reads keep working with the POST budget exhausted.
    for _ in range(5):
        assert exec_mod._auth(get) == ("acme", "operator", "p-1")


# ── idempotency on the assess surface ──────────────────────────────────────


@pytest.fixture()
def fresh_assess_store(monkeypatch, tmp_path):
    monkeypatch.delenv("REMORA_PG_DSN", raising=False)
    monkeypatch.delenv("REMORA_CHAIN_DB", raising=False)
    api_mod._reset_assess_idempotency_store()
    yield
    api_mod._reset_assess_idempotency_store()


def test_assess_keys_roundtrip_per_tenant(fresh_assess_store) -> None:
    api_mod._assess_idempotency_put("acme", "key-12345678", {"decision": "verify"})
    assert api_mod._assess_idempotency_get("acme", "key-12345678") == {
        "decision": "verify"
    }
    assert api_mod._assess_idempotency_get("globex", "key-12345678") is None


def test_assess_keys_are_namespaced_away_from_the_execution_surface(
    fresh_assess_store,
) -> None:
    """A key replayed across surfaces must never return the other surface's
    response. The assess store prefixes 'assess:', so even a shared durable
    backend keeps the two response spaces disjoint."""
    api_mod._assess_idempotency_put("acme", "key-12345678", {"surface": "assess"})
    store = api_mod._assess_idempotency_store()
    # The raw key, as the execution surface would use it, resolves nothing.
    assert store.get("acme", "key-12345678") is None
    assert store.get("acme", "assess:key-12345678") == {"surface": "assess"}


def test_assess_request_accepts_the_key_with_execution_bounds() -> None:
    req = api_mod.AssessRequest(question="q", idempotency_key="k" * 8)
    assert req.idempotency_key == "k" * 8
    with pytest.raises(Exception):
        api_mod.AssessRequest(question="q", idempotency_key="short")
