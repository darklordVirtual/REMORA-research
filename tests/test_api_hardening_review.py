# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Review findings on servers/api.py: body-size limit, /v1/metrics scope,
untrusted role header outside development, development-mode startup warning."""
from __future__ import annotations

import importlib
import json
import logging

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _reload(monkeypatch, *, env="development", tokens=None, bearer=None, **extra):
    monkeypatch.setenv("REMORA_ENV", env)
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("REMORA_API_ALLOW_MOCK_ORACLES", raising=False)
    for k, v in extra.items():
        monkeypatch.setenv(k, v)
    if tokens is None:
        monkeypatch.delenv("REMORA_API_TOKENS", raising=False)
    else:
        monkeypatch.setenv("REMORA_API_TOKENS", json.dumps(tokens))
    if bearer is None:
        monkeypatch.delenv("REMORA_API_BEARER_TOKEN", raising=False)
    else:
        monkeypatch.setenv("REMORA_API_BEARER_TOKEN", bearer)
    import servers.api as api

    return importlib.reload(api)


# ---- 1. body-size limit -------------------------------------------------

def test_oversized_body_is_rejected_with_413(monkeypatch):
    api = _reload(monkeypatch, REMORA_MAX_REQUEST_BYTES="2048")
    client = TestClient(api.app)
    big = {"request_id": "req-12345678", "evidence_type": "log",
           "payload": {"blob": "x" * 10_000}}
    resp = client.post("/v1/evidence", json=big)
    assert resp.status_code == 413, resp.text


def test_oversized_chunked_body_is_rejected_with_413(monkeypatch):
    api = _reload(monkeypatch, REMORA_MAX_REQUEST_BYTES="2048")
    client = TestClient(api.app)

    def gen():
        for _ in range(20):
            yield b'{"a":"' + b"x" * 500 + b'"}'

    resp = client.post("/v1/evidence", content=gen(),
                       headers={"content-type": "application/json"})
    assert resp.status_code == 413, resp.text


def test_normal_body_still_accepted(monkeypatch):
    api = _reload(monkeypatch, REMORA_MAX_REQUEST_BYTES="2048")
    client = TestClient(api.app)
    resp = client.post("/v1/assess", json={"question": "Should we patch?",
                                           "risk_tier": "medium"})
    assert resp.status_code == 200, resp.text


def test_default_limit_is_finite_and_generous(monkeypatch):
    monkeypatch.delenv("REMORA_MAX_REQUEST_BYTES", raising=False)
    api = _reload(monkeypatch)
    assert 64 * 1024 <= api._max_request_bytes() <= 16 * 1024 * 1024


# ---- 2. /v1/metrics scope -----------------------------------------------

def test_metrics_global_view_denied_to_non_admin_in_multitenant(monkeypatch):
    api = _reload(monkeypatch, tokens={
        "a-op": {"tenant": "a", "role": "operator"},
        "a-view": {"tenant": "a", "role": "viewer"},
        "b-admin": {"tenant": "b", "role": "admin"},
    })
    client = TestClient(api.app)
    assert client.get("/v1/metrics", headers={"Authorization": "Bearer a-op"}).status_code == 403
    assert client.get("/v1/metrics", headers={"Authorization": "Bearer a-view"}).status_code == 403
    assert client.get("/v1/metrics", headers={"Authorization": "Bearer b-admin"}).status_code == 200


def test_metrics_single_tenant_viewer_still_allowed(monkeypatch):
    api = _reload(monkeypatch, tokens={
        "v": {"tenant": "only", "role": "viewer"},
        "o": {"tenant": "only", "role": "operator"},
    })
    client = TestClient(api.app)
    assert client.get("/v1/metrics", headers={"Authorization": "Bearer v"}).status_code == 200


# ---- 4. role header outside development ---------------------------------

@pytest.mark.parametrize("env", ["staging", "qa", "test", ""])
def test_non_dev_env_ignores_role_header_in_single_token_mode(monkeypatch, env):
    api = _reload(monkeypatch, env=env, bearer="tok")
    req = _FakeRequest({"Authorization": "Bearer tok", "X-Remora-Role": "admin"})
    assert api._authenticate(req) == ("default", "operator")


def test_development_env_keeps_role_header(monkeypatch):
    api = _reload(monkeypatch, env="development", bearer="tok")
    req = _FakeRequest({"Authorization": "Bearer tok", "X-Remora-Role": "admin"})
    assert api._authenticate(req) == ("default", "admin")


class _FakeRequest:
    def __init__(self, headers):
        self.headers = headers


def test_development_mode_logs_startup_warning(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="remora.api"):
        _reload(monkeypatch, env="development")
    assert any("development mode" in r.getMessage().lower() for r in caplog.records)


def test_staging_does_not_log_development_warning(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="remora.api"):
        _reload(monkeypatch, env="staging", bearer="tok")
    assert not any("development mode" in r.getMessage().lower() for r in caplog.records)
