# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Swagger must let an operator authenticate.

The API authenticates with a bearer token on every governed endpoint, but the
OpenAPI document declared no security scheme at all. Swagger therefore showed
no "Authorize" button, so every protected call from the UI returned 401 with
no way to fix it — the interactive docs were unusable for the thing they
exist for. ReDoc has the same gap: it renders whatever the schema declares,
and the schema declared nothing about auth.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import servers.api as api_mod  # noqa: E402

client = TestClient(api_mod.app)


def _openapi() -> dict:
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    return resp.json()


def test_bearer_security_scheme_is_declared() -> None:
    schemes = _openapi().get("components", {}).get("securitySchemes", {})
    assert schemes, "OpenAPI declares no securitySchemes — Swagger shows no Authorize button"
    bearer = next(
        (s for s in schemes.values()
         if s.get("type") == "http" and s.get("scheme") == "bearer"),
        None,
    )
    assert bearer is not None, f"no HTTP bearer scheme among {list(schemes)}"


def test_security_scheme_explains_where_the_token_comes_from() -> None:
    """An operator reading the docs must learn how to obtain a token, not just
    that one is required."""
    schemes = _openapi()["components"]["securitySchemes"]
    described = " ".join(str(s.get("description", "")) for s in schemes.values())
    assert "REMORA_API_TOKENS" in described, (
        "the scheme description must name the env var that mints tokens"
    )


def test_security_is_applied_to_governed_endpoints() -> None:
    spec = _openapi()
    for path in ("/v1/assess", "/v1/execution/assess", "/v1/execution/execute"):
        op = spec["paths"][path]["post"]
        applied = op.get("security") or spec.get("security")
        assert applied, f"{path} declares no security requirement"


def test_open_endpoints_stay_reachable_without_a_token() -> None:
    """Health and the index must not require auth: a liveness probe that needs
    a credential is not a liveness probe."""
    assert client.get("/v1/health").status_code == 200
    assert client.get("/").status_code == 200
