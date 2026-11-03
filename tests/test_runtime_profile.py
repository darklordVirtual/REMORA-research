# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import sys
import types

import pytest

from remora.toolcall.runtime_profile import (
    RuntimeProfileError,
    current_runtime_profile,
    validate_runtime_profile_prerequisites,
)


STRICT_ENV = {
    "REMORA_TOOLSPEC_BUNDLE": "/tmp/toolspec.json",
    # RMR-CR-001: Ed25519 verification keys and a pinned digest, never the
    # HMAC signing key, in a strict runtime.
    "REMORA_TOOLSPEC_VERIFY_KEYS": "11" * 32,
    "REMORA_TOOLSPEC_PINNED_DIGEST": "ab" * 32,
    # CR-006: a bare strict profile is contract v2, which needs a BindingPolicy
    # and, for resolved_effect REQUIRED, a configured effect registry.
    "REMORA_BINDING_POLICY": str(
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "deploy" / "reference" / "binding-policy-v2.yaml"),
    "REMORA_EFFECT_REGISTRY_MODULE": "example.effects",
    "REMORA_TOOL_REGISTRY_MODULE": "example.registry",
    "REMORA_CHAIN_DB": "/tmp/remora-execution.db",
    "REMORA_PDP_SIGNING_KEY": "a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
    # RMR-CR-003: tenant and role come from a credential table.
    "REMORA_API_TOKENS": '{"tok": {"tenant": "acme", "role": "operator"}}',
    # Property E: the strict profiles now compel the ADR-A custody split, so a
    # strict configuration must say which half of it this process is. The
    # authority role keeps the prerequisites this suite already asserted.
    "REMORA_EXECUTION_DOMAIN_ROLE": "authority",
    "REMORA_EFFECT_CREDENTIAL_ENV_NAMES": "ACME_SMTP_PASSWORD",
    # Property D: strict profiles require an intent resolver.
    "REMORA_SEMANTIC_BUNDLE_MODULE": "servers.semantic_bundle_research",
    # CAP-031: controlled_pilot runs with signed, mandatory cumulative limits
    # and an idempotency key per metered write tool. Presence only here; the
    # execution API verifies the policy when it builds the guard.
    "REMORA_LIMITS_FILE": "/tmp/limits.json",
    "REMORA_LIMITS_LEDGER": "/tmp/limits-ledger.db",
    "REMORA_LIMITS_TRUSTED_KEYS": "22" * 32,
    "REMORA_REQUIRE_LIMITS": "1",
    "REMORA_REQUIRE_IDEMPOTENCY": "1",
}


def _clear(monkeypatch) -> None:
    for name in (
        "REMORA_RUNTIME_PROFILE",
        "REMORA_ENV",
        "REMORA_TOOLSPEC_BUNDLE",
        "REMORA_TOOLSPEC_SIGNING_KEY",
        "REMORA_TOOLSPEC_TRUSTED_IDENTITIES",
        "REMORA_TOOLSPEC_VERIFY_KEYS",
        "REMORA_TOOLSPEC_PINNED_DIGEST",
        "REMORA_BINDING_POLICY",
        "REMORA_EFFECT_REGISTRY_MODULE",
        "REMORA_TOOL_REGISTRY_MODULE",
        "REMORA_PG_DSN",
        "REMORA_CHAIN_DB",
        "REMORA_PDP_SIGNING_KEY",
        "REMORA_API_TOKENS",
        "REMORA_EXECUTION_DOMAIN_ROLE",
        "REMORA_EFFECT_CREDENTIAL_ENV_NAMES",
        "ACME_SMTP_PASSWORD",
        "REMORA_SEMANTIC_BUNDLE_MODULE",
        "REMORA_LIMITS_FILE",
        "REMORA_LIMITS_LEDGER",
        "REMORA_LIMITS_TRUSTED_KEYS",
        "REMORA_REQUIRE_LIMITS",
        "REMORA_REQUIRE_IDEMPOTENCY",
        "REMORA_WS1_MODE",
        "REMORA_WS1_ADMISSION",
    ):
        monkeypatch.delenv(name, raising=False)


def _configure_strict(monkeypatch, profile: str = "review") -> None:
    # This suite pins the v1 prerequisites. The v2 contract (BindingPolicy,
    # effect mediation) needs a real signed bundle and is covered end to end
    # through the scaffold in tests/test_binding_policy.py.
    if "/" not in profile:
        profile = f"{profile}/v1"
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", profile)
    for key, value in STRICT_ENV.items():
        monkeypatch.setenv(key, value)


def test_unset_profile_is_compatibility_research(monkeypatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("REMORA_ENV", "production")
    assert current_runtime_profile() == "research"
    assert validate_runtime_profile_prerequisites() == "research"


def test_profile_aliases_are_normalized(monkeypatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "external_review")
    assert current_runtime_profile() == "review"
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "pilot")
    assert current_runtime_profile() == "controlled_pilot"


