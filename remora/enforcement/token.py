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
from typing import Any

_ENV_KEY = "REMORA_PDP_SIGNING_KEY"


def _get_signing_key() -> bytes | None:
    val = os.environ.get(_ENV_KEY, "").strip()
    return val.encode() if val else None


def _canonical_payload(action: str, observation_hash: str, request_id: str, issued_at: str) -> bytes:
    """Stable canonical serialization for signing (sorted keys, no whitespace)."""
    payload = {
        "action": action,
        "issued_at": issued_at,
        "observation_hash": observation_hash,
        "request_id": request_id,
    }
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
        signature: HMAC-SHA256 over canonical payload, or "" if unsigned.
        is_signed: True if a signing key was available at issuance time.
    """
    action: str
    observation_hash: str
    request_id: str
    issued_at: str
    signature: str
    is_signed: bool

    @classmethod
    def issue(
        cls,
        action: str,
        observation_hash: str,
        request_id: str,
        issued_at: str,
    ) -> "PolicyDecisionToken":
        """Issue a signed (or unsigned) PolicyDecisionToken from the PDP.

        Args:
            action: Decision action ("accept", "verify", "abstain", "escalate").
            observation_hash: Output of _hash_observation(obs) for binding.
            request_id: Unique request identifier.
            issued_at: UTC ISO-8601 timestamp string (from caller to avoid Date.now()).
        """
        key = _get_signing_key()
        if key:
            payload = _canonical_payload(action, observation_hash, request_id, issued_at)
            sig = _compute_signature(payload, key)
            return cls(
                action=action,
                observation_hash=observation_hash,
                request_id=request_id,
                issued_at=issued_at,
                signature=sig,
                is_signed=True,
            )
        return cls(
            action=action,
            observation_hash=observation_hash,
            request_id=request_id,
            issued_at=issued_at,
            signature="",
            is_signed=False,
        )

    def verify(self, observation_hash: str | None = None) -> "TokenVerificationResult":
        """Verify this token's signature and optionally the observation hash.

        Args:
            observation_hash: Expected hash; if provided, must match self.observation_hash.

        Returns:
            TokenVerificationResult with verified=True if signature is valid.
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
            self.action, self.observation_hash, self.request_id, self.issued_at
        )
        expected = _compute_signature(payload, key)
        sig_ok = hmac.compare_digest(expected, self.signature)

        if not sig_ok:
            return TokenVerificationResult(
                verified=False,
                reason="signature_invalid",
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
        return {
            "action": self.action,
            "observation_hash": self.observation_hash,
            "request_id": self.request_id,
            "issued_at": self.issued_at,
            "signature": self.signature,
            "is_signed": self.is_signed,
        }


@dataclass(frozen=True)
class TokenVerificationResult:
    """Result of PolicyDecisionToken.verify()."""
    verified: bool
    reason: str
    is_signed: bool
