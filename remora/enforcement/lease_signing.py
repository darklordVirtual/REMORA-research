# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Signature schemes for ExecutionLease, and the custody split (ADR-A).

The defect this module addresses is a topology defect before it is an
algorithm defect. ``workers/mcp-gateway/src/index.ts`` hands the execution
container ``REMORA_LEASE_SIGNING_KEY`` and ``REMORA_PDP_SIGNING_KEY`` as
plain secrets, and ``ExecutionLease`` signs and verifies with HMAC-SHA256
under that same key. The component that ENFORCES an authorization therefore
holds the material that AUTHORS one. Compromise of the executing container is
not merely a replay risk; it is an authority-forgery risk.

Converting the algorithm without separating custody would fix nothing. So the
unit of change here is a pair:

    format          Ed25519 over the same canonical payload
    key topology    issuer holds a private key; verifier holds only a public key

A component configured with only ``REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC``
can verify every lease it will ever be shown and can mint none. That is the
property, and ``tests/test_lease_authority_custody.py`` attacks it directly.

Why raw Ed25519 and not JWS
---------------------------
The crosswalk defaulted to JWS + EdDSA. Rejected on the evidence: this lease
never leaves the deployment — it travels PDP → PEP — and ``verify()`` already
rebuilds its canonical payload from typed dataclass fields rather than parsing
one. That is strictly stronger than trusting a self-describing token. JWS
would add a parser, a header the presenter partly controls, and the ``alg``
confusion class, to buy interoperability nothing currently requires. Revisit
if a lease ever crosses an organisational boundary. COSE is not built: no
constrained transport requires it.

Downgrade protection
--------------------
``sig_alg`` is part of the SIGNED payload, not a hint beside it. An attacker
cannot strip ``ed25519`` down to ``hmac-sha256`` without invalidating the
signature over the very field they changed. Phase 3 of the migration
additionally refuses HMAC outright unless ``REMORA_LEASE_ACCEPT_HMAC`` is
explicitly set, so the dual-accept window is a decision someone makes rather
than a default that persists.

Fail closed on a missing dependency
-----------------------------------
``cryptography`` is an optional extra (``pyproject.toml``). If Ed25519 material
is configured and the library is absent, issuance and verification RAISE.
Falling back to HMAC there would silently restore the exact vulnerability this
module exists to remove, at the moment an operator believed they had fixed it.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from typing import Any

__all__ = [
    "ALG_HMAC",
    "ALG_ED25519",
    "SigningUnavailable",
    "issuer_algorithm",
    "sign_payload",
    "verify_payload",
    "hmac_accepted",
    "public_key_only",
]

ALG_HMAC = "hmac-sha256"
ALG_ED25519 = "ed25519"

#: Existing symmetric key, unchanged. Phase 1 keeps issuing under it.
ENV_HMAC = "REMORA_LEASE_SIGNING_KEY"
ENV_HMAC_FALLBACK = "REMORA_PDP_SIGNING_KEY"

#: Ed25519 seed (32 bytes, hex or base64). Belongs to the PDP ONLY. A
#: deployment that puts this in the execution container has changed its
#: algorithm and kept its vulnerability.
ENV_ED25519_PRIVATE = "REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE"

#: Ed25519 public key (32 bytes, hex or base64). Safe in the execution
#: container; that is the entire point.
ENV_ED25519_PUBLIC = "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC"

#: Key identifier carried on the lease so rotation does not need a flag day.
ENV_KID = "REMORA_LEASE_SIGNING_KID"

#: Migration phase 3: unset means HMAC leases are refused.
ENV_ACCEPT_HMAC = "REMORA_LEASE_ACCEPT_HMAC"


class SigningUnavailable(RuntimeError):
    """Configured signing or verification material cannot be used.

    Raised rather than returning None so that a misconfigured asymmetric
    deployment fails loudly at issue time instead of quietly degrading to the
    symmetric scheme it was configured to leave behind.
    """


def _decode_key(raw: str, *, name: str) -> bytes:
    """Accept hex or base64; refuse anything that is not 32 bytes.

    Ed25519 seeds and public keys are both exactly 32 bytes. A length check
    here turns "pasted the wrong secret" into a startup error rather than a
    signature that never verifies for reasons nobody can see.
    """
    text = raw.strip()
    key: bytes | None = None
    if len(text) == 64:
        try:
            key = bytes.fromhex(text)
        except ValueError:
            key = None
    if key is None:
        try:
            key = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SigningUnavailable(
                f"{name} is neither 64 hex characters nor valid base64"
            ) from exc
    if len(key) != 32:
        raise SigningUnavailable(
            f"{name} decoded to {len(key)} bytes; Ed25519 keys are 32"
        )
    return key


def _ed25519() -> Any:
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise SigningUnavailable(
            "Ed25519 lease material is configured but the 'cryptography' "
            "package is not installed (pip install 'remora[security]'). "
            "Refusing to fall back to HMAC: that would restore the custody "
            "defect this configuration was chosen to remove."
        ) from exc
    return ed25519


def _hmac_key() -> bytes | None:
    for env in (ENV_HMAC, ENV_HMAC_FALLBACK):
        val = os.environ.get(env, "").strip()
        if val:
            return val.encode()
    return None


