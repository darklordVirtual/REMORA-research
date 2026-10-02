# SPDX-License-Identifier: BUSL-1.1
"""Bounded JSON helpers for the evidence-admission layer.

Comparison and hashing domain, deliberately narrow: null, booleans, integers
and strings, lists, and string-keyed objects. Floats are refused rather than
compared, because binary64 round-tripping through JSON is not a stable
identity for evidence. Depth, size and duplicate keys are bounded before any
other check runs.

This module shares its discipline with ``experiments/bounded_readback.py``
but does not import it: the experiment carries opt-in disclaimers that must
not be inherited by production code by accident.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

MAX_BYTES = 65_536
MAX_DEPTH = 16


def validate_json_value(value: Any, depth: int = 0) -> None:
    """Reject anything outside the bounded comparison domain."""
    if depth > MAX_DEPTH:
        raise ValueError("JSON nesting limit exceeded")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is list:
        for item in value:
            validate_json_value(item, depth + 1)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            validate_json_value(item, depth + 1)
        return
    raise ValueError(
        "unsupported JSON value: only null, bool, int, str, list and "
        "string-keyed objects are admitted"
    )


def canonical_bytes(value: Any) -> bytes:
    """Deterministic comparison encoding. Not an RFC 8785 implementation."""
    validate_json_value(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    """SHA-256 over the canonical encoding."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def decode_bounded(raw: bytes) -> Any:
    """Parse JSON with duplicate-key rejection and size/depth bounds."""
    if type(raw) is not bytes or not raw or len(raw) > MAX_BYTES:
        raise ValueError("invalid evidence size or type")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    validate_json_value(value)
    return value


def require_identifier(value: Any, field: str) -> str:
    """A non-empty string identifier, or a refusal."""
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field}: nonempty identifier required")
    return value


def require_sha256(value: Any, field: str) -> str:
    """A 64-hex digest string, or a refusal."""
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError(f"{field}: 64-hex SHA-256 digest required")
    return value
