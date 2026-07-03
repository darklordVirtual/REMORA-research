"""Cross-tenant isolation and least-privilege RBAC (REM-023 steps 8 & 9).

These tests close the two REM-023 design-document criteria that were open at
REM-022's closure:
  - step 8: no cross-tenant data leakage via the API;
  - step 9: admin has an explicit capability set, not a "*" wildcard.

They run in multi-tenant mode (REMORA_API_TOKENS), where the token binds the
role and tenant — the authoritative auth mode. The header-role escalation
regression lives in tests/test_api_server.py; this file focuses on tenant data
isolation and the wildcard removal.
"""
from __future__ import annotations

import importlib
import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # type: ignore[import-not-found]


def _api(monkeypatch, tokens: dict):
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("REMORA_API_ALLOW_MOCK_ORACLES", raising=False)
    monkeypatch.delenv("REMORA_API_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("REMORA_API_TOKENS", json.dumps(tokens))
    import servers.api as api

    return importlib.reload(api)


TOKENS = {
    "acme-op": {"tenant": "acme", "role": "operator"},
    "globex-op": {"tenant": "globex", "role": "operator"},
    "acme-admin": {"tenant": "acme", "role": "admin"},
}


def _assess(client, token: str) -> str:
    resp = client.post(
        "/v1/assess",
        json={"question": "deploy hotfix?", "risk_tier": "medium"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["request_id"]


# ── Step 8: cross-tenant data isolation ─────────────────────────────────────

def test_tenant_cannot_read_another_tenants_envelope(monkeypatch) -> None:
    api = _api(monkeypatch, TOKENS)
    client = TestClient(api.app)

    req_id = _assess(client, "acme-op")

    # acme can read its own envelope
    own = client.get(f"/v1/envelope/{req_id}",
                     headers={"Authorization": "Bearer acme-op"})
    assert own.status_code == 200
    assert own.json()["tenant_id"] == "acme"

    # globex must NOT see acme's envelope — 404, not the data
    other = client.get(f"/v1/envelope/{req_id}",
                       headers={"Authorization": "Bearer globex-op"})
    assert other.status_code == 404
    assert "acme" not in other.text


def test_tenant_cannot_attach_evidence_to_another_tenants_request(monkeypatch) -> None:
    api = _api(monkeypatch, TOKENS)
    client = TestClient(api.app)

    req_id = _assess(client, "acme-op")
    resp = client.post(
        "/v1/evidence",
        json={"request_id": req_id, "evidence_type": "note",
              "payload": {"x": 1}, "submitted_by": "mallory"},
        headers={"Authorization": "Bearer globex-op"},
    )
    # globex sees no such request in its own tenant scope → 404
    assert resp.status_code == 404


def test_header_tenant_cannot_override_token_tenant(monkeypatch) -> None:
    """X-Remora-Tenant must not redirect a read into another tenant's data."""
    api = _api(monkeypatch, TOKENS)
    client = TestClient(api.app)

    req_id = _assess(client, "acme-op")
    resp = client.get(
        f"/v1/envelope/{req_id}",
        headers={"Authorization": "Bearer globex-op", "X-Remora-Tenant": "acme"},
    )
    assert resp.status_code == 404  # token tenant (globex) is authoritative


# ── Step 9: admin least-privilege (no wildcard) ─────────────────────────────

def test_admin_has_explicit_capability_set_not_wildcard(monkeypatch) -> None:
    api = _api(monkeypatch, TOKENS)
    assert "*" not in api._BUILTIN_ROLE_PERMISSIONS["admin"], "admin must not hold a wildcard"
    assert api._BUILTIN_ROLE_PERMISSIONS["admin"] == set(api._ALL_CAPABILITIES)


def test_all_capabilities_are_covered_by_admin(monkeypatch) -> None:
    """Every capability actually enforced by an endpoint must be in the
    canonical vocabulary (so admin — enumerated from it — is not silently
    missing a capability a future endpoint introduces)."""
    api = _api(monkeypatch, TOKENS)
    import re
    from pathlib import Path

    src = (Path(api.__file__)).read_text(encoding="utf-8")
    enforced = set(re.findall(r'_require_tenant_capability\(role, tenant_id, "([a-z_]+)"\)', src))
    assert enforced, "no capability calls found — test needs updating"
    missing = enforced - set(api._ALL_CAPABILITIES)
    assert not missing, f"capabilities enforced but absent from _ALL_CAPABILITIES: {missing}"


def test_admin_can_perform_every_capability(monkeypatch) -> None:
    api = _api(monkeypatch, TOKENS)
    for cap in api._ALL_CAPABILITIES:
        # should not raise
        assert api._require_tenant_capability("admin", "acme", cap) == "admin"


def test_injected_star_capability_grants_nothing(monkeypatch) -> None:
    """A config that injects '*' as a role capability must not act as a
    wildcard (the '*' in permissions branch was removed)."""
    api = _api(monkeypatch, TOKENS)
    monkeypatch.setattr(api, "_role_permissions_map", lambda: {"weird": {"*"}})
    with pytest.raises(api.HTTPException) as exc:
        api._require_tenant_capability("weird", "acme", "assess")
    assert exc.value.status_code == 403
