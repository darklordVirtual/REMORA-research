# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Bounded tool results: a result is verifiable even when it is not retained.

Dispatch used to inline the whole tool result into both the HTTP response and
the audit record. A large or hostile result therefore inflated the audit trail
and any downstream context window, and gave a prompt-injection payload a free
ride into whatever read the envelope next.

The contract these tests pin: the hash always covers the FULL result, so
truncating the retained preview never costs verifiability — a replay can still
prove it observed the same output.
"""
from __future__ import annotations

import hashlib
import json

from remora.enforcement.result_envelope import (
    DEFAULT_MAX_RESULT_BYTES,
    ToolResultEnvelope,
    capture_tool_result,
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")


# ---------------------------------------------------------------------------
# Small results pass through untouched
# ---------------------------------------------------------------------------

def test_small_result_is_retained_whole() -> None:
    result = {"stored": True, "path": "/tmp/a.json"}
    env = capture_tool_result(result)
    assert env.truncated is False
    assert env.preview == result
    assert env.size_bytes == len(_canonical(result))


def test_hash_is_over_the_canonical_full_result() -> None:
    result = {"b": 2, "a": 1}
    env = capture_tool_result(result)
    assert env.sha256 == hashlib.sha256(_canonical(result)).hexdigest()


def test_hash_is_key_order_independent() -> None:
    assert capture_tool_result({"a": 1, "b": 2}).sha256 == \
        capture_tool_result({"b": 2, "a": 1}).sha256


def test_hash_changes_when_any_value_changes() -> None:
    assert capture_tool_result({"a": 1}).sha256 != capture_tool_result({"a": 2}).sha256


# ---------------------------------------------------------------------------
# Oversized results: bounded preview, unbroken verifiability
# ---------------------------------------------------------------------------

def test_oversized_result_is_truncated_but_still_hashes_the_whole() -> None:
    result = {"rows": ["x" * 100 for _ in range(500)]}
    full_hash = hashlib.sha256(_canonical(result)).hexdigest()
    env = capture_tool_result(result, max_bytes=1024)

    assert env.truncated is True
    assert env.size_bytes == len(_canonical(result))
    assert env.size_bytes > 1024
    # The retained preview is bounded...
    assert len(_canonical(env.preview)) <= 1024 + 256  # marker overhead
    # ...and the hash still identifies the FULL result.
    assert env.sha256 == full_hash


def test_truncated_preview_is_marked_not_silently_shortened() -> None:
    env = capture_tool_result({"rows": ["y" * 100 for _ in range(500)]},
                              max_bytes=512)
    rendered = json.dumps(env.preview, default=str)
    assert "truncated" in rendered.lower()


def test_budget_boundary_is_not_truncated() -> None:
    """A result exactly at the budget is retained; one byte over is not."""
    payload = "z" * 100
    exact = capture_tool_result(payload, max_bytes=len(_canonical(payload)))
    assert exact.truncated is False
    over = capture_tool_result(payload, max_bytes=len(_canonical(payload)) - 1)
    assert over.truncated is True


# ---------------------------------------------------------------------------
# Hostile / awkward payloads degrade, never raise
# ---------------------------------------------------------------------------

def test_unserialisable_result_degrades_to_text_instead_of_raising() -> None:
    class Opaque:
        def __repr__(self) -> str:
            return "<opaque>"

    env = capture_tool_result({"obj": Opaque()})
    assert env.sha256
    assert env.media_type in ("application/json", "text/plain")


def test_result_that_cannot_be_json_encoded_at_all_still_produces_a_hash() -> None:
    class Exploding:
        def __repr__(self) -> str:
            raise RuntimeError("repr blew up")

    env = capture_tool_result(Exploding())
    assert len(env.sha256) == 64
    assert env.media_type == "text/plain"


def test_none_result_is_representable() -> None:
    env = capture_tool_result(None)
    assert env.truncated is False
    assert env.preview is None


# ---------------------------------------------------------------------------
# Serialisation contract (the envelope goes into audit records)
# ---------------------------------------------------------------------------

def test_to_dict_is_json_serialisable_and_complete() -> None:
    env = capture_tool_result({"a": 1})
    d = env.to_dict()
    json.dumps(d)  # must not raise
    assert set(d) == {"sha256", "size_bytes", "truncated", "preview", "media_type"}


def test_default_budget_is_bounded_and_documented() -> None:
    assert isinstance(DEFAULT_MAX_RESULT_BYTES, int)
    assert 0 < DEFAULT_MAX_RESULT_BYTES <= 1_048_576


def test_envelope_is_frozen() -> None:
    import dataclasses

    env = capture_tool_result({"a": 1})
    assert isinstance(env, ToolResultEnvelope)
    assert dataclasses.is_dataclass(env)
    try:
        env.truncated = True  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("ToolResultEnvelope must be immutable")
