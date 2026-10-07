# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Domain-separated Ed25519 signatures (RMR-CR-011, RMR-CR-001).

Every REMORA signature so far is over sorted compact JSON with no statement of
what the bytes are. Today the payloads of different artifacts happen to have
disjoint field sets, so no cross-type forgery is known; that is safety by
schema accident. This module makes the artifact type part of what is signed:

    preimage = domain tag || 0x00 || payload

so a signature made for one domain cannot verify in another, whatever the
payloads look like and whatever key material the two share.

Three further rules, each closing a way the topology could silently weaken:

- **The algorithm is explicit and singular.** Only Ed25519. A signature naming
  anything else is refused, never interpreted.
- **A key is bound to its purposes.** ``SigningKey`` and ``VerificationKey``
  carry the set of domains they may be used for. Signing or verifying outside
  that set is refused, so one key cannot quietly serve two artifact types.
- **The key id is derived, never declared.** ``kid`` is a digest of the public
  key. A signer cannot claim another signer's identity by writing its label:
  the label either is the digest of the key that verifies, or verification
  fails.

Verification never needs signing material: a process configured with
``VerificationKey`` values can check every signature and produce none.

The signed artifacts adopt it as a versioned change (CR-011): their v1
formats are frozen and untagged, and their v2 formats sign in the domains
below. The ``/v2`` in a tag names the artifact format it belongs to, so a
domain tag can never be read as describing a frozen v1 artifact.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

from remora.errors import RemoraError

__all__ = [
    "ALGORITHM",
    "Signature",
    "SignatureDomain",
    "SigningKey",
    "SigningUnavailable",
    "VerificationKey",
    "VerificationResult",
    "derive_kid",
    "preimage",
    "sign",
    "verify",
]

#: The only algorithm this module signs or verifies with.
ALGORITHM = "Ed25519"

_KID_PREFIX = "ed25519-"


class SignatureDomain(str, Enum):
    """What a signature is about. The value is the exact tag in the preimage."""

    TOOLSPEC_BUNDLE = "REMORA/TOOLSPEC-BUNDLE/v1"
    #: PolicyDecisionToken v2. Never used to sign anything under a /v1 tag:
    #: the reserved /v1 values were unused, and v1 tokens are untagged.
    POLICY_GRANT = "REMORA/POLICY-GRANT/v2"
    #: ExecutionLease v2 (v1 leases are untagged and frozen).
    EXECUTION_LEASE = "REMORA/EXECUTION-LEASE/v2"
    #: Tenant audit chain entries from the AUDIT_VERSION_TRANSITION record on.
    AUDIT = "REMORA/AUDIT/v2"
    EVIDENCE = "REMORA/EVIDENCE/v1"
    #: A Native Federation Action Envelope with its transport projection
    #: (remora.federation), verified by federation adapters with a pinned key.
    FEDERATION_ACTION = "REMORA/FEDERATION-ACTION/v1"
    #: A native result about one selected subject (an operation, report,
    #: attempt or effect observation), with how it was selected.
    FEDERATION_RESULT = "REMORA/FEDERATION-RESULT/v1"
    OPERATOR_STATEMENT = "REMORA/OPERATOR-STATEMENT/v1"


class SigningUnavailable(RemoraError, RuntimeError):
    """Signing or verification cannot run: missing library or unusable key.

    Raised, never turned into a negative verification result: a verifier that
    cannot run has not found a bad signature, and a caller must not be able to
    confuse the two.
    """

    code = "signing_unavailable"
    category = "crypto"


def _ed25519() -> Any:
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise SigningUnavailable(
            "Ed25519 signing requires the 'cryptography' package "
            "(pip install 'remora[security]')"
        ) from exc
    return ed25519


