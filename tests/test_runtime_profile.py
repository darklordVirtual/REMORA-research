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
    "REMORA_TOOL_REGISTRY_MODULE": "example.registry",
    "REMORA_CHAIN_DB": "/tmp/remora-execution.db",
    "REMORA_PDP_SIGNING_KEY": "test-pdp-key",
    # Property E: the strict profiles now compel the ADR-A custody split, so a
    # strict configuration must say which half of it this process is. The
    # authority role keeps the prerequisites this suite already asserted.
    "REMORA_EXECUTION_DOMAIN_ROLE": "authority",
    "REMORA_EFFECT_CREDENTIAL_ENV_NAMES": "ACME_SMTP_PASSWORD",
    # Property D: strict profiles require an intent resolver.
    "REMORA_SEMANTIC_BUNDLE_MODULE": "servers.semantic_bundle_research",
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
        "REMORA_TOOL_REGISTRY_MODULE",
        "REMORA_PG_DSN",
        "REMORA_CHAIN_DB",
        "REMORA_PDP_SIGNING_KEY",
        "REMORA_EXECUTION_DOMAIN_ROLE",
        "REMORA_EFFECT_CREDENTIAL_ENV_NAMES",
        "ACME_SMTP_PASSWORD",
        "REMORA_SEMANTIC_BUNDLE_MODULE",
    ):
        monkeypatch.delenv(name, raising=False)


def _configure_strict(monkeypatch, profile: str = "review") -> None:
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
