# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
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
# Key lifecycle (Phase 6): a key id for the current signing key, a
# comma-separated "kid=key" list of PREVIOUS verify-only keys (rotation
# overlap: tokens signed before a rotation stay verifiable until they
# expire), and a comma-separated revocation list that refuses a kid even if
# its key is still present.
_ENV_KID = "REMORA_PDP_SIGNING_KID"
_ENV_PREVIOUS = "REMORA_PDP_PREVIOUS_KEYS"
_ENV_REVOKED = "REMORA_PDP_REVOKED_KIDS"
_ENV_ISSUER = "REMORA_PDP_ISSUER"

# Every token now carries a signed expiry (review finding: replayable
# no-expiry tokens). Default TTL when the issuer does not set one; hard cap
# on any explicit expiry.
DEFAULT_TOKEN_TTL_SECONDS = 300
MAX_TOKEN_TTL_SECONDS = 86400


def _get_signing_key() -> bytes | None:
    val = os.environ.get(_ENV_KEY, "").strip()
    return val.encode() if val else None


def _current_kid() -> str:
    return os.environ.get(_ENV_KID, "").strip()


def _previous_keys() -> dict[str, bytes]:
    """Verify-only keys from prior rotations, as {kid: key}."""
    out: dict[str, bytes] = {}
    for pair in os.environ.get(_ENV_PREVIOUS, "").split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        kid, _, key = pair.partition("=")
        if kid.strip() and key.strip():
            out[kid.strip()] = key.strip().encode()
    return out


def _revoked_kids() -> frozenset[str]:
    return frozenset(
        k.strip() for k in os.environ.get(_ENV_REVOKED, "").split(",") if k.strip()
    )


