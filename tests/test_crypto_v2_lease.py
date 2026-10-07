# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""RMR-CR-011 (C1): ExecutionLease v2, domain-separated, under strict v2.

Before: a lease signs sorted compact JSON with no statement of what the bytes
are (``sig_alg`` ``ed25519`` or ``hmac-sha256``), and the HMAC path falls back
to the PDP key. Safety against cross-type forgery rested on disjoint field
sets. Probe at c8cc91d: under ``review/v2`` an authority still issues
untagged v1 leases, and the executor accepts them for live dispatch.

After: ExecutionLease v1 is frozen (its preimage and vectors are unchanged
under ``vectors/v1``). v2 signs ``REMORA/EXECUTION-LEASE/v2 || 0x00 ||
payload`` with Ed25519, names its key by the derived key id, and is the only
format a strict v2 contract issues or accepts for live dispatch. A v1 lease
stays verifiable as historical evidence, never as live authority.
"""
from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest

pytest.importorskip("cryptography")

from remora.crypto import SignatureDomain, SigningKey, derive_kid, preimage  # noqa: E402
from remora.enforcement import lease_signing as signing  # noqa: E402
from remora.enforcement.lease import ExecutionLease, GovernedToolDispatcher  # noqa: E402

SEED = "11" * 32
ARGS = {"id": "WO-1"}


def _public(seed: str = SEED) -> str:
    key = SigningKey.from_text(seed, [SignatureDomain.EXECUTION_LEASE]).verification_key()
    return key.public_bytes.hex()


@pytest.fixture
def authority(monkeypatch):
    """The authority half: Ed25519 seed, no HMAC lease key."""
    for name in (
        "REMORA_LEASE_SIGNING_KEY",
        "REMORA_PDP_SIGNING_KEY",
        "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC",
        "REMORA_LEASE_ACCEPT_HMAC",
        "REMORA_SIGNATURE_FORMAT",
        "REMORA_LEASE_SIGNING_KID",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE", SEED)
    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "authority")
    return monkeypatch


def _as_executor(monkeypatch) -> None:
    monkeypatch.delenv("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE")
    monkeypatch.setenv("REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", _public())
    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")


def _issue(**extra) -> ExecutionLease:
    return ExecutionLease.issue(
        decision="accept", tenant_id="acme", actor_identity="agent-1", tool_name="wo_close",
        arguments=ARGS, target_environment="prod", policy_bundle_hash="b1",
        issued_at=datetime.now(UTC).isoformat(), **extra)


# -- the domains -------------------------------------------------------------------

def test_the_v2_domains_are_the_approved_tags() -> None:
    assert SignatureDomain.POLICY_GRANT.value == "REMORA/POLICY-GRANT/v2"
    assert SignatureDomain.EXECUTION_LEASE.value == "REMORA/EXECUTION-LEASE/v2"
    assert SignatureDomain.AUDIT.value == "REMORA/AUDIT/v2"


# -- issuance ------------------------------------------------------------------------

def test_a_strict_v2_authority_issues_v2_leases(authority) -> None:
    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    lease = _issue()
    assert lease.sig_alg == signing.ALG_ED25519_V2
    assert lease.kid == derive_kid(bytes.fromhex(_public()))


def test_a_declared_kid_label_cannot_name_a_v2_lease(authority) -> None:
    """v2 names its key by the derived id; a configured label is not used."""
    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    authority.setenv("REMORA_LEASE_SIGNING_KID", "someone-else")
    assert _issue().kid == derive_kid(bytes.fromhex(_public()))


def test_the_v1_contract_keeps_issuing_frozen_v1_leases(authority) -> None:
    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v1")
    assert _issue().sig_alg == signing.ALG_ED25519


def test_research_keeps_v1_unless_v2_is_chosen(authority) -> None:
    authority.delenv("REMORA_RUNTIME_PROFILE", raising=False)
    assert _issue().sig_alg == signing.ALG_ED25519
    authority.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    assert _issue().sig_alg == signing.ALG_ED25519_V2


def test_v2_never_issues_hmac(authority) -> None:
    """v2 has no symmetric form: an authority without the seed refuses."""
    from remora.enforcement.lease import LeaseRefused

    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    authority.delenv("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE")
    authority.setenv("REMORA_LEASE_SIGNING_KEY", "hmac-key")
    with pytest.raises(LeaseRefused, match="Ed25519"):
        _issue()


def test_an_unknown_signature_format_is_refused(authority) -> None:
    authority.setenv("REMORA_SIGNATURE_FORMAT", "v3")
    with pytest.raises(ValueError, match="REMORA_SIGNATURE_FORMAT"):
        _issue()


# -- verification -----------------------------------------------------------------------

def test_a_v2_lease_verifies_with_the_public_key_only(authority) -> None:
    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    lease = _issue()
    _as_executor(authority)
    assert lease.verify_authenticity().verified


def test_the_signature_is_over_the_tagged_preimage(authority) -> None:
    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    lease = _issue()
    payload = ExecutionLease._canonical_payload(lease._signed_fields())
    from cryptography.hazmat.primitives.asymmetric import ed25519

    public = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(_public()))
    raw = base64.b64decode(lease.signature)
    public.verify(raw, preimage(SignatureDomain.EXECUTION_LEASE, payload))
    with pytest.raises(Exception):  # noqa: B017 - InvalidSignature
        public.verify(raw, payload)  # the untagged v1 preimage
    with pytest.raises(Exception):  # noqa: B017
        public.verify(raw, preimage(SignatureDomain.POLICY_GRANT, payload))


def test_a_v2_lease_cannot_be_relabelled_as_v1(authority) -> None:
    """sig_alg is signed: claiming v1 for v2 bytes breaks the signature."""
    import dataclasses

    authority.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    lease = _issue()
    authority.delenv("REMORA_SIGNATURE_FORMAT")
    relabelled = dataclasses.replace(lease, sig_alg=signing.ALG_ED25519)
    assert relabelled.verify_authenticity().reason == "signature_invalid"


def test_a_v2_lease_with_a_swapped_kid_refuses(authority) -> None:
    import dataclasses

    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    lease = _issue()
    _as_executor(authority)
    other = derive_kid(bytes.fromhex(_public("22" * 32)))
    assert dataclasses.replace(lease, kid=other).verify_authenticity().reason == (
        "signature_invalid")


def test_a_v1_lease_is_refused_for_live_authority_under_strict_v2(authority) -> None:
    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v1")
    legacy = _issue()
    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    _as_executor(authority)
    assert legacy.verify_authenticity().reason == "lease_format_legacy"


def test_a_v1_lease_stays_readable_as_historical_evidence(authority) -> None:
    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v1")
    legacy = _issue()
    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    _as_executor(authority)
    historical = legacy.verify_historical()
    assert historical.verified and historical.reason == "historical_v1"
    assert _issue_v2_as_authority(authority).verify_historical().reason == "ok"


def _issue_v2_as_authority(monkeypatch) -> ExecutionLease:
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE", SEED)
    monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "authority")
    lease = _issue()
    _as_executor(monkeypatch)
    return lease


def test_a_legacy_lease_is_refused_before_the_nonce_is_spent(authority) -> None:
    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v1")
    legacy = _issue()
    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    _as_executor(authority)
    dispatcher = GovernedToolDispatcher("b1")
    dispatcher.register("wo_close", lambda args: "ok")
    result = dispatcher.dispatch(legacy, "wo_close", ARGS, tenant_id="acme",
                                 target_environment="prod", actor_identity="agent-1")
    assert result.refusal_reason == "lease_format_legacy"
    assert legacy.nonce not in dispatcher._ledger._consumed


def test_research_still_accepts_v1_and_v2(authority) -> None:
    authority.delenv("REMORA_RUNTIME_PROFILE", raising=False)
    v1 = _issue()
    authority.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    v2 = _issue()
    authority.delenv("REMORA_SIGNATURE_FORMAT")
    assert v1.verify_authenticity().verified and v2.verify_authenticity().verified


def test_a_tampered_v2_lease_refuses(authority) -> None:
    import dataclasses

    authority.setenv("REMORA_RUNTIME_PROFILE", "review/v2")
    lease = _issue()
    _as_executor(authority)
    assert dataclasses.replace(lease, tool_name="wire_transfer").verify_authenticity().reason == (
        "signature_invalid")
    assert dataclasses.replace(lease, signature="!!").verify_authenticity().reason == (
        "signature_invalid")


# -- startup -----------------------------------------------------------------------

@pytest.fixture
def strict(monkeypatch, tmp_path):
    """The scaffold's authority, review/v2."""
    import shlex

    from remora.scaffold import init_review

    monkeypatch.chdir(tmp_path)
    init_review(tmp_path / ".remora")
    for name in (
        "REMORA_TOOLSPEC_SIGNING_KEY",
        "REMORA_LEASE_SIGNING_KEY",
        "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC",
        "REMORA_PG_DSN",
        "REMORA_SIGNATURE_FORMAT",
    ):
        monkeypatch.delenv(name, raising=False)
    text = (tmp_path / ".remora" / "authority.env").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("export "):
            key, _, raw = line[len("export "):].partition("=")
            monkeypatch.setenv(key, shlex.split(raw)[0])
    monkeypatch.syspath_prepend(str(tmp_path / ".remora"))


