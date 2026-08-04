import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient


MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy/ot-pilot/console/app.py"
SPEC = importlib.util.spec_from_file_location("remora_console_app", MODULE_PATH)
console_app = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(console_app)


class DummyResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class DummyAsyncClient:
    def __init__(self, *args, **kwargs):
        self.calls: list[tuple[str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, headers=None):
        self.calls.append((url, headers))
        if url.endswith("/v1/health"):
            return DummyResponse(200, {"status": "ok", "version": "0.10.0"})
        if url.endswith("/v1/policy/version"):
            return DummyResponse(200, {"runtime_mode": "development", "policy_hash": "abc123"})
        if url.endswith("/v1/metrics"):
            return DummyResponse(200, {"assess_total": 7, "decision_counts": {"verify": 4, "escalate": 3}})
        if url.endswith("/v1/audit/chain/verify"):
            return DummyResponse(200, {"chain_valid": True, "records_checked": 3})
        raise AssertionError(f"unexpected URL: {url}")


def test_diagnostics_endpoint_collects_runtime_insights(monkeypatch):
    monkeypatch.setattr(console_app.httpx, "AsyncClient", DummyAsyncClient)
    client = TestClient(console_app.app)

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["health"]["status"] == "ok"
    assert payload["policy"]["runtime_mode"] == "development"
    assert payload["metrics"]["assess_total"] == 7
    assert payload["chain"]["chain_valid"] is True
    assert payload["summary"]["ready"] is True
