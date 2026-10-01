# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The three-domain custody split for mediated effects (NTA-2 phase 3).

``test_custody_guard.py`` covers the two-domain split (K1 to K11): the
authority mints leases and holds no effect credential; the executor verifies
leases and holds the credentials its tools close over. That leaves credential
topology limit L3 open: inside the executor a tool can use any credential the
process holds.

Setting ``REMORA_EFFECT_ENDPOINT`` on the executor declares a third domain.
The effect domain holds the effect credentials and runs the primitives; the
executor, where tool code runs, must then hold none of them.

    K12 an effect process holding lease signing material is refused
    K13 an effect process without verification material is refused
    K14 an effect process missing a declared effect credential is refused
    K15 an executor in three-domain mode holding an effect credential is refused
    K16 a correctly split three-domain deployment is accepted, per role
    K17 the effect domain cannot register tool callables or mint leases
    K18 in three-domain mode only the effect domain binds effect executors
    K19 the two-domain executor is unchanged (it still must hold its credentials)
"""
from __future__ import annotations

import pytest

from remora.enforcement.custody import (
    CustodyViolation,
    assert_custody_split,
    assert_may_hold_effect_executors,
    assert_may_hold_tool_callables,
    assert_may_mint_authority,
    domain_role,
    effect_domain_split,
)
from tests.conformance.test_custody_guard import EFFECT, PUBLIC_KEY, strict  # noqa: F401

ENDPOINT = "https://effects.internal"


def _effect(m: pytest.MonkeyPatch) -> None:
    m.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "effect")
    m.setenv("REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", PUBLIC_KEY)
    m.setenv(EFFECT, "the-real-downstream-secret")


def _worker(m: pytest.MonkeyPatch) -> None:
    m.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
    m.setenv("REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", PUBLIC_KEY)
    m.setenv("REMORA_EFFECT_ENDPOINT", ENDPOINT)


@pytest.fixture
def three(strict):  # noqa: F811
    strict.delenv("REMORA_EFFECT_ENDPOINT", raising=False)
    return strict


def test_the_effect_role_is_recognised(three) -> None:
    _effect(three)
    assert domain_role() == "effect"


def test_k12_effect_holding_signing_material_is_refused(three) -> None:
    _effect(three)
    three.setenv("REMORA_LEASE_SIGNING_KEY", "k")
    with pytest.raises(CustodyViolation, match="signing material"):
        assert_custody_split()


def test_k13_effect_without_verification_material_is_refused(three) -> None:
    _effect(three)
    three.delenv("REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC")
    with pytest.raises(CustodyViolation, match="verify"):
        assert_custody_split()


def test_k14_effect_missing_its_credential_is_refused(three) -> None:
    _effect(three)
    three.delenv(EFFECT)
    with pytest.raises(CustodyViolation, match="missing effect credential"):
        assert_custody_split()


def test_k15_three_domain_executor_holding_a_credential_is_refused(three) -> None:
    _worker(three)
    three.setenv(EFFECT, "leaked-into-the-worker")
    assert effect_domain_split()
    with pytest.raises(CustodyViolation, match="holds effect credential"):
        assert_custody_split()


def test_k16_a_correct_three_domain_split_is_accepted(three) -> None:
    _effect(three)
    assert assert_custody_split() == "effect"
    three.delenv(EFFECT)
    _worker(three)
    assert assert_custody_split() == "executor"


def test_k17_the_effect_domain_registers_no_tools_and_mints_nothing(three) -> None:
    _effect(three)
    with pytest.raises(CustodyViolation):
        assert_may_hold_tool_callables()
    with pytest.raises(CustodyViolation):
        assert_may_mint_authority()


def test_k18_only_the_effect_domain_binds_effect_executors(three) -> None:
    _worker(three)
    with pytest.raises(CustodyViolation, match="effect domain"):
        assert_may_hold_effect_executors()
    three.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "authority")
    with pytest.raises(CustodyViolation):
        assert_may_hold_effect_executors()
    _effect(three)
    three.delenv("REMORA_EFFECT_ENDPOINT")
    assert_may_hold_effect_executors()


def test_k19_the_two_domain_executor_is_unchanged(three) -> None:
    three.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
    three.setenv("REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", PUBLIC_KEY)
    assert not effect_domain_split()
    with pytest.raises(CustodyViolation, match="missing effect credential"):
        assert_custody_split()
    three.setenv(EFFECT, "secret")
    assert assert_custody_split() == "executor"
    assert_may_hold_effect_executors()


def test_research_profile_is_unchanged(monkeypatch) -> None:
    monkeypatch.delenv("REMORA_RUNTIME_PROFILE", raising=False)
    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "effect")
    assert_may_hold_effect_executors()
    assert_may_hold_tool_callables()
