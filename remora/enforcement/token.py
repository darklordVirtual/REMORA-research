# Author: Stian Skogbrott
# License: Apache-2.0
"""PolicyDecisionToken — signed authorization token from PDP to PEP.

Implements intern_forbedring.txt §5.A-B (REM-013): signed authorization token
that flows from the Policy Decision Point to the Policy Enforcement Point.

The PEP (EnforcementGate) must verify the token's HMAC signature before
allowing any action execution. This prevents:
  - Bypassing the PDP by directly calling the PEP with an unsigned decision
  - Token forgery (requires possession of the signing key)
  - Decision substitution (observation_hash binds the token to the specific call)

Key management: set REMORA_PDP_SIGNING_KEY in the environment.
  - If absent: token is issued as UNSIGNED (enforcement gate rejects in strict mode)
  - If set: HMAC-SHA256 signature is computed over canonical payload

Usage (PDP side):
    from remora.enforcement.token import PolicyDecisionToken
    token = PolicyDecisionToken.issue(
        action="accept",
        observation_hash=obs_hash,
        request_id=req_id,
    )
    # Pass token to PEP layer

Usage (PEP side):
    gate = EnforcementGate(strict=True)
    gate.enforce(token, action_fn=lambda: execute_tool(...))
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import UTC
from typing import Any

_ENV_KEY = "REMORA_PDP_SIGNING_KEY"

# Every token now carries a signed expiry (review finding: replayable
# no-expiry tokens). Default TTL when the issuer does not set one; hard cap
# on any explicit expiry.
DEFAULT_TOKEN_TTL_SECONDS = 300
MAX_TOKEN_TTL_SECONDS = 86400


def _get_signing_key() -> bytes | None:
    val = os.environ.get(_ENV_KEY, "").strip()
    return val.encode() if val else None


def _canonical_payload(
    action: str,
    observation_hash: str,
    request_id: str,
    issued_at: str,
    expires_at: str | None = None,
    jti: str = "",
    audience: str = "",
) -> bytes:
    """Stable canonical serialization for signing (sorted keys, no whitespace).

    ``expires_at`` is included in the signed payload only when set, so tokens
    issued before expiry support remain verifiable, while an expiring token
    cannot have its ``expires_at`` stripped without invalidating the signature.
    """
    payload = {
        "action": action,
        "issued_at": issued_at,
        "observation_hash": observation_hash,
        "request_id": request_id,
    }
    if expires_at is not None:
        payload["expires_at"] = expires_at
    if jti:
        payload["jti"] = jti
    if audience:
        payload["audience"] = audience
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _compute_signature(payload_bytes: bytes, key: bytes) -> str:
    return hmac.new(key, payload_bytes, hashlib.sha256).hexdigest()


def _hash_observation(obs_data: Any) -> str:
    """Stable SHA-256 hash of an observation object for binding."""
    if hasattr(obs_data, "__dataclass_fields__"):
        import dataclasses
        serializable = dataclasses.asdict(obs_data)
    elif isinstance(obs_data, dict):
        serializable = obs_data
    else:
        serializable = {"value": str(obs_data)}
    canonical = json.dumps(serializable, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class PolicyDecisionToken:
    """Signed authorization token from PDP (Policy Decision Point) to PEP.

    Attributes:
        action: The authorized decision ("accept", "verify", "abstain", "escalate").
        observation_hash: SHA-256 of the PolicyObservation that was evaluated.
        request_id: Unique identifier for this governance request.
        issued_at: ISO-8601 timestamp of issuance (UTC).
        expires_at: Optional ISO-8601 expiry timestamp (UTC). When set, it is
            part of the signed payload and verify() rejects the token after
            this instant. When None, the token does not expire (audit finding
            F-2 documents this legacy mode; new issuers should set an expiry).
        signature: HMAC-SHA256 over canonical payload, or "" if unsigned.
        is_signed: True if a signing key was available at issuance time.
    """
    action: str
    observation_hash: str
    request_id: str
    issued_at: str
    signature: str
    is_signed: bool
    expires_at: str | None = None
    # One-time-use id (consumed atomically by the PEP) and intended verifier.
    jti: str = ""
    audience: str = ""

    @classmethod
    def issue(
        cls,
        action: str,
        observation_hash: str,
        request_id: str,
        issued_at: str,
        expires_at: str | None = None,
        audience: str = "",
    ) -> PolicyDecisionToken:
        """Issue a signed (or unsigned) PolicyDecisionToken from the PDP.

        Args:
            action: Decision action ("accept", "verify", "abstain", "escalate").
            observation_hash: Output of _hash_observation(obs) for binding.
            request_id: Unique request identifier.
            issued_at: UTC ISO-8601 timestamp string (from caller to avoid Date.now()).
            expires_at: Optional UTC ISO-8601 expiry; signed into the payload
                when set, so it cannot be stripped or extended post-issuance.
        """
        import uuid as _uuid
        from datetime import datetime, timedelta

        issued_dt = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
        if expires_at is None:
            # Expiry is mandatory (closes the legacy no-expiry replay window):
            # compute the default TTL when the issuer does not set one.
            expires_at = (
                issued_dt + timedelta(seconds=DEFAULT_TOKEN_TTL_SECONDS)
            ).isoformat()
        else:
            expiry_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            ttl = (expiry_dt - issued_dt).total_seconds()
            if ttl <= 0 or ttl > MAX_TOKEN_TTL_SECONDS:
                raise ValueError(
                    f"token TTL must be in (0, {MAX_TOKEN_TTL_SECONDS}] seconds, got {ttl}"
                )
        jti = str(_uuid.uuid4())
        key = _get_signing_key()
        if key:
            payload = _canonical_payload(
                action, observation_hash, request_id, issued_at, expires_at,
                jti, audience,
            )
            sig = _compute_signature(payload, key)
            return cls(
                action=action,
                observation_hash=observation_hash,
                request_id=request_id,
                issued_at=issued_at,
                signature=sig,
                is_signed=True,
                expires_at=expires_at,
                jti=jti,
                audience=audience,
            )
        return cls(
            action=action,
            observation_hash=observation_hash,
            request_id=request_id,
            issued_at=issued_at,
            signature="",
            is_signed=False,
            expires_at=expires_at,
            jti=jti,
            audience=audience,
        )

    def verify(
        self,
        observation_hash: str | None = None,
        now: str | None = None,
    ) -> TokenVerificationResult:
        """Verify this token's signature, expiry, and optionally the observation hash.

        Args:
            observation_hash: Expected hash; if provided, must match self.observation_hash.
            now: UTC ISO-8601 timestamp to evaluate expiry against; defaults to
                the current UTC time. Only consulted when expires_at is set.

        Returns:
            TokenVerificationResult with verified=True if signature is valid
            and the token has not expired.
        """
        key = _get_signing_key()
        if not key:
            return TokenVerificationResult(
                verified=False,
                reason="no_signing_key",
                is_signed=False,
            )
        if not self.is_signed or not self.signature:
            return TokenVerificationResult(
                verified=False,
                reason="token_not_signed",
                is_signed=False,
            )

        payload = _canonical_payload(
            self.action, self.observation_hash, self.request_id, self.issued_at,
            self.expires_at, self.jti, self.audience,
        )
        expected = _compute_signature(payload, key)
        sig_ok = hmac.compare_digest(expected, self.signature)

        if not sig_ok:
            return TokenVerificationResult(
                verified=False,
                reason="signature_invalid",
                is_signed=True,
            )

        if self.expires_at is None:
            # Mandatory-expiry policy: legacy no-expiry tokens are rejected
            # outright (audit finding F-2 / replay review finding).
            return TokenVerificationResult(
                verified=False,
                reason="missing_expiry",
                is_signed=True,
            )
        if self.expires_at is not None:
            from datetime import datetime

            try:
                expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
                current = (
                    datetime.fromisoformat(now.replace("Z", "+00:00"))
                    if now is not None
                    else datetime.now(UTC)
                )
            except ValueError:
                return TokenVerificationResult(
                    verified=False,
                    reason="expiry_unparseable",
                    is_signed=True,
                )
            if current >= expiry:
                return TokenVerificationResult(
                    verified=False,
                    reason="token_expired",
                    is_signed=True,
                )

        if observation_hash is not None and observation_hash != self.observation_hash:
            return TokenVerificationResult(
                verified=False,
                reason="observation_hash_mismatch",
                is_signed=True,
            )

        return TokenVerificationResult(
            verified=True,
            reason="ok",
            is_signed=True,
        )

    def to_dict(self) -> dict[str, Any]:
        """Complete serialisation — every signed field round-trips."""
        return {
            "action": self.action,
            "observation_hash": self.observation_hash,
            "request_id": self.request_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "jti": self.jti,
            "audience": self.audience,
            "signature": self.signature,
            "is_signed": self.is_signed,
        }

    _FIELDS = frozenset({
        "action", "observation_hash", "request_id", "issued_at",
        "expires_at", "jti", "audience", "signature", "is_signed",
    })

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyDecisionToken:
        """Reconstruct a token; unknown keys are rejected (fail closed)."""
        unknown = set(data) - cls._FIELDS
        if unknown:
            raise ValueError(f"unknown token fields: {sorted(unknown)}")
        return cls(**data)


@dataclass(frozen=True)
class TokenVerificationResult:
    """Result of PolicyDecisionToken.verify()."""
    verified: bool
    reason: str
    is_signed: bool
