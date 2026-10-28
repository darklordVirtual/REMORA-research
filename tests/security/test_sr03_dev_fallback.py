"""SR-03 / SEC-05: the no-credential development fallback must be opt-in and
read-only.

On HEAD, a development server with neither REMORA_API_TOKENS nor
REMORA_API_BEARER_TOKEN authenticates every request as ("default",
"operator") without reading any header, and operator includes `execute`.
Combined with the reference compose publishing 8000 on all interfaces, a
plain `docker compose up` exposed the enforcing execute path with no
credential.

The rule: no credentials without REMORA_ALLOW_UNAUTHENTICATED_DEV=1 is a
500 misconfiguration on every governed route; with the opt-in the fallback
identity is ("default", "viewer") — read-only, no execute.
"""

from __future__ import annotations

import importlib

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # type: ignore[import-not-found]  # noqa: E402


def _load_no_credential_api(monkeypatch: pytest.MonkeyPatch, *, opt_in: bool):
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("REMORA_API_ALLOW_MOCK_ORACLES", raising=False)
    monkeypatch.delenv("REMORA_API_TOKENS", raising=False)
    monkeypatch.delenv("REMORA_API_BEARER_TOKEN", raising=False)
    if opt_in:
        monkeypatch.setenv("REMORA_ALLOW_UNAUTHENTICATED_DEV", "1")
    else:
        monkeypatch.delenv("REMORA_ALLOW_UNAUTHENTICATED_DEV", raising=False)
    import servers.api as api

    return importlib.reload(api)


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/v1/assess"),
        ("GET", "/v1/metrics"),
        ("GET", "/metrics"),
        ("GET", "/v1/audit/chain/verify"),
    ],
)
def test_no_credentials_without_opt_in_refuses(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    api = _load_no_credential_api(monkeypatch, opt_in=False)
    client = TestClient(api.app, raise_server_exceptions=False)

    resp = client.request(method, path, json={"question": "x"} if method == "POST" else None)
    assert resp.status_code in (401, 500), (
        f"{method} {path} without credentials and without the opt-in must be "
        f"refused, got {resp.status_code}"
    )


def test_opt_in_fallback_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the explicit opt-in the fallback identity is viewer: read passes,
    anything beyond read (assess, execute) does not."""
    api = _load_no_credential_api(monkeypatch, opt_in=True)
    client = TestClient(api.app, raise_server_exceptions=False)

    assert client.get("/v1/metrics").status_code == 200

    assess = client.post("/v1/assess", json={"question": "deploy?", "risk_tier": "high"})
    assert assess.status_code == 403, (
        "the unauthenticated fallback must not carry the assess capability"
    )

    execute = client.post(
        "/v1/execution/assess",
        json={"tool_name": "x", "arguments": {}},
    )
    assert execute.status_code in (401, 403), (
        "the unauthenticated fallback must never reach the execution surface"
    )


def test_credentials_still_work_without_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opt-in gate applies only to the no-credential fallback; a real
    token keeps working without it."""
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "real-token")
    monkeypatch.delenv("REMORA_ALLOW_UNAUTHENTICATED_DEV", raising=False)
    import servers.api as api

    api = importlib.reload(api)
    client = TestClient(api.app, raise_server_exceptions=False)

    resp = client.post(
        "/v1/assess",
        json={"question": "deploy?", "risk_tier": "high"},
        headers={"Authorization": "Bearer real-token"},
    )
    assert resp.status_code == 200
