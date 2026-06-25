# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for api.py security hardening.

Item 3a: Exception leakage
  - HTTP 500 responses must NOT contain raw exception messages.
  - HTTP 500 responses must include a correlation_id for log correlation.
  - Internal details (DSN, paths, module names) must not appear in 500 body.

Item 3b: Rate limiting
  - The API must configure a per-token rate limiter.
  - The rate limiter must be enabled and configurable via env var.
  - After the limit is exceeded, subsequent requests return HTTP 429.

All tests RED initially.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

# FastAPI is an optional dependency ([api] extra). Skip the whole module when it
# is absent, matching the convention in tests/test_api_server.py.
pytest.importorskip("fastapi")


# ---------------------------------------------------------------------------
# Test client setup
# ---------------------------------------------------------------------------

@pytest.fixture()
def dev_client():
    """TestClient in development mode (no auth required)."""
    from fastapi.testclient import TestClient
    with patch.dict(os.environ, {"REMORA_ENV": "development"}):
        from servers.api import app
        yield TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Item 3a: Exception leakage
# ---------------------------------------------------------------------------

class TestExceptionLeakage:

    def test_assess_500_does_not_leak_exception_message(self, dev_client):
        """Internal exception text must not appear in 500 response body."""
        secret_message = "postgresql://admin:s3cr3t@db.internal:5432/remora"

        # Force an exception containing a secret-like string
        with patch("servers.api._make_engine",
                   side_effect=RuntimeError(secret_message)):
            resp = dev_client.post(
                "/v1/assess",
                json={
                    "question": "Should I delete the prod DB?",
                    "risk_tier": "critical",
                },
            )

        assert resp.status_code == 500
        body = resp.text
        assert secret_message not in body, (
            f"Secret message leaked in 500 response: {body[:200]}"
        )

    def test_assess_500_contains_correlation_id(self, dev_client):
        """HTTP 500 from /v1/assess must include a correlation_id field."""
        with patch("servers.api._make_engine",
                   side_effect=RuntimeError("internal failure")):
            resp = dev_client.post(
                "/v1/assess",
                json={"question": "x", "risk_tier": "low"},
            )
        assert resp.status_code == 500
        # correlation_id must be in the response body (JSON or text)
        body = resp.text
        assert "correlation_id" in body, (
            f"500 response must contain correlation_id. Body: {body[:300]}"
        )

    def test_rerun_500_does_not_leak_exception_message(self, dev_client):
        """Internal exception text must not appear in /v1/rerun 500 response."""
        secret = "AWS_SECRET_KEY=AKIAIOSFODNN7EXAMPLE"
        with patch("servers.api._make_engine",
                   side_effect=RuntimeError(secret)):
            resp = dev_client.post(
                "/v1/rerun",
                json={"request_id": "req-xyz-001"},
                headers={"X-Remora-Tenant": "default"},
            )
        # /v1/rerun will 404 (no such envelope) OR 500 if engine construction fails first
        # Either way, secret must not leak
        assert secret not in resp.text, (
            f"Secret leaked in rerun response: {resp.text[:200]}"
        )

    def test_500_response_has_generic_message(self, dev_client):
        """HTTP 500 must have a generic, user-safe error message."""
        with patch("servers.api._make_engine",
                   side_effect=RuntimeError("details that must not leak")):
            resp = dev_client.post(
                "/v1/assess",
                json={"question": "x", "risk_tier": "low"},
            )
        assert resp.status_code == 500
        detail = resp.json().get("detail", "")
        assert "details that must not leak" not in detail, (
            f"Exception text leaked in detail: {detail!r}"
        )
        # Generic message must be present
        assert len(detail) > 0, "detail must not be empty"


# ---------------------------------------------------------------------------
# Item 3b: Rate limiting — configuration and integration
# ---------------------------------------------------------------------------

class TestRateLimiting:

    def test_api_has_rate_limit_configured(self):
        """The API module must have a rate limiter configured."""
        import servers.api as api_module
        # There must be a rate limiter attribute or a rate-limit dependency
        has_limiter = (
            hasattr(api_module, "_rate_limiter")
            or hasattr(api_module, "_assess_rate_limit")
            or hasattr(api_module, "limiter")
        )
        assert has_limiter, (
            "servers/api.py must configure a rate limiter "
            "(_rate_limiter, _assess_rate_limit, or limiter)"
        )

    def test_rate_limit_env_var_is_respected(self):
        """REMORA_ASSESS_RATE_LIMIT_PER_MIN must configure the limit."""
        import servers.api as api_module
        # The module must read this env var (or equivalent)
        src = open(api_module.__file__, encoding="utf-8").read()
        assert (
            "REMORA_ASSESS_RATE_LIMIT" in src
            or "REMORA_RATE_LIMIT" in src
            or "rate_limit" in src.lower()
        ), "api.py must reference a rate-limit env var or configuration"

    def test_assess_returns_429_when_rate_exceeded(self, dev_client):
        """POST /v1/assess must return 429 when the per-minute rate is exceeded."""
        # Set a very low limit for testing
        with patch.dict(os.environ, {
            "REMORA_ENV": "development",
            "REMORA_ASSESS_RATE_LIMIT_PER_MIN": "2",
        }):
            from fastapi.testclient import TestClient
            # Force module reload to pick up new rate limit
            import importlib
            import servers.api
            importlib.reload(servers.api)
            client = TestClient(servers.api.app, raise_server_exceptions=False)

            payload = {"question": "test", "risk_tier": "low"}
            responses = [client.post("/v1/assess", json=payload) for _ in range(4)]
            status_codes = [r.status_code for r in responses]

            # At least one 429 must appear after exceeding the limit
            assert 429 in status_codes, (
                f"Expected at least one 429 after exceeding rate limit. "
                f"Got status codes: {status_codes}"
            )