def hmac_accepted() -> bool:
    """Whether HMAC leases may still be verified.

    The default is deliberately conditional rather than fixed, so that the
    migration cannot stall in its most dangerous state.

    - No Ed25519 verification material configured: HMAC is accepted. This is
      every deployment before the migration starts, and phase 1 must not break
      them.
    - Ed25519 verification material configured: HMAC is REFUSED unless
      ``REMORA_LEASE_ACCEPT_HMAC`` is explicitly set. Once a deployment can
      verify asymmetric leases, continuing to honour symmetric ones is a
      downgrade window, and a downgrade window should be a decision someone
      made rather than a default nobody noticed.

    A deployment mid-migration sets the flag for exactly as long as leases
    issued under the old scheme can still be in flight — one lease TTL.
    """
    explicit = os.environ.get(ENV_ACCEPT_HMAC, "").strip().lower()
    if explicit:
        return explicit in {"1", "true", "yes", "on"}
    asymmetric_configured = bool(
        os.environ.get(ENV_ED25519_PUBLIC, "").strip()
        or os.environ.get(ENV_ED25519_PRIVATE, "").strip()
    )
    return not asymmetric_configured


def public_key_only() -> bool:
    """True when this process can verify Ed25519 leases but cannot issue them.

    The custody property, expressed as something a deployment can assert about
    itself and a test can attack.
    """
    return bool(os.environ.get(ENV_ED25519_PUBLIC, "").strip()) and not (
        os.environ.get(ENV_ED25519_PRIVATE, "").strip()
    )


def issuer_algorithm() -> str | None:
    """The algorithm this process can issue under, or None if it cannot.

    Ed25519 wins when a private key is present: a deployment that has both
    configured is mid-migration and should be minting the stronger object.
    """
    if os.environ.get(ENV_ED25519_PRIVATE, "").strip():
        return ALG_ED25519
    if _hmac_key():
        return ALG_HMAC
    return None


def issuer_kid() -> str:
    return os.environ.get(ENV_KID, "").strip()


def sign_payload(payload: bytes, *, alg: str) -> str:
    """Sign with the configured issuer material for ``alg``."""
    if alg == ALG_ED25519:
        seed = os.environ.get(ENV_ED25519_PRIVATE, "").strip()
        if not seed:
            raise SigningUnavailable(
                f"{ENV_ED25519_PRIVATE} is not set; this process cannot mint "
                "Ed25519 leases (which is the correct posture for a verifier)"
            )
        ed = _ed25519()
        key = ed.Ed25519PrivateKey.from_private_bytes(
            _decode_key(seed, name=ENV_ED25519_PRIVATE)
        )
        return key.sign(payload).hex()
    if alg == ALG_HMAC:
        key = _hmac_key()
        if not key:
            raise SigningUnavailable("no HMAC lease signing key configured")
        return hmac.new(key, payload, hashlib.sha256).hexdigest()
    raise SigningUnavailable(f"unknown lease signature algorithm: {alg!r}")


def verify_payload(payload: bytes, signature: str, *, alg: str) -> bool:
    """Verify ``signature`` over ``payload`` under ``alg``.

    Returns False for a bad signature. Raises ``SigningUnavailable`` when the
    material needed to reach a verdict is absent, so "cannot check" is never
    reported as "checked and fine".
    """
    if alg == ALG_ED25519:
        pub = os.environ.get(ENV_ED25519_PUBLIC, "").strip()
        if not pub:
            # A PDP holding only the private key can still verify: deriving the
            # public key from the seed is exactly what Ed25519 permits, and it
            # keeps a single-process deployment working without weakening
            # anything — the verifier still cannot mint unless it holds the seed.
            seed = os.environ.get(ENV_ED25519_PRIVATE, "").strip()
            if not seed:
                raise SigningUnavailable(
                    f"neither {ENV_ED25519_PUBLIC} nor {ENV_ED25519_PRIVATE} "
                    "is set; an Ed25519 lease cannot be verified"
                )
            ed = _ed25519()
            public = ed.Ed25519PrivateKey.from_private_bytes(
                _decode_key(seed, name=ENV_ED25519_PRIVATE)
            ).public_key()
        else:
            ed = _ed25519()
            public = ed.Ed25519PublicKey.from_public_bytes(
                _decode_key(pub, name=ENV_ED25519_PUBLIC)
            )
        try:
            public.verify(bytes.fromhex(signature), payload)
        except (ValueError, Exception):  # noqa: B014 - InvalidSignature subclasses Exception
            return False
        return True
    if alg == ALG_HMAC:
        if not hmac_accepted():
            # Phase 3. Refused as a policy decision, not as a signature
            # failure, so the audit trail distinguishes "downgrade attempt or
            # stale issuer" from "forged signature".
            raise SigningUnavailable(
                "HMAC lease signatures are refused: set "
                f"{ENV_ACCEPT_HMAC}=1 only for the duration of the Ed25519 "
                "migration window"
            )
        key = _hmac_key()
        if not key:
            raise SigningUnavailable("no HMAC lease signing key configured")
        expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    raise SigningUnavailable(f"unknown lease signature algorithm: {alg!r}")
