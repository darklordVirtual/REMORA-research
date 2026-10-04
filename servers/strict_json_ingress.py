# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Strict raw-JSON admission for the execution surface.

Security-relevant execution requests reach the authority logic as values a
general JSON parser has already produced. That parser is permissive where
RFC 8259 leaves room and RFC 7493 (I-JSON) does not: when a member name is
repeated the last value silently wins, ``NaN`` and ``Infinity`` are accepted
as numbers, and a lone ``\\uD800`` escape becomes an unpaired surrogate code
point inside a Python string. ``canonical_tool_call_hash`` is computed from
the parsed value, so two wire bodies that differ in a way the parser
collapses hash the same and only one of them is what the signer saw.

This module admits or refuses the *bytes* before the framework decodes them.
It never changes a value: a body that passes is handed to the framework
unchanged, so every request that was valid before this guard existed parses
to the same object and hashes the same. The guard can only refuse.

Refused, with a stable ``code``:

``json_too_large``          body above ``REMORA_MAX_EXECUTION_JSON_BYTES``
``json_invalid_utf8``       bytes that are not strict UTF-8 (including
                            encoded surrogates and a leading BOM)
``json_too_deep``           nesting beyond ``REMORA_MAX_EXECUTION_JSON_DEPTH``
``json_duplicate_member``   a repeated object member name, compared after
                            escape decoding (``"a"`` and ``"\\u0061"`` are the
                            same name)
``json_non_finite_number``  ``NaN``, ``Infinity`` or ``-Infinity``
``json_unpaired_surrogate`` a string containing a lone surrogate code point
``json_noncharacter``       a string containing a Unicode noncharacter
                            (I-JSON, RFC 7493 section 2.1)
``json_malformed``          anything else the strict decoder refuses

Not done here, deliberately: no Unicode normalisation, no re-serialisation,
no number conversion (integers stay integers; the framework's own parser
decides exactly as before), no change to ``remora/json-sorted-v1`` or to any
stored signature. The guard is scoped by path prefix to the surfaces that
compute a tool-call hash; everything else passes through untouched.
"""
from __future__ import annotations

import json
import os
from typing import Any, Iterable

STRICT_PATH_PREFIXES: tuple[str, ...] = ("/v1/execution/", "/v1/assess")
STRICT_METHODS: frozenset[bytes | str] = frozenset({"POST", "PUT", "PATCH"})

DEFAULT_MAX_BYTES = 1_048_576  # matches REMORA_MAX_REQUEST_BYTES' default
DEFAULT_MAX_DEPTH = 32

REFUSAL_CODES: tuple[str, ...] = (
    "json_too_large",
    "json_invalid_utf8",
    "json_too_deep",
    "json_duplicate_member",
    "json_non_finite_number",
    "json_unpaired_surrogate",
    "json_noncharacter",
    "json_malformed",
)


class StrictJsonRefusal(ValueError):
    """The body was refused before parsing. ``code`` is one of REFUSAL_CODES."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in REFUSAL_CODES:  # pragma: no cover - programming error
            raise ValueError(f"unknown refusal code {code!r}")
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _positive_int(raw: str, default: int) -> int:
    raw = raw.strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


# The two reads name their keys literally so the credential-topology gate
# (scripts/check_credential_topology.py) can resolve them statically.
def max_execution_json_bytes() -> int:
    return _positive_int(os.getenv("REMORA_MAX_EXECUTION_JSON_BYTES", ""), DEFAULT_MAX_BYTES)


def max_execution_json_depth() -> int:
    return _positive_int(os.getenv("REMORA_MAX_EXECUTION_JSON_DEPTH", ""), DEFAULT_MAX_DEPTH)


# ── scanning helpers (linear, no recursion) ─────────────────────────────────

def _check_depth(text: str, max_depth: int) -> None:
    """Refuse nesting deeper than ``max_depth`` without recursing.

    A string-aware scan: brackets inside string literals do not count. The
    scan does not validate the JSON; the decoder does that afterwards. It
    only guarantees the decoder is never asked to recurse past the cap.
    """
    depth = 0
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
            if depth > max_depth:
                raise StrictJsonRefusal(
                    "json_too_deep", f"nesting exceeds {max_depth} levels"
                )
        elif ch in "}]":
            depth -= 1


