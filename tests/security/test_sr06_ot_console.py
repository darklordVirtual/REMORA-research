"""SR-06 / SEC-06: the OT-pilot console must not let the caller pick a role.

On HEAD the console holds all three pilot tokens, lets the request body
choose `role` (so any network caller can propose AND approve, defeating the
separation of duties the pilot exists to demonstrate), serves every token
unauthenticated on GET /api/tokens, and runs the battery with no
single-flight guard.

The rule: the console holds only the viewer token; /api/call forwards the
credential the caller presents and knows no roles; /api/tokens is gone; the
battery requires the caller's tokens per request and runs single-flight.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # type: ignore[import-not-found]  # noqa: E402

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "deploy" / "ot-pilot" / "console" / "app.py"
)


def _load_console(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REMORA_API_URL", "http://api:8000")
    monkeypatch.delenv("PILOT_TOKEN_OPERATOR", raising=False)
    monkeypatch.delenv("PILOT_TOKEN_APPROVER", raising=False)
    monkeypatch.setenv("PILOT_TOKEN_VIEWER", "viewer-tok")
    spec = importlib.util.spec_from_file_location("ot_console_app", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json_dumps(payload)

    def json(self):
        return self._payload


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload)


class _FakeAsyncClient:
    """Captures outbound calls instead of touching the network."""

    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None, **kwargs):
        type(self).calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse({"decision": "verify"})

    async def get(self, url, headers=None, **kwargs):
        type(self).calls.append({"url": url, "headers": headers})
        return _FakeResponse({"status": "ok"})


class _Req:
    def __init__(self, body: dict):
        self._body = body

    async def json(self):
        return self._body


def test_tokens_route_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_console(monkeypatch)
    client = TestClient(module.app)

    assert client.get("/api/tokens").status_code == 404, (
        "GET /api/tokens served every pilot token unauthenticated"
    )


def test_console_holds_no_operator_or_approver_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_console(monkeypatch)
    tokens = getattr(module, "TOKENS", None)
    if tokens is not None:
        assert "approver" not in tokens and "operator" not in tokens, (
            "the console still holds write-capable tokens; a caller who picks "
            "a role can approve their own proposal"
        )


def test_call_forwards_the_presented_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_console(monkeypatch)
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = TestClient(module.app)

    resp = client.post(
        "/api/call",
        json={
            "path": "/v1/execution/assess",
            "payload": {"tool_name": "read_sensor", "arguments": {}},
            "token": "caller-held-token",
        },
    )
    assert resp.status_code == 200, resp.text
    assert _FakeAsyncClient.calls, "no outbound call was made"
    assert _FakeAsyncClient.calls[0]["headers"]["Authorization"] == (
        "Bearer caller-held-token"
    )


def test_call_cannot_select_a_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SR-06 attack: body role=approver must not mint an approver call."""
    module = _load_console(monkeypatch)
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    client = TestClient(module.app)

    resp = client.post(
        "/api/call",
        json={
            "path": "/v1/execution/assess",
            "payload": {"tool_name": "adjust_setpoint", "arguments": {}},
            "role": "approver",
        },
    )
    assert resp.status_code == 400, resp.text
    assert _FakeAsyncClient.calls == [], "a role-selected call went out"


class _FakeProc:
    def __init__(self):
        self.returncode = 0

    async def communicate(self):
        return b"battery-output", None


def test_battery_requires_tokens_and_passes_them_to_the_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_console(monkeypatch)

    refused = asyncio.run(module.battery(_Req({})))
    assert refused.status_code == 400

    captured: dict = {}

    async def _fake_exec(*args, **kwargs):
        captured.update(kwargs)
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    ok = asyncio.run(
        module.battery(_Req({"agent_token": "tok-agent", "approver_token": "tok-approver"}))
    )
    assert ok.status_code == 200
    env = captured.get("env", {})
    assert env.get("OT_TOKEN_AGENT") == "tok-agent"
    assert env.get("OT_TOKEN_APPROVER") == "tok-approver"


def test_battery_is_single_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_console(monkeypatch)

    active = 0
    peak = 0

    async def _fake_exec(*args, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)

        class _SlowProc:
            returncode = 0

            async def communicate(self):
                nonlocal active
                try:
                    await asyncio.sleep(0.05)
                    return b"ok", None
                finally:
                    active -= 1

        return _SlowProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    body = {"agent_token": "a", "approver_token": "b"}

    async def _two_at_once():
        return await asyncio.gather(
            module.battery(_Req(body)), module.battery(_Req(body))
        )

    first, second = asyncio.run(_two_at_once())
    assert peak == 1, "two battery runs overlapped"
    assert sorted([first.status_code, second.status_code]) == [200, 409]
