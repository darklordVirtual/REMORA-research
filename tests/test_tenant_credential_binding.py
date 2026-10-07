# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-CR-003: the tenant derives from the authenticated credential.

Before: REMORA_ENV had three readings. ``staging``, a typo or an empty value
was "not development" to authentication and "not production" to the startup
guard, so single-token mode ran without the production prerequisites and
took the tenant from X-Remora-Tenant. Probe at b9ade2b: REMORA_ENV=staging,
one bearer token, header ``victim`` authenticated as ('victim', 'operator').
The review profile required no credential table either.

After: one parser (remora.profiles.deployment_environment) with two values,
unknown refused; single-token mode is development only; a token-table
credential's tenant cannot be widened by the header; strict profiles require
REMORA_API_TOKENS.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException, Request

import servers.api as api
from remora.profiles import RuntimeProfileError, deployment_environment

ROOT = Path(__file__).resolve().parents[1]
TABLE = {"tok-a": ("tenant-a", "operator"), "tok-b": ("tenant-b", "reviewer")}


def _request(*headers: tuple[bytes, bytes]) -> Request:
    return Request(scope={"type": "http", "method": "GET", "path": "/v1/execution/proposals/x",
                          "query_string": b"", "headers": list(headers)})


@pytest.fixture
def token_table(monkeypatch):
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.delenv("REMORA_API_BEARER_TOKEN", raising=False)
    monkeypatch.setattr(api, "_TOKEN_TABLE", dict(TABLE))


# -- one reading of REMORA_ENV -------------------------------------------------

@pytest.mark.parametrize("value", ["staging", "stagin", "prd", "productions", "test", "local"])
def test_an_unknown_environment_is_refused_not_read_as_either(monkeypatch, value) -> None:
    monkeypatch.setenv("REMORA_ENV", value)
    with pytest.raises(RuntimeProfileError, match="unknown"):
        deployment_environment()
    with pytest.raises(RuntimeProfileError):
        api._is_production_mode()


@pytest.mark.parametrize(("value", "expected"), [
    (None, "development"), ("", "development"), ("  ", "development"),
    ("dev", "development"), ("Development", "development"),
    ("prod", "production"), ("PRODUCTION", "production"),
])
def test_the_known_environments_keep_their_documented_meaning(monkeypatch, value, expected) -> None:
    if value is None:
        monkeypatch.delenv("REMORA_ENV", raising=False)
    else:
        monkeypatch.setenv("REMORA_ENV", value)
    assert deployment_environment() == expected


def test_an_unknown_environment_refuses_api_startup() -> None:
    env = {**os.environ, "REMORA_ENV": "staging", "PYTHONPATH": str(ROOT)}
    result = subprocess.run([sys.executable, "-c", "import servers.api"], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode != 0
    assert "REMORA_ENV='staging' is unknown" in result.stderr


def test_no_reader_of_remora_env_bypasses_the_parser() -> None:
    """Every runtime read goes through deployment_environment()."""
    offenders = []
    for folder in ("remora", "servers"):
        for path in (ROOT / folder).rglob("*.py"):
            if path.name == "profiles.py":
                continue
            text = path.read_text(encoding="utf-8")
            for needle in ('getenv("REMORA_ENV"', 'environ.get("REMORA_ENV"', 'environ["REMORA_ENV"]'):
                if needle in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {needle}")
    assert offenders == []


# -- single-token mode is development only ------------------------------------

def test_single_token_with_a_foreign_tenant_header_is_refused_outside_development(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "single")
    monkeypatch.setattr(api, "_TOKEN_TABLE", {})
    with pytest.raises(HTTPException) as exc:
        api._authenticate(_request((b"authorization", b"Bearer single"),
                                   (b"x-remora-tenant", b"victim")))
    assert exc.value.status_code == 403


def test_single_token_in_development_still_reads_the_header(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "single")
    monkeypatch.setattr(api, "_TOKEN_TABLE", {})
    assert api._authenticate(_request((b"authorization", b"Bearer single"),
                                      (b"x-remora-tenant", b"local")))[0] == "local"


# -- a credential's tenant cannot be widened ----------------------------------

def test_a_token_for_tenant_a_with_header_b_is_refused(token_table) -> None:
    with pytest.raises(HTTPException) as exc:
        api._authenticate(_request((b"authorization", b"Bearer tok-a"),
                                   (b"x-remora-tenant", b"tenant-b")))
    assert exc.value.status_code == 403


def test_a_matching_tenant_header_is_allowed(token_table) -> None:
    assert api._authenticate(_request((b"authorization", b"Bearer tok-a"),
                                      (b"x-remora-tenant", b"tenant-a"))) == ("tenant-a", "operator")


def test_a_missing_tenant_header_gives_the_credential_tenant(token_table) -> None:
    assert api._authenticate(_request((b"authorization", b"Bearer tok-b"))) == ("tenant-b", "reviewer")


# -- strict profiles require the credential table ------------------------------

def test_the_review_profile_cannot_start_in_single_token_mode(monkeypatch) -> None:
    from remora.toolcall.runtime_profile import validate_runtime_profile_prerequisites

    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "review")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "single")
    monkeypatch.delenv("REMORA_API_TOKENS", raising=False)
    with pytest.raises(RuntimeProfileError, match="REMORA_API_TOKENS"):
        validate_runtime_profile_prerequisites()
