# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The PDP->PEP custody boundary: a verifier must not be able to mint (ADR-A).

Found by reading the deployed Cloudflare gateway against its own architecture
diagram. `workers/mcp-gateway/src/index.ts` hands the execution container
REMORA_LEASE_SIGNING_KEY and REMORA_PDP_SIGNING_KEY as ordinary secrets, and
ExecutionLease signed and verified with HMAC under that same key. So the
component that ENFORCES an authorization also held the material to AUTHOR one.
Compromise of the executing container was not merely a replay risk; it was an
authority-forgery risk, and no test said so.

The first crosswalk recorded the opposite — "no credential exists in the
container" — as one of REMORA's strongest properties. It was the claim made
with the most confidence and the least evidence. These tests exist so that the
property is asserted by an attack rather than by a sentence.

The attack is the point: a process holding EVERY piece of verification material
available to the PEP attempts to mint a valid ACCEPT lease for an action nobody
assessed. Under Ed25519 it must fail cryptographically, not by policy.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.enforcement import lease_signing as signing  # noqa: E402
from remora.enforcement.lease import ExecutionLease, LeaseRefused  # noqa: E402

pytest.importorskip(
    "cryptography",
    reason="Ed25519 lease signing needs the optional 'security' extra",
)

from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402

ISSUED = datetime.now(UTC).isoformat()
CALL = {"tool_name": "wo_close", "arguments": {"id": "WO-1"},
        "tenant_id": "acme", "target_environment": "staging"}


def _keypair() -> tuple[str, str]:
    private = ed25519.Ed25519PrivateKey.generate()
    seed = private.private_bytes_raw().hex()
    public = private.public_key().public_bytes_raw().hex()
    return seed, public


@pytest.fixture()
def pdp(monkeypatch):
    """A process with the private key: the PDP. It may mint."""
    seed, public = _keypair()
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, seed)
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, public)
    monkeypatch.delenv(signing.ENV_HMAC, raising=False)
    monkeypatch.delenv(signing.ENV_HMAC_FALLBACK, raising=False)
    return seed, public


def _issue() -> ExecutionLease:
    return ExecutionLease.issue(
        decision="accept", actor_identity="agent-1",
        policy_bundle_hash="bundle-1", issued_at=ISSUED, **CALL)


def _verify(lease: ExecutionLease):
    return lease.verify(now=ISSUED, actor_identity="agent-1", **CALL)


def test_the_pdp_issues_ed25519_when_a_private_key_is_present(pdp):
    lease = _issue()
    assert lease.is_signed is True
    assert lease.sig_alg == signing.ALG_ED25519
    assert _verify(lease).verified is True


def test_a_verifier_holding_only_the_public_key_cannot_mint(monkeypatch, pdp):
    """The property, attacked directly.

    This is the compromised-container scenario: the attacker has everything
    the PEP has. Every piece of it verifies, and none of it signs.
    """
    _seed, public = pdp
    genuine = _issue()

    # Strip the container down to exactly what a verifier needs.
    monkeypatch.delenv(signing.ENV_ED25519_PRIVATE, raising=False)
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, public)

    assert signing.public_key_only() is True
    assert _verify(genuine).verified is True, (
        "the compromised component must still be able to do its job")

    # Now try to author authority for an action nobody assessed.
    # Refused as LeaseRefused rather than SigningUnavailable: the first version
    # of this test caught issue() silently emitting an UNSIGNED lease here.
    with pytest.raises(LeaseRefused):
        ExecutionLease.issue(
            decision="accept", actor_identity="agent-1",
            tool_name="wo_delete_all", arguments={},
            tenant_id="acme", target_environment="prod",
            policy_bundle_hash="bundle-1", issued_at=ISSUED)


def test_a_forged_signature_from_the_wrong_key_is_refused(monkeypatch, pdp):
    """Having *a* private key is not having *the* private key."""
    genuine = _issue()
    attacker_seed, _ = _keypair()
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, attacker_seed)

    forged_sig = signing.sign_payload(
        ExecutionLease._canonical_payload(genuine._signed_fields()),
        alg=signing.ALG_ED25519)
    forged = ExecutionLease(**{**genuine.to_dict(), "signature": forged_sig})

    monkeypatch.delenv(signing.ENV_ED25519_PRIVATE, raising=False)
    assert _verify(forged).verified is False
    assert _verify(forged).reason == "signature_invalid"


def test_the_algorithm_cannot_be_downgraded(monkeypatch, pdp):
    """sig_alg is inside the signed payload, so stripping it breaks the signature.

    Without this, an attacker who learned the old symmetric key could relabel
    an Ed25519 lease as HMAC and have it verify under a key the container still
    holds — the downgrade window doing the attacker's work for them.
    """
    lease = _issue()
    monkeypatch.setenv(signing.ENV_HMAC, "the-old-shared-secret")
    monkeypatch.setenv(signing.ENV_ACCEPT_HMAC, "1")

    downgraded = ExecutionLease(
        **{**lease.to_dict(), "sig_alg": signing.ALG_HMAC})
    assert _verify(downgraded).verified is False, (
        "relabelling the algorithm must not produce a verifiable lease")


def test_hmac_is_refused_once_asymmetric_verification_is_configured(monkeypatch):
    """Migration phase 3, and the reason the default is conditional.

    Before Ed25519 is configured, HMAC must keep working or phase 1 breaks
    every existing deployment. After it is configured, continuing to honour
    HMAC is a downgrade window that someone must choose on purpose.
    """
    monkeypatch.setenv(signing.ENV_HMAC, "legacy-key")
    monkeypatch.delenv(signing.ENV_ED25519_PRIVATE, raising=False)
    monkeypatch.delenv(signing.ENV_ED25519_PUBLIC, raising=False)
    monkeypatch.delenv(signing.ENV_ACCEPT_HMAC, raising=False)

    legacy = _issue()
    assert legacy.sig_alg == signing.ALG_HMAC
    assert _verify(legacy).verified is True, "phase 1 must not break anyone"

    # The deployment migrates: asymmetric verification material appears.
    _seed, public = _keypair()
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, public)

    result = _verify(legacy)
    assert result.verified is False
    assert result.reason == "signature_algorithm_refused", (
        "a refused algorithm must be distinguishable from a forged signature")

    # ...and the operator opens the window deliberately for one lease TTL.
    monkeypatch.setenv(signing.ENV_ACCEPT_HMAC, "1")
    assert _verify(legacy).verified is True


def test_a_missing_crypto_library_never_falls_back_to_hmac(monkeypatch, pdp):
    """Silent fallback would restore the defect at the moment it looked fixed."""
    monkeypatch.setattr(
        signing, "_ed25519",
        lambda: (_ for _ in ()).throw(signing.SigningUnavailable("no cryptography")))
    monkeypatch.setenv(signing.ENV_HMAC, "still-configured")

    with pytest.raises(signing.SigningUnavailable):
        _issue()


def test_the_binding_is_still_enforced_under_ed25519(pdp):
    """The new signature scheme must not quietly loosen what C already binds."""
    lease = _issue()
    changed = lease.verify(
        now=ISSUED, actor_identity="agent-1",
        tool_name="wo_close", arguments={"id": "WO-2"},   # argument changed
        tenant_id="acme", target_environment="staging")
    assert changed.verified is False
    assert changed.reason == "tool_args_hash_mismatch"
