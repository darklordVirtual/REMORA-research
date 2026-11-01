"""SR-05 / SEC-04: the Prometheus /metrics endpoint must enforce the same
multi-tenant admin check as /v1/metrics.

Both endpoints serve the same process-global counters. On HEAD, /metrics
calls only _authenticate, so any tenant's viewer token reads every tenant's
decision and refusal volumes. The admin check that /v1/metrics applies must
cover both surfaces.
"""

from __future__ import annotations

import importlib
import json as _json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # type: ignore[import-not-found]  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_api_configuration(monkeypatch: pytest.MonkeyPatch):
    """Do not leave the test token table active for later API modules."""
    yield
    monkeypatch.undo()
    import servers.api as api

    importlib.reload(api)


def _load_multitenant_api(monkeypatch: pytest.MonkeyPatch, tokens: dict):
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("REMORA_API_ALLOW_MOCK_ORACLES", raising=False)
    monkeypatch.delenv("REMORA_API_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("REMORA_PROMETHEUS_PUBLIC", raising=False)
    monkeypatch.setenv("REMORA_API_TOKENS", _json.dumps(tokens))
    import servers.api as api

    return importlib.reload(api)


_TOKENS = {
    "viewer-a": {"tenant": "acme", "role": "viewer"},
    "admin-a": {"tenant": "acme", "role": "admin"},
    "viewer-b": {"tenant": "globex", "role": "viewer"},
}


@pytest.mark.parametrize("path", ["/metrics", "/v1/metrics"])
def test_multi_tenant_metrics_require_admin(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    api = _load_multitenant_api(monkeypatch, _TOKENS)
    client = TestClient(api.app)

    viewer = client.get(path, headers={"Authorization": "Bearer viewer-a"})
    assert viewer.status_code == 403, (
        f"{path}: a viewer token read process-global metrics across tenants"
    )

    admin = client.get(path, headers={"Authorization": "Bearer admin-a"})
    assert admin.status_code == 200

    anon = client.get(path)
    assert anon.status_code in (401, 403)


def test_metrics_single_tenant_keeps_read_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single-tenant deployment has no cross-tenant leak; viewer keeps read."""
    api = _load_multitenant_api(
        monkeypatch, {"viewer-a": {"tenant": "acme", "role": "viewer"}}
    )
    client = TestClient(api.app)

    for path in ("/metrics", "/v1/metrics"):
        resp = client.get(path, headers={"Authorization": "Bearer viewer-a"})
        assert resp.status_code == 200


def test_prometheus_public_flag_still_opens_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The explicit REMORA_PROMETHEUS_PUBLIC deployment opt-out is unchanged."""
    api = _load_multitenant_api(monkeypatch, _TOKENS)
    # Read per request by the handler; set after the loader's env reset.
    monkeypatch.setenv("REMORA_PROMETHEUS_PUBLIC", "1")
    client = TestClient(api.app)

    assert client.get("/metrics").status_code == 200
    # The JSON surface stays governed regardless of the Prometheus opt-out.
    assert client.get("/v1/metrics").status_code in (401, 403)
