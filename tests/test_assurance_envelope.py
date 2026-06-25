"""Tests for remora.assurance.envelope."""
from __future__ import annotations

import pytest
from dataclasses import FrozenInstanceError

from remora.assurance.envelope import (
    AssuranceEnvelope,
    _sha256_list,
    build_envelope,
)

_BASE_KW = dict(
    trace_root_hash="abc",
    leaf_count=3,
    genome_dict={},
    oracle_provider_ids=[],
    policy_decision=None,
)


# ---------------------------------------------------------------------------
# 1. build_envelope succeeds with minimal args
# ---------------------------------------------------------------------------
def test_build_envelope_succeeds():
    env = build_envelope(**_BASE_KW)
    assert isinstance(env, AssuranceEnvelope)


# ---------------------------------------------------------------------------
# 2. root_hash passes through unchanged
# ---------------------------------------------------------------------------
def test_root_hash_passthrough():
    env = build_envelope(**_BASE_KW)
    assert env.root_hash == "abc"


# ---------------------------------------------------------------------------
# 3. leaf_count passes through unchanged
# ---------------------------------------------------------------------------
def test_leaf_count_passthrough():
    env = build_envelope(**_BASE_KW)
    assert env.leaf_count == 3


# ---------------------------------------------------------------------------
# 4. signature_standard contains "unsigned"
# ---------------------------------------------------------------------------
def test_signature_standard_contains_unsigned():
    env = build_envelope(**_BASE_KW)
    assert "unsigned" in env.signature_standard


# ---------------------------------------------------------------------------
# 5. config_hash is a 64-char hex string
# ---------------------------------------------------------------------------
def test_config_hash_is_sha256_hex():
    env = build_envelope(**_BASE_KW)
    assert isinstance(env.config_hash, str)
    assert len(env.config_hash) == 64
    int(env.config_hash, 16)  # must be valid hex


# ---------------------------------------------------------------------------
# 6. model_pool_hash is a 64-char hex string
# ---------------------------------------------------------------------------
def test_model_pool_hash_is_sha256_hex():
    env = build_envelope(**_BASE_KW)
    assert isinstance(env.model_pool_hash, str)
    assert len(env.model_pool_hash) == 64
    int(env.model_pool_hash, 16)


# ---------------------------------------------------------------------------
# 7. policy_hash is a 64-char hex string
# ---------------------------------------------------------------------------
def test_policy_hash_is_sha256_hex():
    env = build_envelope(**_BASE_KW)
    assert isinstance(env.policy_hash, str)
    assert len(env.policy_hash) == 64
    int(env.policy_hash, 16)


# ---------------------------------------------------------------------------
# 8. Different genome_dicts produce different config_hashes
# ---------------------------------------------------------------------------
def test_different_genome_dicts_different_config_hash():
    env_a = build_envelope(**{**_BASE_KW, "genome_dict": {"lr": 0.1}})
    env_b = build_envelope(**{**_BASE_KW, "genome_dict": {"lr": 0.9}})
    assert env_a.config_hash != env_b.config_hash


# ---------------------------------------------------------------------------
# 9. Same inputs always produce same envelope (deterministic)
# ---------------------------------------------------------------------------
def test_deterministic():
    env_a = build_envelope(**_BASE_KW)
    env_b = build_envelope(**_BASE_KW)
    assert env_a == env_b


# ---------------------------------------------------------------------------
# 10. Non-empty policy_decision gives different policy_hash than empty
# ---------------------------------------------------------------------------
def test_nonempty_policy_decision_differs_from_empty():
    env_empty = build_envelope(**{**_BASE_KW, "policy_decision": None})
    env_policy = build_envelope(**{**_BASE_KW, "policy_decision": {"decision": "accept"}})
    assert env_empty.policy_hash != env_policy.policy_hash


# ---------------------------------------------------------------------------
# 11. Oracle order doesn't matter (_sha256_list sorts)
# ---------------------------------------------------------------------------
def test_sha256_list_order_independent():
    assert _sha256_list(["a", "b"]) == _sha256_list(["b", "a"])


def test_model_pool_hash_order_independent():
    env_ab = build_envelope(**{**_BASE_KW, "oracle_provider_ids": ["a", "b"]})
    env_ba = build_envelope(**{**_BASE_KW, "oracle_provider_ids": ["b", "a"]})
    assert env_ab.model_pool_hash == env_ba.model_pool_hash


# ---------------------------------------------------------------------------
# 12. AssuranceEnvelope is frozen (immutable)
# ---------------------------------------------------------------------------
def test_assurance_envelope_is_frozen():
    env = build_envelope(**_BASE_KW)
    with pytest.raises(FrozenInstanceError):
        env.root_hash = "tampered"  # type: ignore[misc]