@dataclass(frozen=True)
class AuthorizationContext:
    """The conditions under which a decision was made, bound into its token.

    A signature answers who wrote the token. Until RMR-001 the token answered
    nothing else about the authorization: it carried the action, a hash of the
    call, timestamps, a one-time id and an audience. Tenant and target were
    covered transitively, because ``canonical_tool_call_hash`` takes them into
    its preimage, but the principal the decision was made for, the policy bundle
    it was decided under and the tool contract it was decided against were not
    bound at all.

    That gap has a shape. A token minted for one principal could be redeemed by
    another with the same capability in the same tenant, and a call reclassified
    as destructive after issuance could still be executed on the old
    authorization, because the redeeming path deliberately does not re-run the
    engine. The lease minted at dispatch binds the CURRENT values, which is a
    true statement about the lease and a misleading one about the authorization:
    it proves what the executor did, not what the decision point approved.

    Binding these as one hash keeps the wire format and the signature rules
    unchanged, and makes the redemption check a single comparison that cannot be
    partially applied.
    """

    tenant: str = ""
    principal: str = ""
    target_environment: str = ""
    policy_bundle_hash: str = ""
    toolspec_hash: str = ""
    intent_authority_hash: str = ""

    def hash(self) -> str:
        canonical = json.dumps(
            {
                "intent_authority_hash": self.intent_authority_hash or "",
                "policy_bundle_hash": self.policy_bundle_hash or "",
                "principal": self.principal or "",
                "target_environment": self.target_environment or "",
                "tenant": self.tenant or "",
                "toolspec_hash": self.toolspec_hash or "",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def differences(self, other: "AuthorizationContext") -> list[str]:
        """Field names that differ, so a refusal can say which one moved."""

        return [
            name
            for name in (
                "tenant",
                "principal",
                "target_environment",
                "policy_bundle_hash",
                "toolspec_hash",
                "intent_authority_hash",
            )
            if (getattr(self, name) or "") != (getattr(other, name) or "")
        ]


def _canonical_payload(
    action: str,
    observation_hash: str,
    request_id: str,
    issued_at: str,
    expires_at: str | None = None,
    jti: str = "",
    audience: str = "",
    kid: str = "",
    issuer: str = "",
    context_hash: str = "",
) -> bytes:
    """Stable canonical serialization for signing (sorted keys, no whitespace).

    ``expires_at`` is included in the signed payload only when set, so tokens
    issued before expiry support remain verifiable, while an expiring token
    cannot have its ``expires_at`` stripped without invalidating the signature.
    ``kid`` and ``issuer`` follow the same included-only-when-set discipline:
    pre-lifecycle tokens verify unchanged, and a token carrying a key id
    cannot have it stripped or swapped without invalidating the signature.
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
    if kid:
        payload["kid"] = kid
    if issuer:
        payload["issuer"] = issuer
    if context_hash:
        payload["context_hash"] = context_hash
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
    # Key lifecycle (Phase 6): which signing key produced this signature, and
    # who issued it. Both are signed-when-set: a token cannot have its kid
    # stripped or swapped, and pre-lifecycle tokens (kid == "") verify
    # unchanged against the current-then-previous key set.
    kid: str = ""
    issuer: str = ""
    #: SHA-256 of the AuthorizationContext this decision was made under. Signed
    #: when set, and compared at redemption against the context recomputed from
    #: the current request (RMR-001). Empty on tokens minted before the binding
    #: existed, which verify unchanged.
    context_hash: str = ""

    @classmethod
    def issue(
        cls,
        action: str,
        observation_hash: str,
        request_id: str,
        issued_at: str,
        expires_at: str | None = None,
        audience: str = "",
        context: "AuthorizationContext | None" = None,
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
        context_hash = context.hash() if context is not None else ""
        key = _get_signing_key()
        kid = _current_kid()
        issuer = os.environ.get(_ENV_ISSUER, "").strip()
        if key:
            payload = _canonical_payload(
                action, observation_hash, request_id, issued_at, expires_at,
                jti, audience, kid, issuer, context_hash,
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
                kid=kid,
                issuer=issuer,
                context_hash=context_hash,
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
            kid=kid,
            issuer=issuer,
            context_hash=context_hash,
        )

    def verify(
        self,
        observation_hash: str | None = None,
        now: str | None = None,
        context: "AuthorizationContext | None" = None,
    ) -> TokenVerificationResult:
        """Verify this token's signature, expiry, and optionally the observation hash.

        Args:
            observation_hash: Expected hash; if provided, must match self.observation_hash.
            now: UTC ISO-8601 timestamp to evaluate expiry against; defaults to
                the current UTC time. Only consulted when expires_at is set.
            context: The authorization context recomputed from the request being
                redeemed. When supplied, it must equal the one signed into the
                token. A token that carries no context refuses against a
                supplied one rather than passing: an unbound token cannot be
                shown to have been issued under these conditions, and treating
                "unknown" as "matching" is the failure this parameter exists to
                prevent (RMR-001).

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

        # Key lifecycle: a revoked kid refuses even if its key is still
        # deployed; a token naming a kid must verify with EXACTLY that key
        # (current or a previous rotation key); a pre-lifecycle token (no
        # kid) verifies against the current key, then each previous key —
        # the rotation-overlap window that keeps in-flight tokens valid
        # across a rotation until they expire.
        if self.kid and self.kid in _revoked_kids():
            return TokenVerificationResult(
                verified=False,
                reason="kid_revoked",
                is_signed=True,
            )

        payload = _canonical_payload(
            self.action, self.observation_hash, self.request_id, self.issued_at,
            self.expires_at, self.jti, self.audience, self.kid, self.issuer,
            self.context_hash,
        )

        if self.kid:
            current_kid = _current_kid()
            if self.kid == current_kid:
                candidate_keys = [key]
            else:
                prev = _previous_keys().get(self.kid)
                if prev is None:
                    return TokenVerificationResult(
                        verified=False,
                        reason="unknown_kid",
                        is_signed=True,
                    )
                candidate_keys = [prev]
        else:
            candidate_keys = [key, *_previous_keys().values()]

        sig_ok = any(
            hmac.compare_digest(_compute_signature(payload, k), self.signature)
            for k in candidate_keys
        )
        if not sig_ok:
            return TokenVerificationResult(
                verified=False,
                reason="signature_invalid",
                is_signed=True,
            )

        if context is not None:
            if not self.context_hash:
                return TokenVerificationResult(
                    verified=False,
                    reason="context_unbound",
                    is_signed=True,
                )
            if self.context_hash != context.hash():
                return TokenVerificationResult(
                    verified=False,
                    reason="context_mismatch",
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
                issued = datetime.fromisoformat(self.issued_at.replace("Z", "+00:00"))
                expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
                current = (
                    datetime.fromisoformat(now.replace("Z", "+00:00"))
                    if now is not None
                    else datetime.now(UTC)
                )
                # Coerce naive timestamps to UTC so a naive expires_at / now
                # cannot raise TypeError on comparison (fail-closed: an
                # unparseable/ambiguous time must yield verified=False, never
                # an uncaught exception).
                if issued.tzinfo is None:
                    issued = issued.replace(tzinfo=UTC)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=UTC)
                if current.tzinfo is None:
                    current = current.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                return TokenVerificationResult(
                    verified=False,
                    reason="expiry_unparseable",
                    is_signed=True,
                )
            # Not-before: a future-dated issued_at must not mint a token whose
            # real usable lifetime exceeds the TTL cap (clock-skewed or
            # malicious issuer input). Same invariant as ExecutionLease
            # (external review 2026-07-24, F-03): the token is valid only
            # inside [issued_at, expires_at).
            if current < issued:
                return TokenVerificationResult(
                    verified=False,
                    reason="token_not_yet_valid",
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
            "kid": self.kid,
            "issuer": self.issuer,
            "context_hash": self.context_hash,
            "signature": self.signature,
            "is_signed": self.is_signed,
        }

    _FIELDS = frozenset({
        "action", "observation_hash", "request_id", "issued_at",
        "expires_at", "jti", "audience", "kid", "issuer",
        "context_hash", "signature", "is_signed",
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
