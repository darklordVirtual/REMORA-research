# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Strict raw-JSON admission on the execution surface (servers/strict_json_ingress.py).

Two halves. The admission function is characterised vector by vector against
RFC 8259 and RFC 7493: what is refused, with which code, and what passes
untouched. The middleware is then shown to replay admitted bytes to the
application byte for byte, so a request that was valid before the guard
parses to the same value and hashes the same, and to refuse only on the
guarded paths and methods. The last tests go through ``servers.api.app``.
"""
from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse, PlainTextResponse  # noqa: E402

from remora.policy.observation import canonical_tool_call_hash  # noqa: E402
from servers.strict_json_ingress import (  # noqa: E402
    REFUSAL_CODES,
    STRICT_PATH_PREFIXES,
    StrictJsonIngressMiddleware,
    StrictJsonRefusal,
    admit_strict_json,
)

VALID_CALL = (
    b'{"tool_call": {"name": "net.port.shutdown", '
    b'"arguments": {"switch": "sw-01", "port": 7, "ratio": 0.5, "nested": {"k": [1, 2, {"z": null}]}}, '
    b'"tenant": "acme", "target": "prod"}}'
)


def _refused(raw: bytes, **kw) -> str:
    with pytest.raises(StrictJsonRefusal) as info:
        admit_strict_json(raw, **kw)
    assert info.value.code in REFUSAL_CODES
    return info.value.code


# ── refused vectors ─────────────────────────────────────────────────────────

def test_duplicate_top_level_member_is_refused() -> None:
    assert _refused(b'{"a": 1, "a": 2}') == "json_duplicate_member"


def test_duplicate_nested_argument_member_is_refused() -> None:
    raw = b'{"tool_call": {"arguments": {"port": 7, "port": 8}}}'
    assert _refused(raw) == "json_duplicate_member"


def test_duplicate_key_spelled_literally_and_as_escape_is_refused() -> None:
    # "a" and "a" are the same member name after escape decoding; a
    # permissive parser keeps the last one and the signer saw neither.
    assert _refused(b'{"a": 1, "\\u0061": 2}') == "json_duplicate_member"


def test_unpaired_high_surrogate_escape_is_refused() -> None:
    assert _refused(b'{"s": "\\ud800"}') == "json_unpaired_surrogate"


def test_unpaired_low_surrogate_escape_is_refused() -> None:
    assert _refused(b'{"s": "x\\udc00y"}') == "json_unpaired_surrogate"


def test_unpaired_surrogate_in_a_member_name_is_refused() -> None:
    assert _refused(b'{"\\ud800": 1}') == "json_unpaired_surrogate"


def test_invalid_utf8_bytes_are_refused() -> None:
    assert _refused(b'{"s": "\xff\xfe"}') == "json_invalid_utf8"


def test_cesu_encoded_surrogate_bytes_are_refused() -> None:
    # ED A0 80 is U+D800 encoded as if it were a scalar value; strict UTF-8 refuses it.
    assert _refused(b'{"s": "\xed\xa0\x80"}') == "json_invalid_utf8"


def test_byte_order_mark_is_refused() -> None:
    assert _refused(b'\xef\xbb\xbf{"a": 1}') == "json_invalid_utf8"


@pytest.mark.parametrize("literal", [b"NaN", b"Infinity", b"-Infinity"])
def test_non_finite_numbers_are_refused(literal: bytes) -> None:
    assert _refused(b'{"ratio": ' + literal + b"}") == "json_non_finite_number"


def test_noncharacter_is_refused() -> None:
    assert _refused('{"s": "￾"}'.encode("utf-8")) == "json_noncharacter"
    assert _refused('{"s": "﷐"}'.encode("utf-8")) == "json_noncharacter"


def test_excessive_nesting_is_refused_before_the_decoder_recurses() -> None:
    deep = b"[" * 40 + b"]" * 40
    assert _refused(deep, max_depth=32) == "json_too_deep"
    # Brackets inside strings do not count as nesting.
    assert admit_strict_json(b'{"s": "' + b"[" * 100 + b'"}', max_depth=4) == {"s": "[" * 100}


def test_excessive_body_size_is_refused() -> None:
    assert _refused(b'{"s": "' + b"x" * 100 + b'"}', max_bytes=64) == "json_too_large"


def test_malformed_json_is_refused_as_malformed() -> None:
    assert _refused(b'{"a": }') == "json_malformed"
    assert _refused(b"") == "json_malformed"


# ── admitted vectors: value identity with the permissive parser ───────────

@pytest.mark.parametrize(
    "raw",
    [
        VALID_CALL,
        '{"s": "ordinary unicode: æøå ñ 中文 🙂"}'.encode("utf-8"),
        b'{"s": "\\ud83d\\ude00"}',  # valid surrogate pair escape, U+1F600
        '{"s": "\U0001F600"}'.encode("utf-8"),  # the same astral scalar, raw
        b'{"n": 12345678901234567890123456789, "f": 1.5e300, "neg": -0.0}',
        b'  {\n  "a" : [ 1 , 2 ] ,\n "b" : {}  }\n',
        b'[1, "two", {"three": 3}]',
        b'"a bare string"',
        b"42",
    ],
)
def test_admitted_body_decodes_to_what_the_framework_would_see(raw: bytes) -> None:
    assert admit_strict_json(raw) == json.loads(raw)


def test_integers_are_not_reinterpreted_through_binary64() -> None:
    value = admit_strict_json(b'{"n": 9007199254740993}')
    assert value["n"] == 9007199254740993 and isinstance(value["n"], int)


def test_admission_does_not_change_the_tool_call_hash() -> None:
    body = json.loads(VALID_CALL)["tool_call"]
    admitted = admit_strict_json(VALID_CALL)["tool_call"]
    before = canonical_tool_call_hash(
        name=body["name"], arguments=body["arguments"],
        tenant=body["tenant"], target=body["target"],
    )
    after = canonical_tool_call_hash(
        name=admitted["name"], arguments=admitted["arguments"],
        tenant=admitted["tenant"], target=admitted["target"],
    )
    assert before == after


# ── middleware: scope and byte-for-byte replay ─────────────────────────────

def _echo_app():
    from starlette.applications import Starlette
    from starlette.routing import Route

    async def echo(request: Request):
        return PlainTextResponse(await request.body())

    async def ping(request: Request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[
        Route("/v1/execution/assess", echo, methods=["POST"]),
        Route("/v1/execution/assess", ping, methods=["GET"]),
        Route("/v1/assess", echo, methods=["POST"]),
        Route("/v1/evidence", echo, methods=["POST"]),
    ])
    app.add_middleware(StrictJsonIngressMiddleware)
    return app


def test_middleware_replays_admitted_bytes_unchanged() -> None:
    client = TestClient(_echo_app())
    raw = b'  {"tool_call" : {"name":"x", "arguments": {"b": 2, "a": 1}}, "note": "\\u00e6 \xc3\xa6"}  '
    resp = client.post("/v1/execution/assess", content=raw,
                       headers={"content-type": "application/json"})
    assert resp.status_code == 200
    assert resp.content == raw  # whitespace, key order and escapes preserved


def test_middleware_refuses_on_guarded_paths_with_the_code() -> None:
    client = TestClient(_echo_app())
    for path in ("/v1/execution/assess", "/v1/assess"):
        resp = client.post(path, content=b'{"a": 1, "a": 2}',
                           headers={"content-type": "application/json"})
        assert resp.status_code == 400, path
        assert resp.json()["code"] == "json_duplicate_member"


def test_middleware_passes_other_paths_and_methods_through() -> None:
    client = TestClient(_echo_app())
    dup = b'{"a": 1, "a": 2}'
    assert client.post("/v1/evidence", content=dup,
                       headers={"content-type": "application/json"}).status_code == 200
    assert client.get("/v1/execution/assess").status_code == 200


def test_middleware_passes_an_empty_body_through() -> None:
    client = TestClient(_echo_app())
    resp = client.post("/v1/execution/assess", content=b"")
    assert resp.status_code == 200 and resp.content == b""


def test_guarded_prefixes_cover_the_execution_router() -> None:
    assert "/v1/execution/" in STRICT_PATH_PREFIXES
    assert "/v1/assess" in STRICT_PATH_PREFIXES


# ── through the real application ───────────────────────────────────────────

def _reload_api(monkeypatch):
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("REMORA_API_TOKENS", raising=False)
    monkeypatch.delenv("REMORA_API_BEARER_TOKEN", raising=False)
    import servers.api as api

    return importlib.reload(api)


def test_execution_surface_refuses_duplicate_members_before_anything_else(monkeypatch) -> None:
    api = _reload_api(monkeypatch)
    client = TestClient(api.app)
    resp = client.post("/v1/execution/assess", content=b'{"tool": "x", "tool": "y"}',
                       headers={"content-type": "application/json"})
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "json_duplicate_member"


def test_execution_surface_refuses_non_finite_numbers(monkeypatch) -> None:
    api = _reload_api(monkeypatch)
    client = TestClient(api.app)
    resp = client.post("/v1/execution/assess", content=b'{"arguments": {"ratio": NaN}}',
                       headers={"content-type": "application/json"})
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "json_non_finite_number"


def test_execution_surface_hands_well_formed_bodies_to_the_application(monkeypatch) -> None:
    api = _reload_api(monkeypatch)
    client = TestClient(api.app)
    resp = client.post("/v1/execution/assess", content=b'{"tool": "x"}',
                       headers={"content-type": "application/json"})
    # Whatever the application answers (authentication, validation), the
    # guard did not: no guard code, no 400 from this layer.
    assert resp.status_code != 400 or "code" not in resp.json()


def test_body_size_limit_still_wins_over_the_guard(monkeypatch) -> None:
    api = _reload_api(monkeypatch)
    monkeypatch.setenv("REMORA_MAX_REQUEST_BYTES", "128")
    client = TestClient(api.app)
    resp = client.post("/v1/execution/assess", content=b'{"s": "' + b"x" * 1000 + b'"}',
                       headers={"content-type": "application/json"})
    assert resp.status_code == 413, resp.text