def test_unknown_profile_is_refused(monkeypatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "looks-secure")
    with pytest.raises(RuntimeProfileError, match="is unknown"):
        current_runtime_profile()


def test_review_refuses_unsigned_volatile_legacy_path(monkeypatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "review")
    with pytest.raises(RuntimeProfileError) as exc:
        validate_runtime_profile_prerequisites()
    text = str(exc.value)
    assert "REMORA_TOOLSPEC_BUNDLE" in text
    assert "REMORA_TOOLSPEC_VERIFY_KEYS" in text
    assert "REMORA_TOOLSPEC_PINNED_DIGEST" in text
    # The HMAC key is no longer a prerequisite: requiring it would put the
    # material that authors bundles into the process that verifies them.
    assert "REMORA_TOOLSPEC_SIGNING_KEY" not in text
    assert "REMORA_PG_DSN (or REMORA_CHAIN_DB)" in text
    assert "REMORA_PDP_SIGNING_KEY" in text


@pytest.mark.parametrize("profile", ["review", "controlled_pilot"])
@pytest.mark.parametrize("role", ["authority", "executor"])
def test_strict_profile_refuses_a_runtime_holding_the_toolspec_signing_key(
    monkeypatch, profile: str, role: str
) -> None:
    """RMR-CR-001: an HMAC verifier can author every bundle it accepts."""
    _clear(monkeypatch)
    _configure_strict(monkeypatch, profile)
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", role)
    monkeypatch.setenv("REMORA_TOOLSPEC_SIGNING_KEY", "authoring-material")
    with pytest.raises(RuntimeProfileError, match="REMORA_TOOLSPEC_SIGNING_KEY"):
        validate_runtime_profile_prerequisites()


@pytest.mark.parametrize("missing", [
    "REMORA_TOOLSPEC_VERIFY_KEYS", "REMORA_TOOLSPEC_PINNED_DIGEST",
])
def test_strict_profile_requires_verify_keys_and_a_pinned_digest(
    monkeypatch, missing: str
) -> None:
    _clear(monkeypatch)
    _configure_strict(monkeypatch, "review")
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeProfileError, match=missing):
        validate_runtime_profile_prerequisites()


def test_review_accepts_signed_and_durable_configuration(monkeypatch) -> None:
    _clear(monkeypatch)
    _configure_strict(monkeypatch, "review")
    monkeypatch.setenv("REMORA_ENV", "development")
    assert validate_runtime_profile_prerequisites() == "review"


def test_controlled_pilot_requires_production_environment(monkeypatch) -> None:
    _clear(monkeypatch)
    _configure_strict(monkeypatch, "controlled_pilot")
    monkeypatch.setenv("REMORA_ENV", "development")
    with pytest.raises(RuntimeProfileError, match="REMORA_ENV=production"):
        validate_runtime_profile_prerequisites()


def test_controlled_pilot_accepts_full_production_configuration(monkeypatch) -> None:
    _clear(monkeypatch)
    _configure_strict(monkeypatch, "controlled_pilot")
    monkeypatch.setenv("REMORA_ENV", "production")
    assert validate_runtime_profile_prerequisites() == "controlled_pilot"


@pytest.mark.parametrize("missing", [
    "REMORA_LIMITS_FILE", "REMORA_LIMITS_LEDGER", "REMORA_LIMITS_TRUSTED_KEYS",
    "REMORA_REQUIRE_LIMITS", "REMORA_REQUIRE_IDEMPOTENCY",
])
def test_controlled_pilot_requires_signed_mandatory_limits(monkeypatch, missing) -> None:
    """CAP-031, SDD P0 item 3: a write pilot cannot start against no budget."""
    _clear(monkeypatch)
    _configure_strict(monkeypatch, "controlled_pilot")
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeProfileError, match=f"cumulative limits.*{missing}"):
        validate_runtime_profile_prerequisites()


def test_review_does_not_require_limits(monkeypatch) -> None:
    """The handoff profile reviews the path; only the write pilot must run with a budget."""
    _clear(monkeypatch)
    _configure_strict(monkeypatch, "review")
    monkeypatch.setenv("REMORA_ENV", "development")
    for name in ("REMORA_LIMITS_FILE", "REMORA_LIMITS_LEDGER", "REMORA_LIMITS_TRUSTED_KEYS",
                 "REMORA_REQUIRE_LIMITS", "REMORA_REQUIRE_IDEMPOTENCY"):
        monkeypatch.delenv(name)
    assert validate_runtime_profile_prerequisites() == "review"