def _decode_32(raw: str | bytes, *, what: str) -> bytes:
    """Accept raw bytes, 64 hex characters or base64; require 32 bytes."""
    if isinstance(raw, (bytes, bytearray)):
        key = bytes(raw)
    else:
        text = raw.strip()
        decoded: bytes | None = None
        if len(text) == 64:
            try:
                decoded = bytes.fromhex(text)
            except ValueError:
                decoded = None
        if decoded is None:
            try:
                decoded = base64.b64decode(text, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise SigningUnavailable(
                    f"{what} is neither 64 hex characters nor valid base64"
                ) from exc
        key = decoded
    if len(key) != 32:
        raise SigningUnavailable(f"{what} is {len(key)} bytes; Ed25519 keys are 32")
    return key


def derive_kid(public_bytes: bytes) -> str:
    """The key id: a digest of the public key, so it cannot be claimed."""
    return _KID_PREFIX + hashlib.sha256(public_bytes).hexdigest()


def preimage(domain: SignatureDomain, payload: bytes) -> bytes:
    """The bytes actually signed: domain tag, a NUL separator, the payload."""
    if not isinstance(domain, SignatureDomain):
        raise TypeError("domain must be a SignatureDomain")
    return domain.value.encode("ascii") + b"\x00" + bytes(payload)


def _domains(domains: Iterable[SignatureDomain]) -> frozenset[SignatureDomain]:
    out = frozenset(domains)
    if not out:
        raise ValueError("a key must be bound to at least one signature domain")
    if not all(isinstance(d, SignatureDomain) for d in out):
        raise TypeError("domains must be SignatureDomain values")
    return out


@dataclass(frozen=True)
class VerificationKey:
    """An Ed25519 public key, its derived id, and the domains it may verify."""

    public_bytes: bytes
    domains: frozenset[SignatureDomain]
    kid: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_bytes", _decode_32(self.public_bytes, what="public key"))
        object.__setattr__(self, "domains", _domains(self.domains))
        object.__setattr__(self, "kid", derive_kid(self.public_bytes))

    @classmethod
    def from_text(cls, raw: str, domains: Iterable[SignatureDomain]) -> "VerificationKey":
        return cls(_decode_32(raw, what="public key"), frozenset(domains))


@dataclass(frozen=True)
class SigningKey:
    """An Ed25519 seed and the domains it may sign. Never printed."""

    seed: bytes = field(repr=False)
    domains: frozenset[SignatureDomain]

    def __post_init__(self) -> None:
        object.__setattr__(self, "seed", _decode_32(self.seed, what="signing seed"))
        object.__setattr__(self, "domains", _domains(self.domains))

    @classmethod
    def from_text(cls, raw: str, domains: Iterable[SignatureDomain]) -> "SigningKey":
        return cls(_decode_32(raw, what="signing seed"), frozenset(domains))

    @classmethod
    def generate(cls, domains: Iterable[SignatureDomain]) -> "SigningKey":
        import os

        return cls(os.urandom(32), frozenset(domains))

    def verification_key(self) -> VerificationKey:
        from cryptography.hazmat.primitives import serialization

        private = _ed25519().Ed25519PrivateKey.from_private_bytes(self.seed)
        raw = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
        return VerificationKey(raw, self.domains)

    @property
    def kid(self) -> str:
        return self.verification_key().kid


@dataclass(frozen=True)
class Signature:
    """A detached signature with the facts needed to check it."""

    algorithm: str
    domain: str
    kid: str
    value: str  # standard base64 of the 64-byte signature

    def to_dict(self) -> dict[str, str]:
        return {"algorithm": self.algorithm, "domain": self.domain,
                "kid": self.kid, "signature": self.value}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Signature":
        return cls(
            algorithm=str(raw.get("algorithm", "")),
            domain=str(raw.get("domain", "")),
            kid=str(raw.get("kid", "")),
            value=str(raw.get("signature", "")),
        )


@dataclass(frozen=True)
class VerificationResult:
    """``ok`` plus the reason. Reasons are stable strings callers branch on."""

    ok: bool
    reason: str
    kid: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.ok


def sign(domain: SignatureDomain, payload: bytes, key: SigningKey) -> Signature:
    """Sign ``payload`` in ``domain``. Refused when the key is not bound to it."""
    if domain not in key.domains:
        raise ValueError(
            f"signing key {key.kid} is not bound to {domain.value}; a key serves "
            "only the domains it was created for"
        )
    private = _ed25519().Ed25519PrivateKey.from_private_bytes(key.seed)
    raw = private.sign(preimage(domain, payload))
    return Signature(ALGORITHM, domain.value, key.kid, base64.b64encode(raw).decode("ascii"))


def verify(
    domain: SignatureDomain,
    payload: bytes,
    signature: Signature,
    keys: Mapping[str, VerificationKey] | Iterable[VerificationKey],
    *,
    revoked: Iterable[str] = (),
) -> VerificationResult:
    """Check ``signature`` over ``payload`` in ``domain`` against trusted keys.

    Order: algorithm, domain, revocation, key lookup by derived id, key
    purpose, then the signature itself. Each failure has its own reason, so a
    revoked key is never reported as a bad signature and a bad signature never
    as an unknown key.
    """
    if signature.algorithm != ALGORITHM:
        return VerificationResult(False, "algorithm_unsupported", signature.kid)
    if signature.domain != domain.value:
        return VerificationResult(False, "domain_mismatch", signature.kid)
    if signature.kid in set(revoked):
        return VerificationResult(False, "key_revoked", signature.kid)
    by_kid = dict(keys) if isinstance(keys, Mapping) else {k.kid: k for k in keys}
    key = by_kid.get(signature.kid)
    if key is None or key.kid != signature.kid:
        return VerificationResult(False, "unknown_kid", signature.kid)
    if domain not in key.domains:
        return VerificationResult(False, "key_purpose_mismatch", signature.kid)
    try:
        raw = base64.b64decode(signature.value, validate=True)
    except (binascii.Error, ValueError):
        return VerificationResult(False, "signature_malformed", signature.kid)
    from cryptography.exceptions import InvalidSignature

    public = _ed25519().Ed25519PublicKey.from_public_bytes(key.public_bytes)
    try:
        public.verify(raw, preimage(domain, payload))
    except InvalidSignature:
        return VerificationResult(False, "signature_invalid", signature.kid)
    return VerificationResult(True, "ok", signature.kid)
