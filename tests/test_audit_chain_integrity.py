# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The tenant audit chain fails loudly instead of restarting quietly.

Three defects closed here shared one shape: a lookup or input that could not
be understood was treated as "nothing to link to", which restarts the chain
at genesis with no signal — the precise tampering shape the chain exists to
expose.
"""
from __future__ import annotations

import pytest

import servers.api as api


class _Store:
    """Minimal control-plane stand-in returning a scripted latest record."""

    def __init__(self, latest: object) -> None:
        self._latest = latest

    def get_latest_audit_record_for_tenant(self, *, tenant_id: str) -> object:
        return self._latest


def _with_store(monkeypatch: pytest.MonkeyPatch, latest: object) -> None:
    monkeypatch.setattr(api, "_CONTROL_PLANE_STORE", _Store(latest))


def test_absent_record_is_genesis(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_store(monkeypatch, None)
    assert api._latest_tenant_audit_hash("tenant-a") is None


def test_envelope_hash_is_preferred_then_state_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_store(monkeypatch, {"envelope_audit_hash": "aa", "state_hash": "bb"})
    assert api._latest_tenant_audit_hash("t") == "aa"
    _with_store(monkeypatch, {"state_hash": "bb"})
    assert api._latest_tenant_audit_hash("t") == "bb"


def test_malformed_record_raises_instead_of_restarting_the_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row with no linkable hash is a broken chain, not a new one."""
    _with_store(monkeypatch, {"unexpected": "shape"})
    with pytest.raises(api.AuditChainLookupError):
        api._latest_tenant_audit_hash("t")


def test_non_mapping_lookup_result_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for bad in ("a string", 42, ["list"]):
        _with_store(monkeypatch, bad)
        with pytest.raises(api.AuditChainLookupError):
            api._latest_tenant_audit_hash("t")


def test_blank_hashes_are_not_accepted_as_a_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_store(monkeypatch, {"envelope_audit_hash": "   ", "state_hash": ""})
    with pytest.raises(api.AuditChainLookupError):
        api._latest_tenant_audit_hash("t")


def test_non_dict_payload_cannot_be_chain_hashed() -> None:
    """Every malformed envelope used to hash to the same value."""
    for bad in (None, "envelope", 7, ["audit"]):
        with pytest.raises(TypeError):
            api._canonical_envelope_for_hash(bad)  # type: ignore[arg-type]


def test_distinct_payloads_hash_distinctly() -> None:
    a = api._compute_envelope_chain_hash(
        previous_hash=None, envelope_payload={"decision": "accept"}
    )
    b = api._compute_envelope_chain_hash(
        previous_hash=None, envelope_payload={"decision": "verify"}
    )
    assert a != b


def test_genesis_flag_is_excluded_from_the_hash_preimage() -> None:
    """Adding the marker must not change any committed chain hash.

    ``genesis`` is derived from ``previous_hash``, which the preimage already
    carries as a prefix. Hashing it too would rewrite every envelope hash and
    break the tenant chains recorded before this field existed.
    """
    without = api._compute_envelope_chain_hash(
        previous_hash="prev", envelope_payload={"audit": {"policy_version": "v3"}}
    )
    with_flag = api._compute_envelope_chain_hash(
        previous_hash="prev",
        envelope_payload={"audit": {"policy_version": "v3", "genesis": True}},
    )
    assert without == with_flag


# ---------------------------------------------------------------------------
# production prerequisites: an unsigned chain is not a tamper-evident chain
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "omitted",
    ["REMORA_ENVELOPE_SIGNING_KEY", "REMORA_PDP_SIGNING_KEY",
     "REMORA_LEASE_SIGNING_KEY"],
)
def test_production_refuses_to_start_without_a_signing_key(
    monkeypatch: pytest.MonkeyPatch, omitted: str, tmp_path
) -> None:
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "tok")
    monkeypatch.setenv("REMORA_CONTROL_PLANE_DSN", "postgresql://localhost/remora")
    # A durable path the guard accepts on any machine: /tmp is tmpfs on many
    # Linux installs and disk on the GitHub runners, so the old literal made
    # this test pass in CI and fail locally (external review 2026-08-30, F2).
    # The filesystem probe has its own coverage in
    # tests/test_ephemeral_durable_state.py; this test is about a different
    # prerequisite and only needs to get past the durability one.
    monkeypatch.setattr(api, "filesystem_type_for", lambda _path: "ext4")
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "chain.db"))
    monkeypatch.setenv("REMORA_ORACLE_BACKEND", "groq")
    monkeypatch.setenv("REMORA_API_TOKENS", '{"t":{"tenant":"t","role":"operator"}}')
    monkeypatch.setenv("REMORA_ENVELOPE_SIGNING_KEY", "envelope-key")
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "lease-key")
    monkeypatch.delenv(omitted, raising=False)

    with pytest.raises(RuntimeError, match=omitted):
        api._validate_production_prerequisites()


def test_production_starts_when_every_signing_key_is_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "tok")
    monkeypatch.setenv("REMORA_CONTROL_PLANE_DSN", "postgresql://localhost/remora")
    # A durable path the guard accepts on any machine: /tmp is tmpfs on many
    # Linux installs and disk on the GitHub runners, so the old literal made
    # this test pass in CI and fail locally (external review 2026-08-30, F2).
    # The filesystem probe has its own coverage in
    # tests/test_ephemeral_durable_state.py; this test is about a different
    # prerequisite and only needs to get past the durability one.
    monkeypatch.setattr(api, "filesystem_type_for", lambda _path: "ext4")
    monkeypatch.setenv("REMORA_CHAIN_DB", str(tmp_path / "chain.db"))
    monkeypatch.setenv("REMORA_ORACLE_BACKEND", "groq")
    monkeypatch.setenv("REMORA_API_TOKENS", '{"t":{"tenant":"t","role":"operator"}}')
    monkeypatch.setenv("REMORA_ENVELOPE_SIGNING_KEY", "envelope-key")
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "lease-key")
    monkeypatch.delenv("REMORA_API_ALLOW_MOCK_ORACLES", raising=False)

    api._validate_production_prerequisites()
