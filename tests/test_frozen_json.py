# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""remora.frozen_json: deep freeze, JSON-domain refusal, strict equality."""
from __future__ import annotations

import datetime
import hashlib
import json
from types import MappingProxyType

import pytest

from remora import frozen_json
from remora.governance.effect_verification import effect_digest


def test_freeze_is_deep_and_detached():
    source = {"a": {"b": [1, {"c": "x"}]}}
    frozen = frozen_json.freeze(source)
    source["a"]["b"][1]["c"] = "y"
    source["a"]["b"].append(2)
    assert frozen_json.thaw(frozen) == {"a": {"b": [1, {"c": "x"}]}}
    assert isinstance(frozen["a"], MappingProxyType)
    assert isinstance(frozen["a"]["b"], tuple)
    with pytest.raises(TypeError):
        frozen["a"]["new"] = 1  # type: ignore[index]


@pytest.mark.parametrize("bad", [
    {1: "numeric key"},
    {"when": datetime.datetime(2026, 10, 6)},
    {"obj": object()},
    {"nan": float("nan")},
    {"inf": float("inf")},
    {"raw": b"bytes"},
])
def test_values_outside_the_json_domain_are_refused_not_coerced(bad):
    with pytest.raises(TypeError):
        frozen_json.freeze(bad)
    with pytest.raises(TypeError):
        frozen_json.digest(bad)


def test_digest_matches_the_historic_effect_digest_encoding():
    value = {"b": [1, 2.5, None, True], "a": "blåbær"}
    historic = hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert frozen_json.digest(value) == historic
    assert effect_digest(value) == historic
    assert frozen_json.digest(frozen_json.freeze(value)) == historic


@pytest.mark.parametrize("left,right,equal", [
    (1, 1, True),
    (True, 1, False),
    (1, 1.0, False),
    ("1", 1, False),
    ([1, 2], (1, 2), True),
    ({"a": [True]}, {"a": [1]}, False),
    ({"a": 1}, {"a": 1, "b": 2}, False),
    ({"a": {"b": None}}, frozen_json.freeze({"a": {"b": None}}), True),
    ([1], {"0": 1}, False),
])
def test_strict_equal_keeps_kinds_apart_at_every_depth(left, right, equal):
    assert frozen_json.strict_equal(left, right) is equal
    assert frozen_json.strict_equal(right, left) is equal


@pytest.mark.parametrize("observed", ["6", True, 6.0, 6.9, None])
def test_version_increment_accepts_integers_only(observed):
    from remora.governance.effect_verification import (
        EffectStatus,
        PostconditionContract,
        verify_declared_delta,
    )

    contract = PostconditionContract(
        tool_id="t", reader="r", target_selector={"id": "1"},
        expected_fields={"version": 5},
        comparison_rules={"version": "version_increment"},
    )
    kwargs = dict(proposal_id="p", execution_id="e", toolspec_hash="d" * 64,
                  verifier_identity="r")
    assert verify_declared_delta(
        contract, {"version": observed}, **kwargs).status is EffectStatus.MISMATCH
    assert verify_declared_delta(
        contract, {"version": 6}, **kwargs).status is EffectStatus.VERIFIED
