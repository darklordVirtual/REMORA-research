# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Key-handling contracts for lease signing (ADR-A).

`tests/test_lease_authority_custody.py` attacks the property: a verifier must
not be able to mint. This file covers the material-handling branches that
property rests on, one contract each.

Every test here corresponds to a real failure mode an operator can produce:
a truncated secret, the public key pasted where the private one belongs, a
key store that returns an empty string, a lease arriving under an algorithm
this build does not implement. The common requirement is that each fails
CLOSED and says which variable is wrong -- a signature that never verifies for
reasons nobody can see is how a deployment ends up with the migration flag
permanently on.

Nothing here asserts "the function was called". If a test in this file passes
for a reason other than the contract in its name, it is a bad test.
"""
from __future__ import annotations

import base64
import os as _os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.enforcement import lease_signing as signing  # noqa: E402
from remora.enforcement.lease import ExecutionLease  # noqa: E402

if _os.environ.get("REMORA_REQUIRE_SECURITY_EXTRA", "").strip() in {"1", "true"}:
    import cryptography  # noqa: F401
else:
    pytest.importorskip("cryptography")

from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402

ISSUED = datetime.now(UTC).isoformat()
PAYLOAD = b'{"decision":"accept"}'
CALL = {"tool_name": "wo_close", "arguments": {"id": "WO-1"},
        "tenant_id": "acme", "target_environment": "staging"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in (signing.ENV_ED25519_PRIVATE, signing.ENV_ED25519_PUBLIC,
                 signing.ENV_HMAC, signing.ENV_HMAC_FALLBACK,
                 signing.ENV_ACCEPT_HMAC, signing.ENV_KID):
        monkeypatch.delenv(name, raising=False)


def _pair() -> tuple[str, str]:
    k = ed25519.Ed25519PrivateKey.generate()
    return k.private_bytes_raw().hex(), k.public_key().public_bytes_raw().hex()


# ── key decoding: both encodings, and every way to get it wrong ─────────────

def test_a_base64_encoded_key_is_accepted(monkeypatch):
    """Operators paste base64 as often as hex; both must work.

    If only hex were accepted, a base64 key would fail as "not valid base64",
    which names the wrong problem.
    """
    seed_hex, _ = _pair()
    seed_b64 = base64.b64encode(bytes.fromhex(seed_hex)).decode()
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, seed_b64)

    signature = signing.sign_payload(PAYLOAD, alg=signing.ALG_ED25519)
    assert signing.verify_payload(PAYLOAD, signature,
                                  alg=signing.ALG_ED25519) is True


def test_a_malformed_private_key_is_refused_by_name(monkeypatch):
    """Not hex, not base64. The error must name the variable."""
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, "not-a-key-at-all!!")
    with pytest.raises(signing.SigningUnavailable) as exc:
        signing.sign_payload(PAYLOAD, alg=signing.ALG_ED25519)
    assert signing.ENV_ED25519_PRIVATE in str(exc.value)


def test_a_sixty_four_character_non_hex_key_falls_back_to_base64(monkeypatch):
    """The length-64 branch must not swallow a valid base64 key.

    64 characters is both the hex length of a 32-byte key and a plausible
    base64 length, so the hex attempt has to fail soft rather than reject.
    """
    # 64 'z's is not hex, but IS valid base64 (decoding to 48 bytes). Reaching
    # the LENGTH complaint rather than the encoding one is the proof that the
    # hex attempt failed soft and base64 was tried -- if the length-64 branch
    # had rejected outright, this would report an encoding error instead.
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, "z" * 64)
    with pytest.raises(signing.SigningUnavailable) as exc:
        signing.sign_payload(PAYLOAD, alg=signing.ALG_ED25519)
    assert "decoded to 48 bytes" in str(exc.value)

    # And a 64-character string that is neither encoding reports the encoding.
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, "!" * 64)
    with pytest.raises(signing.SigningUnavailable) as exc:
        signing.sign_payload(PAYLOAD, alg=signing.ALG_ED25519)
    assert "neither 64 hex characters nor valid base64" in str(exc.value)


def test_a_wrong_length_key_is_refused_with_its_length(monkeypatch):
    """The truncated-secret case: valid base64, wrong size.

    This is the one that would otherwise produce signatures that never verify.
    """
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE,
                       base64.b64encode(b"tooshort").decode())
    with pytest.raises(signing.SigningUnavailable) as exc:
        signing.sign_payload(PAYLOAD, alg=signing.ALG_ED25519)
    assert "8 bytes" in str(exc.value) and "32" in str(exc.value)


def test_a_malformed_public_key_is_refused_at_verification(monkeypatch):
    """A broken verifier must refuse, never accept."""
    seed, _ = _pair()
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, seed)
    signature = signing.sign_payload(PAYLOAD, alg=signing.ALG_ED25519)

    monkeypatch.delenv(signing.ENV_ED25519_PRIVATE)
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, "clearly-not-a-key")
    with pytest.raises(signing.SigningUnavailable):
        signing.verify_payload(PAYLOAD, signature, alg=signing.ALG_ED25519)


# ── verification material: present, absent, and the wrong one ───────────────

def test_a_verifier_with_the_wrong_public_key_refuses(monkeypatch):
    """Two valid keypairs. The signature must bind to one of them."""
    seed_a, _ = _pair()
    _seed_b, public_b = _pair()
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, seed_a)
    signature = signing.sign_payload(PAYLOAD, alg=signing.ALG_ED25519)

    monkeypatch.delenv(signing.ENV_ED25519_PRIVATE)
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, public_b)
    assert signing.verify_payload(PAYLOAD, signature,
                                  alg=signing.ALG_ED25519) is False


def test_the_issuer_can_verify_from_its_seed_alone(monkeypatch):
    """A single-process deployment must still work.

    Deriving the public key from the seed is what Ed25519 permits, and it
    weakens nothing: the verifier still cannot mint unless it holds the seed,
    which in this branch it does because it IS the issuer.
    """
    seed, _ = _pair()
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, seed)
    signature = signing.sign_payload(PAYLOAD, alg=signing.ALG_ED25519)
    assert signing.verify_payload(PAYLOAD, signature,
                                  alg=signing.ALG_ED25519) is True
    assert signing.public_key_only() is False


def test_no_material_at_all_cannot_reach_a_verdict(monkeypatch):
    """"Cannot check" must never be reported as "checked and fine"."""
    with pytest.raises(signing.SigningUnavailable) as exc:
        signing.verify_payload(PAYLOAD, "00" * 64, alg=signing.ALG_ED25519)
    assert signing.ENV_ED25519_PUBLIC in str(exc.value)


def test_a_malformed_signature_is_a_refusal_not_a_crash(monkeypatch):
    """Signatures arrive from the network; non-hex must not raise ValueError."""
    _seed, public = _pair()
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, public)
    assert signing.verify_payload(PAYLOAD, "not-hex-at-all",
                                  alg=signing.ALG_ED25519) is False
    assert signing.verify_payload(PAYLOAD, "", alg=signing.ALG_ED25519) is False


# ── algorithm selection ─────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["rs256", "none", "HMAC-SHA256", ""])
def test_an_unsupported_algorithm_is_refused_both_ways(monkeypatch, bad):
    """`alg` comes off the lease, so it is attacker-influenced input.

    Includes "none" (the classic JWT bypass) and a case-variant of a real
    algorithm, because a lenient match is how alg confusion starts.
    """
    seed, public = _pair()
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, seed)
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, public)

    with pytest.raises(signing.SigningUnavailable):
        signing.sign_payload(PAYLOAD, alg=bad)
    with pytest.raises(signing.SigningUnavailable):
        signing.verify_payload(PAYLOAD, "00" * 64, alg=bad)


def test_hmac_signing_without_a_key_refuses(monkeypatch):
    """An empty key store must not produce a signature over an empty secret."""
    with pytest.raises(signing.SigningUnavailable):
        signing.sign_payload(PAYLOAD, alg=signing.ALG_HMAC)


def test_hmac_verification_without_a_key_refuses(monkeypatch):
    monkeypatch.setenv(signing.ENV_ACCEPT_HMAC, "1")
    with pytest.raises(signing.SigningUnavailable):
        signing.verify_payload(PAYLOAD, "00" * 32, alg=signing.ALG_HMAC)


def test_the_pdp_fallback_key_is_honoured(monkeypatch):
    """REMORA_PDP_SIGNING_KEY is the historical name and is still accepted."""
    monkeypatch.setenv(signing.ENV_HMAC_FALLBACK, "legacy-shared-secret")
    assert signing.issuer_algorithm() == signing.ALG_HMAC
    signature = signing.sign_payload(PAYLOAD, alg=signing.ALG_HMAC)
    assert signing.verify_payload(PAYLOAD, signature,
                                  alg=signing.ALG_HMAC) is True


# ── issuer selection and rotation ───────────────────────────────────────────

def test_ed25519_wins_when_both_are_configured(monkeypatch):
    """Mid-migration a deployment holds both; it must mint the stronger one."""
    seed, _ = _pair()
    monkeypatch.setenv(signing.ENV_HMAC, "legacy")
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, seed)
    assert signing.issuer_algorithm() == signing.ALG_ED25519


def test_no_material_means_no_issuer(monkeypatch):
    assert signing.issuer_algorithm() is None


def test_a_missing_kid_is_empty_not_absent(monkeypatch):
    """Single-key deployments are normal; a missing kid must not be an error."""
    seed, _ = _pair()
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, seed)
    assert signing.issuer_kid() == ""

    lease = ExecutionLease.issue(
        decision="accept", actor_identity="a", policy_bundle_hash="b",
        issued_at=ISSUED, **CALL)
    assert lease.kid == ""
    assert lease.verify(now=ISSUED, actor_identity="a", **CALL).verified is True


def test_the_kid_is_carried_and_signed(monkeypatch):
    """Rotation needs the kid to be bound, not merely attached.

    An unsigned kid could be rewritten to point a verifier at a different key,
    which is the multi-key version of algorithm confusion.
    """
    seed, _ = _pair()
    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, seed)
    monkeypatch.setenv(signing.ENV_KID, "lease-2026-08")

    lease = ExecutionLease.issue(
        decision="accept", actor_identity="a", policy_bundle_hash="b",
        issued_at=ISSUED, **CALL)
    assert lease.kid == "lease-2026-08"
    assert lease.verify(now=ISSUED, actor_identity="a", **CALL).verified is True

    relabelled = ExecutionLease(**{**lease.to_dict(), "kid": "some-other-key"})
    assert relabelled.verify(
        now=ISSUED, actor_identity="a", **CALL).verified is False


def test_rotation_verifies_under_the_new_key_and_not_the_old(monkeypatch):
    """The rotation contract, end to end."""
    old_seed, old_public = _pair()
    new_seed, new_public = _pair()

    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, old_seed)
    monkeypatch.setenv(signing.ENV_KID, "old")
    old_lease = ExecutionLease.issue(
        decision="accept", actor_identity="a", policy_bundle_hash="b",
        issued_at=ISSUED, **CALL)

    # Rotate: the verifier now trusts only the new public key.
    monkeypatch.delenv(signing.ENV_ED25519_PRIVATE)
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, new_public)
    assert old_lease.verify(
        now=ISSUED, actor_identity="a", **CALL).verified is False, (
        "a lease from the retired key must stop verifying after rotation")

    monkeypatch.setenv(signing.ENV_ED25519_PRIVATE, new_seed)
    monkeypatch.setenv(signing.ENV_KID, "new")
    new_lease = ExecutionLease.issue(
        decision="accept", actor_identity="a", policy_bundle_hash="b",
        issued_at=ISSUED, **CALL)
    monkeypatch.delenv(signing.ENV_ED25519_PRIVATE)
    assert new_lease.verify(
        now=ISSUED, actor_identity="a", **CALL).verified is True
    assert old_public != new_public


# ── the optional dependency ─────────────────────────────────────────────────

def test_a_missing_cryptography_refuses_at_verification_too(monkeypatch):
    """Issuance already covered; verification must not degrade either.

    If verification fell back to HMAC when the library was missing, an
    attacker who learned the old shared secret could pick the moment.
    """
    _seed, public = _pair()
    monkeypatch.setenv(signing.ENV_ED25519_PUBLIC, public)
    monkeypatch.setenv(signing.ENV_HMAC, "the-old-secret")
    monkeypatch.setattr(signing, "_ed25519", lambda: (_ for _ in ()).throw(
        signing.SigningUnavailable("cryptography is not installed")))

    with pytest.raises(signing.SigningUnavailable):
        signing.verify_payload(PAYLOAD, "00" * 64, alg=signing.ALG_ED25519)