def _validate():
    from remora.toolcall.runtime_profile import validate_runtime_profile_prerequisites

    return validate_runtime_profile_prerequisites()


def test_a_v2_authority_needs_the_ed25519_lease_seed(strict, monkeypatch) -> None:
    from remora.profiles import RuntimeProfileError

    monkeypatch.delenv("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE")
    with pytest.raises(RuntimeProfileError, match="REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE"):
        _validate()


def test_a_v2_contract_refuses_a_request_for_v1_signatures(strict, monkeypatch) -> None:
    from remora.profiles import RuntimeProfileError

    monkeypatch.setenv("REMORA_SIGNATURE_FORMAT", "v1")
    with pytest.raises(RuntimeProfileError, match="signature format v2 only"):
        _validate()


def test_the_scaffold_authority_starts_under_signature_format_v2(strict) -> None:
    assert _validate() == "review"


# -- material that cannot reach a verdict ------------------------------------------------

def test_v2_signing_without_the_seed_raises(authority) -> None:
    authority.delenv("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE")
    with pytest.raises(signing.SigningUnavailable, match="cannot mint"):
        signing.sign_payload(b"{}", alg=signing.ALG_ED25519_V2)


def test_a_v2_lease_without_verification_material_is_unverifiable(authority) -> None:
    authority.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    lease = _issue()
    authority.delenv("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE")
    assert lease.verify_authenticity().reason == "no_signing_key"
    assert lease.verify_historical().reason == "no_signing_key"


def test_an_unsigned_lease_is_no_historical_evidence(authority) -> None:
    import dataclasses

    authority.setenv("REMORA_SIGNATURE_FORMAT", "v2")
    unsigned = dataclasses.replace(_issue(), signature="", is_signed=False)
    assert unsigned.verify_historical().reason == "lease_not_signed"
