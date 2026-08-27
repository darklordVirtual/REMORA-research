# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The custody split as a prerequisite, not a convention (property E).

``test_execution_boundary.py`` demonstrates that a single process cannot
enforce an execution boundary: the callable can be extracted (B3) and the
environment is ambient (B4). Neither is fixable inside the dispatcher.

What this module tests is the response: under a strict runtime profile the
configuration in which those bypasses matter is refused outright. The
question moves from "can the boundary be crossed in one process" (it can) to
"can one process be configured to serve as the boundary" (it cannot).

Case identifiers used in the conformance assessment:

    K1  an unset domain role is refused under a strict profile
    K2  an authority process holding an effect credential is refused
    K3  an executor process holding lease signing material is refused
    K4  an executor without verification material is refused
    K5  an executor missing its declared effect credential is refused
    K6  an empty effect-credential declaration is refused as vacuous
    K7  the authority domain cannot register tool callables
    K8  the execution domain cannot mint a lease
    K9  a correctly split deployment is accepted
    K10 none of this changes the research profile
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from remora.enforcement.custody import (
    CustodyViolation,
    assert_custody_split,
    assert_may_hold_tool_callables,
    assert_may_mint_authority,
    declared_effect_credentials,
    domain_role,
)
from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher

STRICT = "review"
EFFECT = "ACME_SMTP_PASSWORD"
PUBLIC_KEY = "a" * 64
BUNDLE = "d" * 64


@pytest.fixture
def strict(monkeypatch: pytest.MonkeyPatch):
    """A strict profile with nothing else configured; tests add their own."""
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", STRICT)
    monkeypatch.setenv("REMORA_EFFECT_CREDENTIAL_ENV_NAMES", EFFECT)
    for name in (
        "REMORA_EXECUTION_DOMAIN_ROLE",
        EFFECT,
        "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
        "REMORA_LEASE_SIGNING_KEY",
        "REMORA_PDP_SIGNING_KEY",
        "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _authority(strict: pytest.MonkeyPatch) -> None:
    strict.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "authority")


def _executor(strict: pytest.MonkeyPatch) -> None:
    strict.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
    strict.setenv("REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", PUBLIC_KEY)
    strict.setenv(EFFECT, "the-real-downstream-secret")


def test_k1_unset_role_is_refused_under_a_strict_profile(strict) -> None:
    with pytest.raises(CustodyViolation) as caught:
        assert_custody_split()
    assert "REMORA_EXECUTION_DOMAIN_ROLE" in str(caught.value)


def test_k2_authority_holding_an_effect_credential_is_refused(strict) -> None:
    _authority(strict)
    strict.setenv(EFFECT, "leaked-into-the-authority-process")
    with pytest.raises(CustodyViolation) as caught:
        assert_custody_split()
    assert EFFECT in str(caught.value)


def test_k3_executor_holding_signing_material_is_refused(strict) -> None:
    """The split is decorative if the verifier can also sign."""
    _executor(strict)
    strict.setenv("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE", "b" * 64)
    with pytest.raises(CustodyViolation) as caught:
        assert_custody_split()
    assert "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE" in str(caught.value)


@pytest.mark.parametrize(
    "env", ["REMORA_LEASE_SIGNING_KEY", "REMORA_PDP_SIGNING_KEY"]
)
def test_k3_executor_refuses_every_signing_variant(strict, env: str) -> None:
    """A guard that only knew about Ed25519 would miss the HMAC deployment."""
    _executor(strict)
    strict.setenv(env, "symmetric-key-material")
    with pytest.raises(CustodyViolation) as caught:
        assert_custody_split()
    assert env in str(caught.value)


def test_k4_executor_without_verification_material_is_refused(strict) -> None:
    _executor(strict)
    strict.delenv("REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC")
    with pytest.raises(CustodyViolation) as caught:
        assert_custody_split()
    assert "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC" in str(caught.value)


def test_k5_executor_missing_its_effect_credential_is_refused(strict) -> None:
    _executor(strict)
    strict.delenv(EFFECT)
    with pytest.raises(CustodyViolation) as caught:
        assert_custody_split()
    assert "not have" in str(caught.value)


def test_k6_empty_effect_declaration_is_refused_as_vacuous(strict) -> None:
    """A guard with nothing to check would pass every deployment."""
    _authority(strict)
    strict.setenv("REMORA_EFFECT_CREDENTIAL_ENV_NAMES", "  ,  ")
    assert declared_effect_credentials() == ()
    with pytest.raises(CustodyViolation) as caught:
        assert_custody_split()
    assert "at least one effect credential" in str(caught.value)


def test_k7_authority_cannot_register_tool_callables(strict) -> None:
    """B3's configuration, refused before it can exist."""
    _authority(strict)
    with pytest.raises(CustodyViolation):
        assert_may_hold_tool_callables()

    dispatcher = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE)
    with pytest.raises(CustodyViolation):
        dispatcher.register("send_mail", lambda _args: "sent")
    assert dispatcher._tools == {}


def test_k8_executor_cannot_mint_a_lease(strict) -> None:
    _executor(strict)
    with pytest.raises(CustodyViolation):
        assert_may_mint_authority()

    with pytest.raises(CustodyViolation):
        ExecutionLease.issue(
            decision="accept",
            tenant_id="t1",
            actor_identity="agent-1",
            tool_name="send_mail",
            arguments={"to": "a@example.com"},
            target_environment="prod",
            policy_bundle_hash=BUNDLE,
            issued_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(
                datetime.now(timezone.utc) + timedelta(minutes=5)
            ).isoformat(),
        )


def test_k9_a_correctly_split_deployment_is_accepted(strict) -> None:
    """The guard must permit the configuration it is asking for."""
    _executor(strict)
    assert assert_custody_split() == "executor"
    assert_may_hold_tool_callables()

    dispatcher = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE)
    dispatcher.register("send_mail", lambda _args: "sent")
    assert "send_mail" in dispatcher._tools

    strict.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "authority")
    strict.delenv(EFFECT)
    assert assert_custody_split() == "authority"
    assert_may_mint_authority()


def test_k10_research_profile_is_unchanged(monkeypatch) -> None:
    """The weak configurations stay available where they are honest.

    Research and library use are explicitly supported, and a guard that
    broke them would push users onto the strict profile without the
    infrastructure it requires.
    """
    monkeypatch.delenv("REMORA_RUNTIME_PROFILE", raising=False)
    monkeypatch.delenv("REMORA_EXECUTION_DOMAIN_ROLE", raising=False)
    monkeypatch.delenv("REMORA_EFFECT_CREDENTIAL_ENV_NAMES", raising=False)

    assert domain_role() == "authority"
    assert assert_custody_split() == "authority"
    assert_may_hold_tool_callables()
    assert_may_mint_authority()

    dispatcher = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE)
    dispatcher.register("send_mail", lambda _args: "sent")
    assert "send_mail" in dispatcher._tools


def test_k11_unknown_role_is_refused_rather_than_guessed(strict) -> None:
    strict.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "excutor")
    with pytest.raises(CustodyViolation) as caught:
        assert_custody_split()
    assert "excutor" in str(caught.value)
