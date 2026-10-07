# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Domain-separated Ed25519 signing (remora/crypto/domain_signing.py).

RMR-CR-011: the type of artifact must be part of what is signed, so a
signature over one artifact can never verify as another, even under the same
key and over identical payload bytes.
"""
from __future__ import annotations

import dataclasses

import pytest

pytest.importorskip("cryptography")

from remora.crypto import (  # noqa: E402
    Signature,
    SignatureDomain,
    SigningKey,
    VerificationKey,
    derive_kid,
    preimage,
    sign,
    verify,
)

ALL = frozenset(SignatureDomain)
PAYLOAD = b'{"a":1}'


def _key(domains=ALL) -> SigningKey:
    return SigningKey.generate(domains)


def test_a_signature_verifies_in_its_own_domain() -> None:
    key = _key()
    sig = sign(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD, key)
    result = verify(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD, sig, [key.verification_key()])
    assert result.ok and result.reason == "ok" and result.kid == key.kid


@pytest.mark.parametrize("signed_in", list(SignatureDomain))
def test_a_signature_never_verifies_in_another_domain(signed_in: SignatureDomain) -> None:
    # Same key, bound to every domain, same payload bytes: only the domain differs.
    key = _key()
    sig = sign(signed_in, PAYLOAD, key)
    for other in SignatureDomain:
        if other is signed_in:
            continue
        relabelled = dataclasses.replace(sig, domain=other.value)
        for candidate in (sig, relabelled):
            result = verify(other, PAYLOAD, candidate, [key.verification_key()])
            assert not result.ok, (signed_in, other, candidate.domain)
            assert result.reason in {"domain_mismatch", "signature_invalid"}


def test_the_domain_tag_is_part_of_the_preimage() -> None:
    a = preimage(SignatureDomain.POLICY_GRANT, PAYLOAD)
    b = preimage(SignatureDomain.EXECUTION_LEASE, PAYLOAD)
    assert a != b
    assert a == b"REMORA/POLICY-GRANT/v1\x00" + PAYLOAD


def test_a_key_cannot_sign_outside_its_domains() -> None:
    key = _key({SignatureDomain.TOOLSPEC_BUNDLE})
    with pytest.raises(ValueError, match="not bound"):
        sign(SignatureDomain.EXECUTION_LEASE, PAYLOAD, key)


def test_a_verification_key_cannot_verify_outside_its_domains() -> None:
    signer = _key()
    sig = sign(SignatureDomain.EXECUTION_LEASE, PAYLOAD, signer)
    narrow = VerificationKey(signer.verification_key().public_bytes,
                             frozenset({SignatureDomain.TOOLSPEC_BUNDLE}))
    result = verify(SignatureDomain.EXECUTION_LEASE, PAYLOAD, sig, [narrow])
    assert (result.ok, result.reason) == (False, "key_purpose_mismatch")


def test_the_kid_is_derived_from_the_key_and_cannot_be_claimed() -> None:
    honest, other = _key(), _key()
    assert honest.kid == derive_kid(honest.verification_key().public_bytes)
    # The other key holder signs and labels the signature with honest's kid.
    forged = dataclasses.replace(
        sign(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD, other), kid=honest.kid)
    result = verify(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD, forged,
                    [honest.verification_key()])
    assert (result.ok, result.reason) == (False, "signature_invalid")
    # And a kid that matches no trusted key is unknown, not invalid.
    unknown = sign(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD, other)
    result = verify(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD, unknown,
                    [honest.verification_key()])
    assert (result.ok, result.reason) == (False, "unknown_kid")


def test_a_mapping_keyed_under_the_wrong_kid_does_not_help() -> None:
    honest, other = _key(), _key()
    sig = sign(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD, other)
    mislabelled = {sig.kid: honest.verification_key()}
    result = verify(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD, sig, mislabelled)
    assert (result.ok, result.reason) == (False, "unknown_kid")


def test_revoked_keys_are_refused_before_the_signature_is_checked() -> None:
    key = _key()
    sig = sign(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD, key)
    result = verify(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD, sig,
                    [key.verification_key()], revoked=[key.kid])
    assert (result.ok, result.reason) == (False, "key_revoked")


def test_other_algorithms_and_malformed_values_are_refused() -> None:
    key = _key()
    sig = sign(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD, key)
    vk = [key.verification_key()]
    hmac_claim = dataclasses.replace(sig, algorithm="HMAC-SHA256")
    assert verify(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD, hmac_claim, vk).reason == "algorithm_unsupported"
    garbage = dataclasses.replace(sig, value="not base64!")
    assert verify(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD, garbage, vk).reason == "signature_malformed"
    assert verify(SignatureDomain.TOOLSPEC_BUNDLE, PAYLOAD + b" ", sig, vk).reason == "signature_invalid"


def test_verification_needs_no_signing_material_and_seeds_are_not_printed() -> None:
    key = _key()
    vk = key.verification_key()
    assert not any(isinstance(getattr(vk, f.name), bytes) and getattr(vk, f.name) == key.seed
                   for f in dataclasses.fields(vk))
    assert key.seed.hex() not in repr(key)
    sig = sign(SignatureDomain.EVIDENCE, PAYLOAD, key)
    restored = Signature.from_dict(sig.to_dict())
    assert verify(SignatureDomain.EVIDENCE, PAYLOAD, restored,
                  [VerificationKey.from_text(vk.public_bytes.hex(), ALL)]).ok


def test_keys_must_be_bound_to_a_domain_and_be_32_bytes() -> None:
    with pytest.raises(ValueError):
        SigningKey.generate(frozenset())
    from remora.crypto import SigningUnavailable

    with pytest.raises(SigningUnavailable):
        VerificationKey.from_text("abcd", ALL)
