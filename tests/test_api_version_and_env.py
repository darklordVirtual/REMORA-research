# Author: Stian Skogbrott
# License: Apache-2.0
"""Tests for api.py version derivation and REMORA_ENV standardisation.

Item 6: api.py version must match pyproject.toml (0.8.0), derived from
        importlib.metadata rather than hardcoded.

Item 8: _is_production_mode() and auth have inconsistent REMORA_ENV defaults.
        A single canonical helper must be used everywhere.

All tests RED initially.
"""
from __future__ import annotations

import importlib.metadata
import os
from unittest.mock import patch

import pytest

# FastAPI is an optional dependency ([api] extra). Skip the whole module when it
# is absent, matching the convention in tests/test_api_server.py.
pytest.importorskip("fastapi")


class TestApiVersionMatchesPackage:

    def test_fastapi_app_version_matches_package_metadata(self):
        """FastAPI app.version must equal importlib.metadata version for 'remora'."""
        import servers.api as api_module
        pkg_version = importlib.metadata.version("remora")
        assert api_module.app.version == pkg_version, (
            f"app.version={api_module.app.version!r} does not match "
            f"package version={pkg_version!r}"
        )

    def test_health_endpoint_returns_package_version(self):
        """GET /v1/health version field must equal package metadata version."""
        from fastapi.testclient import TestClient
        from servers.api import app
        client = TestClient(app)
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        pkg_version = importlib.metadata.version("remora")
        assert resp.json().get("version") == pkg_version, (
            f"health.version={resp.json().get('version')!r} != package {pkg_version!r}"
        )


class TestRemoteEnvModeConsistency:
    """_is_production_mode() and auth must use the same default for REMORA_ENV."""

    def test_no_env_var_defaults_to_development_mode(self):
        """With REMORA_ENV unset, the system must behave as development mode."""
        import servers.api as api_module
        with patch.dict(os.environ, {}, clear=False):
            env_backup = os.environ.pop("REMORA_ENV", None)
            try:
                result = api_module._is_production_mode()
                # Default must be development (False)
                assert result is False, (
                    "Without REMORA_ENV set, _is_production_mode() must return False "
                    "(development default)"
                )
            finally:
                if env_backup is not None:
                    os.environ["REMORA_ENV"] = env_backup

    def test_production_string_triggers_production_mode(self):
        import servers.api as api_module
        for val in ("production", "prod", "PRODUCTION", "PROD"):
            with patch.dict(os.environ, {"REMORA_ENV": val}):
                assert api_module._is_production_mode() is True, (
                    f"REMORA_ENV={val!r} should trigger production mode"
                )

    def test_development_string_gives_development_mode(self):
        import servers.api as api_module
        for val in ("development", "dev", "DEVELOPMENT"):
            with patch.dict(os.environ, {"REMORA_ENV": val}):
                assert api_module._is_production_mode() is False, (
                    f"REMORA_ENV={val!r} should give development mode"
                )

    def test_auth_and_is_production_mode_agree_on_unset_env(self):
        """The auth function must also treat unset REMORA_ENV as development.

        The audit found that _is_production_mode() defaulted to 'development'
        but _authenticate() defaulted to 'production' — contradictory behavior.
        After the fix both must agree: unset = development.
        """
        import servers.api as api_module
        from fastapi import Request

        env_backup = os.environ.pop("REMORA_ENV", None)
        # Also remove credentials so auth hits the "no credentials" path
        token_backup = os.environ.pop("REMORA_API_BEARER_TOKEN", None)
        try:
            # With no env and no credentials, auth must NOT raise 500
            # (it should use dev fallback and return "default", "operator")
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/v1/assess",
                "query_string": b"",
                "headers": [],
            }
            mock_request = Request(scope=scope)
            tenant, role = api_module._authenticate(mock_request)
            assert tenant == "default"
            assert role == "operator"
        finally:
            if env_backup is not None:
                os.environ["REMORA_ENV"] = env_backup
            if token_backup is not None:
                os.environ["REMORA_API_BEARER_TOKEN"] = token_backup

    def test_single_env_mode_helper_used_everywhere(self):
        """servers/api.py must define a single canonical env-mode helper."""
        import inspect
        import servers.api as api_module
        # Verify _get_env_mode() exists and is used by _is_production_mode()
        assert hasattr(api_module, "_get_env_mode"), (
            "servers/api.py must define _get_env_mode() as a canonical helper"
        )
        # Verify _get_env_mode is called within _is_production_mode
        src = inspect.getsource(api_module._is_production_mode)
        assert "_get_env_mode" in src, (
            "_is_production_mode() must use _get_env_mode() helper"
        )