def test_deployment_registry_wires_the_profile_gate(monkeypatch) -> None:
    """The handoff profile check is on the execution metadata path, not docs only."""
    _clear(monkeypatch)
    monkeypatch.setenv("REMORA_RUNTIME_PROFILE", "review")

    from remora.toolcall.deployment_registry import resolve_tool_metadata

    # The profile refusal happens before execution_api is imported/resolved.
    with pytest.raises(RuntimeProfileError):
        resolve_tool_metadata("safe_read")

    _configure_strict(monkeypatch, "review")
    fake = types.ModuleType("servers.execution_api")
    fake.TOOL_REGISTRY = {
        "safe_read": {
            "risk_tier": "low",
            "domain": "test",
            "action_type": "read",
        }
    }
    monkeypatch.setitem(sys.modules, "servers.execution_api", fake)
    metadata, declared = resolve_tool_metadata("safe_read")
    assert declared is True
    assert metadata["risk_tier"] == "low"


def test_strict_profile_requires_an_intent_resolver(monkeypatch) -> None:
    """Property D: without a resolver every call would abstain; refuse at startup."""
    _clear(monkeypatch)
    _configure_strict(monkeypatch, "review")
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    with pytest.raises(RuntimeProfileError, match="intent resolver"):
        validate_runtime_profile_prerequisites()


def test_controlled_pilot_on_postgres_requires_a_shared_limit_ledger(monkeypatch) -> None:
    """SDD §7.1 / G04: shared authority state with a host-local budget lets each executor spend it all."""
    _clear(monkeypatch)
    _configure_strict(monkeypatch, "controlled_pilot")
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.delenv("REMORA_CHAIN_DB")
    monkeypatch.setenv("REMORA_PG_DSN", "postgresql://remora@db/remora")
    with pytest.raises(RuntimeProfileError, match="REMORA_LIMITS_LEDGER must be a PostgreSQL DSN"):
        validate_runtime_profile_prerequisites()
    monkeypatch.setenv("REMORA_LIMITS_LEDGER", "postgresql://remora@db/remora")
    assert validate_runtime_profile_prerequisites() == "controlled_pilot"


def _strict_profile(monkeypatch, profile: str) -> None:
    _clear(monkeypatch)
    _configure_strict(monkeypatch, profile)
    monkeypatch.setenv("REMORA_ENV", "production")


@pytest.mark.parametrize("profile", ["review", "controlled_pilot"])
@pytest.mark.parametrize("admission", [None, "legacy", "LEGACY "])
def test_a_strict_profile_enforcing_ws1_refuses_legacy_admission(monkeypatch, profile, admission) -> None:
    """RMR-AUD-26-003: on legacy, evidence that lapses after the WS1 re-gate is
    still spent (control 2b). The ADR says the strict profile must refuse it."""
    _strict_profile(monkeypatch, profile)
    monkeypatch.setenv("REMORA_WS1_MODE", "enforce")
    if admission is not None:
        monkeypatch.setenv("REMORA_WS1_ADMISSION", admission)
    with pytest.raises(RuntimeProfileError, match="REMORA_WS1_ADMISSION=atomic"):
        validate_runtime_profile_prerequisites()


@pytest.mark.parametrize("profile", ["review", "controlled_pilot"])
def test_a_strict_profile_enforcing_ws1_accepts_atomic_admission(monkeypatch, profile) -> None:
    _strict_profile(monkeypatch, profile)
    monkeypatch.setenv("REMORA_WS1_MODE", "enforce")
    monkeypatch.setenv("REMORA_WS1_ADMISSION", "atomic")
    assert validate_runtime_profile_prerequisites() == profile


def test_an_unknown_admission_value_is_refused_by_the_profile_too(monkeypatch) -> None:
    _strict_profile(monkeypatch, "controlled_pilot")
    monkeypatch.setenv("REMORA_WS1_MODE", "enforce")
    monkeypatch.setenv("REMORA_WS1_ADMISSION", "fast")
    with pytest.raises(RuntimeProfileError, match="got 'fast'"):
        validate_runtime_profile_prerequisites()


@pytest.mark.parametrize("mode", [None, "off", "shadow"])
def test_ws1_off_or_shadow_keeps_legacy_under_a_strict_profile(monkeypatch, mode) -> None:
    """Shadow leaves the decision unchanged (Ws1Gate.apply), so legacy admits
    nothing on WS1 evidence there."""
    _strict_profile(monkeypatch, "controlled_pilot")
    if mode is not None:
        monkeypatch.setenv("REMORA_WS1_MODE", mode)
    assert validate_runtime_profile_prerequisites() == "controlled_pilot"


def test_the_research_profile_keeps_legacy_with_ws1_enforcing(monkeypatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("REMORA_WS1_MODE", "enforce")
    assert validate_runtime_profile_prerequisites() == "research"