def _is_noncharacter(code_point: int) -> bool:
    return 0xFDD0 <= code_point <= 0xFDEF or (code_point & 0xFFFE) == 0xFFFE


def _check_text(value: str) -> None:
    for ch in value:
        cp = ord(ch)
        if 0xD800 <= cp <= 0xDFFF:
            raise StrictJsonRefusal(
                "json_unpaired_surrogate", "string contains an unpaired surrogate"
            )
        if _is_noncharacter(cp):
            raise StrictJsonRefusal(
                "json_noncharacter", "string contains a Unicode noncharacter"
            )


def _check_strings(value: Any) -> None:
    """Walk the decoded value iteratively; refuse bad code points anywhere."""
    stack: list[Any] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            _check_text(item)
        elif isinstance(item, dict):
            for key, child in item.items():
                _check_text(key)
                stack.append(child)
        elif isinstance(item, list):
            stack.extend(item)


def _unique_members(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise StrictJsonRefusal(
                "json_duplicate_member", f"duplicate object member {key!r}"
            )
        out[key] = value
    return out


def _refuse_constant(name: str) -> Any:
    raise StrictJsonRefusal("json_non_finite_number", f"{name} is not a JSON number")


# ── the admission function ─────────────────────────────────────────────────

def admit_strict_json(
    raw: bytes,
    *,
    max_bytes: int | None = None,
    max_depth: int | None = None,
) -> Any:
    """Admit ``raw`` as strict JSON or raise :class:`StrictJsonRefusal`.

    Returns the decoded value for callers that want it (tests, tooling). The
    middleware discards it: the framework decodes the same bytes itself, so
    the admitted request is exactly the request that would have arrived
    without this guard.
    """
    limit = max_bytes if max_bytes is not None else max_execution_json_bytes()
    depth = max_depth if max_depth is not None else max_execution_json_depth()
    if len(raw) > limit:
        raise StrictJsonRefusal("json_too_large", f"body exceeds {limit} bytes")
    try:
        text = raw.decode("utf-8")  # strict: refuses invalid sequences and CESU surrogates
    except UnicodeDecodeError as exc:
        raise StrictJsonRefusal("json_invalid_utf8", "body is not valid UTF-8") from exc
    if text.startswith("﻿"):
        raise StrictJsonRefusal("json_invalid_utf8", "body starts with a byte order mark")
    _check_depth(text, depth)
    try:
        value = json.loads(
            text, object_pairs_hook=_unique_members, parse_constant=_refuse_constant
        )
    except StrictJsonRefusal:
        raise
    except (ValueError, RecursionError) as exc:
        raise StrictJsonRefusal("json_malformed", "body is not well-formed JSON") from exc
    _check_strings(value)
    return value


# ── ASGI middleware ─────────────────────────────────────────────────────────

def _path_is_guarded(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


class StrictJsonIngressMiddleware:
    """Refuse non-strict JSON bodies on the guarded paths; replay the rest.

    Buffers the request body (the outer body-size middleware bounds it),
    runs :func:`admit_strict_json`, and on success hands the original bytes
    to the application through a replacement ``receive``. On refusal it
    answers 400 with a JSON body carrying the stable ``code``. Non-HTTP
    scopes, other methods, other paths and empty bodies pass straight
    through.
    """

    def __init__(self, asgi_app: Any, prefixes: tuple[str, ...] = STRICT_PATH_PREFIXES) -> None:
        self.app = asgi_app
        self.prefixes = tuple(prefixes)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in STRICT_METHODS
            or not _path_is_guarded(scope.get("path", ""), self.prefixes)
        ):
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] == "http.request":
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
        raw = b"".join(chunks)

        if raw:
            try:
                admit_strict_json(raw)
            except StrictJsonRefusal as refusal:
                await self._reject(send, refusal)
                return

        replayed = False

        async def replay() -> Any:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send: Any, refusal: StrictJsonRefusal) -> None:
        body = json.dumps({
            "detail": f"strict JSON admission refused the request body: {refusal.detail}",
            "code": refusal.code,
        }).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 400,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_DEPTH",
    "REFUSAL_CODES",
    "STRICT_METHODS",
    "STRICT_PATH_PREFIXES",
    "StrictJsonIngressMiddleware",
    "StrictJsonRefusal",
    "admit_strict_json",
    "max_execution_json_bytes",
    "max_execution_json_depth",
]
