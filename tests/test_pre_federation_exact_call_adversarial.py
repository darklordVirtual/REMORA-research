# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pre-Federation adversarial probes for exact-call binding.

This file is intentionally test-only.  It expands the declared search domain in
tests/test_enforcement_properties.py without changing production semantics.

The probes distinguish:
- mutations that MUST produce a different exact-call binding; and
- values that are not representable without loss in the JSON tool-call domain
  and therefore MUST be rejected rather than silently stringified/coerced.

A failure here is evidence for a bounded hardening issue, not evidence that the
/v1/execution raw-JSON boundary is bypassable.  The HTTP boundary has separate
strict-admission tests.  These probes target the library-level binding primitive
that Federation/interop claims cite directly.
"""
from __future__ import annotations

import math

import pytest

from remora.policy.observation import canonical_tool_call_hash


def _h(arguments):
    return canonical_tool_call_hash(
        name="adjust_setpoint",
        arguments=arguments,
        tenant="tenant-a",
        target="prod",
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ({"nested": {"mode": "safe", "limit": 5}}, {"nested": {"mode": "safe", "limit": 6}}),
        ({"nested": {"mode": "safe", "limit": 5}}, {"nested": {"mode": "safe"}}),
        ({"ports": ["eth0", "eth1"]}, {"ports": ["eth1", "eth0"]}),
        ({"value": 1}, {"value": 1.0}),
        ({"value": True}, {"value": 1}),
        ({"value": None}, {}),
        ({"name": "\u00e9"}, {"name": "e\u0301"}),
    ],
)
def test_exact_call_binding_distinguishes_json_domain_mutations(before, after):
    """Semantically different JSON-domain calls must not share a binding."""
    assert _h(before) != _h(after)


def test_object_member_order_is_not_a_call_change():
    """Object-member order is intentionally irrelevant to exact-call identity."""
    assert _h({"a": 1, "b": {"x": 2, "y": 3}}) == _h(
        {"b": {"y": 3, "x": 2}, "a": 1}
    )


def test_non_json_object_must_not_collapse_to_its_string_representation():
    """default=str would let a Python object reuse authority issued for a string.

    The safe outcomes are either:
      1. reject the non-JSON value at hashing/admission time, or
      2. encode a typed representation that cannot collide with a JSON string.
    Silent stringification is not an exact-call binding.
    """

    class LooksLikeApproved:
        def __str__(self) -> str:
            return "approved"

    obj = LooksLikeApproved()
    try:
        object_hash = _h({"value": obj})
    except (TypeError, ValueError):
        return
    assert object_hash != _h({"value": "approved"})


def test_non_string_mapping_key_must_not_collapse_to_string_key():
    """JSON object keys are strings; library input must not erase Python key type."""
    try:
        numeric_key_hash = _h({1: "x"})
    except (TypeError, ValueError):
        return
    assert numeric_key_hash != _h({"1": "x"})


def test_tuple_must_not_silently_collapse_to_json_array():
    """A non-JSON container type must be rejected or remain type-distinct."""
    try:
        tuple_hash = _h({"value": (1, 2)})
    except (TypeError, ValueError):
        return
    assert tuple_hash != _h({"value": [1, 2]})


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_rejected_from_exact_call_binding(value):
    """NaN/Infinity are outside the interoperable JSON tool-call domain."""
    with pytest.raises((TypeError, ValueError)):
        _h({"value": value})
