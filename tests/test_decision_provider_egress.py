# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""What may leave the process for a semantic provider (issue #753, gap 3).

The credential check used to read only the top-level keys, so a secret one
level down reached the provider. It now reaches every depth, inside objects
and lists, and the state has to stay inside the JSON domain and the egress
bounds. A state outside them is refused, never trimmed: trimming would change
the question the provider is asked.
"""
from __future__ import annotations

import pytest

from remora.decision_providers.enrich import (
    EGRESS_MAX_BYTES,
    EGRESS_MAX_DEPTH,
    EGRESS_MAX_ITEMS,
    EGRESS_MAX_TEXT,
    semantic_state,
    semantic_state_v2,
)


def _v1(arguments, context=None):
    return semantic_state(intent="refund order 4", tool_name="refund", arguments=arguments, context=context)


def _v2(arguments, untrusted=None):
    return semantic_state_v2(operator_request="refund order 4", tool_name="refund",
                             arguments=arguments, untrusted_content=untrusted)


@pytest.mark.parametrize("payload", [
    {"api_key": "x"},
    {"config": {"api_key": "x"}},
    {"items": [{"session_token": "x"}]},
    {"nested": {"auth": {"private_key": "x"}}},
    {"a": [[{"b": {"Authorization": "Bearer x"}}]]},
    {"headers": [{"name": "x", "Cookie": "y"}]},
])
@pytest.mark.parametrize("build", [_v1, _v2])
def test_credential_shaped_keys_are_refused_at_any_depth(build, payload) -> None:
    with pytest.raises(ValueError, match="credential-shaped"):
        build(payload)


def test_credentials_in_context_and_untrusted_content_are_refused_too() -> None:
    with pytest.raises(ValueError, match="credential-shaped"):
        _v1({"order": 4}, context={"meta": {"password": "x"}})
    with pytest.raises(ValueError, match="credential-shaped"):
        _v2({"order": 4}, untrusted={"ticket": [{"secret": "x"}]})


def test_the_refusal_names_where_the_key_is() -> None:
    with pytest.raises(ValueError, match=r"items\[0\]\.session_token"):
        _v2({"items": [{"session_token": "x"}]})


@pytest.mark.parametrize("build", [_v1, _v2])
def test_ordinary_nested_json_passes_unchanged(build) -> None:
    args = {"order": 4, "lines": [{"sku": "A-1", "qty": 2, "price": 9.5}], "note": None,
            "flags": {"express": True}, "tags": ["blue", "gift"]}
    state = build(args)
    assert (state["arguments"] if "arguments" in state else state["proposed_call"]["arguments"]) == args


def test_excessive_depth_is_refused() -> None:
    deep: dict = {}
    node = deep
    for _ in range(EGRESS_MAX_DEPTH + 2):
        node["n"] = {}
        node = node["n"]
    with pytest.raises(ValueError, match="nested deeper"):
        _v2(deep)


def test_too_many_items_are_refused() -> None:
    with pytest.raises(ValueError, match="more than"):
        _v2({"ids": list(range(EGRESS_MAX_ITEMS + 1))})
    with pytest.raises(ValueError, match="more than"):
        _v2({f"k{i}": i for i in range(EGRESS_MAX_ITEMS + 1)})


def test_an_overlong_free_text_field_is_refused_not_trimmed() -> None:
    with pytest.raises(ValueError, match="text longer"):
        _v2({"note": "x" * (EGRESS_MAX_TEXT + 1)})
    with pytest.raises(ValueError, match="text longer"):
        semantic_state_v2(operator_request="y" * (EGRESS_MAX_TEXT + 1), tool_name="t", arguments={})


def test_an_oversized_serialized_state_is_refused() -> None:
    # Each field is inside the text bound; together they exceed the byte bound.
    chunk = "z" * (EGRESS_MAX_TEXT - 1)
    with pytest.raises(ValueError, match="bytes of state"):
        _v2({f"part{i}": chunk for i in range(EGRESS_MAX_BYTES // EGRESS_MAX_TEXT + 1)})


@pytest.mark.parametrize("value", [b"raw", float("nan"), float("inf"), {1, 2}, object()])
def test_values_outside_the_json_domain_are_refused(value) -> None:
    with pytest.raises(ValueError, match="refusing to send"):
        _v2({"v": value})


def test_a_non_string_key_is_refused() -> None:
    with pytest.raises(ValueError, match="non-string key"):
        _v2({"v": {1: "x"}})
