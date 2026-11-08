# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""PolicyDecisionToken — signed authorization token from PDP to PEP.

Implements intern_forbedring.txt §5.A-B (REM-013): signed authorization token
that flows from the Policy Decision Point to the Policy Enforcement Point.

The PEP (EnforcementGate) must verify the token's HMAC signature before
allowing any action execution. This prevents:
  - Bypassing the PDP by directly calling the PEP with an unsigned decision
  - Token forgery by a party without the signing key
  - Decision substitution (observation_hash binds the token to the specific call)

What a symmetric token does NOT establish (RMR-CR-002): a trust boundary
between decision and enforcement. With v1 or v2 the PDP and the PEP share
REMORA_PDP_SIGNING_KEY, so any code that can verify a grant can also mint
one. Where the PDP and the PEP run in one process (the review path mints and
consumes on consecutive lines) the token is an in-process,
one-time grant record: jti, expiry, audience, context and observation
bindings are real and tested, and the signature adds no separation.

Format v3 (2026-10-13) is the boundary. It is Ed25519 over
``REMORA/POLICY-GRANT/v3 || 0x00 || payload``, its ``kid`` is derived from the
public key, and a process configured with only
``REMORA_PDP_VERIFY_KEYS_ED25519`` can redeem every grant it is shown and mint
none: ``issue()`` refuses in such a process rather than producing an unsigned
token. A deployment that runs ``/assess`` and ``/execute-accepted`` in
different custody domains therefore has a real decision/enforcement split.
Running both in one process with the private key is still one domain, and v3
does not pretend otherwise.

Downgrade: once Ed25519 material is configured, a live v1 or v2 (HMAC) token
is refused (``token_hmac_refused``) unless ``REMORA_PDP_ACCEPT_HMAC`` is set
for a migration window, the rule the lease already follows.

Signature formats (RMR-CR-011): v1 is HMAC-SHA256 over the untagged
canonical payload, frozen with its vector in ``vectors/v1``. v2 is
HMAC-SHA256 over ``REMORA/POLICY-GRANT/v2 || 0x00 || payload``, and the
payload carries ``format: v2``, so a v2 token cannot be relabelled as v1. A
strict v2 contract issues only v2 and refuses a v1 token as live authority
(``token_format_legacy``); ``verify_historical()`` still reads v1. v2 adds
domain separation, not a trust boundary: the key stays symmetric and shared
by PDP and PEP (RMR-CR-002).

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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from remora.governance.task_identity import TaskIdentity

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
# Format v3 (RMR-CR-002). The seed belongs to the PDP only; the verify keys
# (comma-separated, for rotation) are safe in any process that redeems grants.
_ENV_ED25519_PRIVATE = "REMORA_PDP_SIGNING_KEY_ED25519_PRIVATE"
_ENV_ED25519_PUBLIC = "REMORA_PDP_VERIFY_KEYS_ED25519"
_ENV_ACCEPT_HMAC = "REMORA_PDP_ACCEPT_HMAC"

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
        # An empty or "="-less entry partitions to an empty kid or key.
        kid, _, key = pair.strip().partition("=")
        if kid.strip() and key.strip():
            out[kid.strip()] = key.strip().encode()
    return out


def _revoked_kids() -> frozenset[str]:
    return frozenset(
        k.strip() for k in os.environ.get(_ENV_REVOKED, "").split(",") if k.strip()
    )


def _ed25519_seed() -> str:
    return os.environ.get(_ENV_ED25519_PRIVATE, "").strip()


def _ed25519_public_keys() -> list[str]:
    return [k.strip() for k in os.environ.get(_ENV_ED25519_PUBLIC, "").split(",") if k.strip()]


def asymmetric_configured() -> bool:
    """Whether this process holds any v3 (Ed25519) grant material."""
    return bool(_ed25519_seed() or _ed25519_public_keys())


def verify_only() -> bool:
    """True when this process can redeem v3 grants and cannot mint any.

    The decision/enforcement boundary of RMR-CR-002, as something a deployment
    can assert about itself and a test can attack.
    """
    return bool(_ed25519_public_keys()) and not _ed25519_seed()


def hmac_accepted() -> bool:
    """Whether a live v1 or v2 (HMAC) grant may still authorize.

    Without Ed25519 material: yes, every deployment before the migration. With
    it: only while ``REMORA_PDP_ACCEPT_HMAC`` is explicitly set. A process that
    can verify asymmetric grants and still honours symmetric ones has a
    downgrade window, and a downgrade window should be a decision someone made.
    """
    explicit = os.environ.get(_ENV_ACCEPT_HMAC, "").strip().lower()
    if explicit:
        return explicit in {"1", "true", "yes", "on"}
    return not asymmetric_configured()


def _v3_signing_key() -> Any:
    from remora.crypto import SignatureDomain, SigningKey

    return SigningKey.from_text(_ed25519_seed(), {SignatureDomain.POLICY_GRANT_ASYMMETRIC})


def _v3_verification_keys() -> list[Any]:
    from remora.crypto import SignatureDomain, VerificationKey

    domain = {SignatureDomain.POLICY_GRANT_ASYMMETRIC}
    keys = [VerificationKey.from_text(k, domain) for k in _ed25519_public_keys()]
    if not keys and _ed25519_seed():
        # A PDP holding only its seed can still verify what it minted; it
        # could mint anyway, so this weakens nothing.
        keys = [_v3_signing_key().verification_key()]
    return keys


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
    #: The task this decision was made under. Absent by default, because a
    #: context that carries no task identity must hash exactly as it did
    #: before these fields existed, or every token issued under RMR-001
    #: stops verifying. See remora/governance/task_identity.py.
    context_id: str = ""
    task_id: str = ""
    execution_context_hash: str = ""
    #: Digest of the request the call arrived in
    #: (:mod:`remora.execution.request_ref`). Absent by default for the same
    #: reason as the task fields: a context without one hashes as before.
    request_ref_hash: str = ""
    #: A service identity the proposal named to execute on the principal's
    #: behalf, admitted at assess time against the deployment's per-tenant
    #: declaration. Absent by default and omitted from the hash when empty,
    #: like the task fields, so a context naming no delegate hashes exactly as
    #: before. Bound here so a delegate cannot be added or swapped after the
    #: grant or the approval it rides on.
    delegated_executor: str = ""
    #: The WS1 binding (issue #953): context, requirement set, monitor profile,
    #: registry, planner and budget the composition reached ACCEPT under.
    #: Absent unless WS1 runs in enforce mode, and omitted from the hash when
    #: empty, so a context without it hashes exactly as before. Redemption
    #: recomputes it from a fresh WS1 re-gate, so a moved requirement or a
    #: precondition no longer proved refuses as context_mismatch.
    ws1_binding_hash: str = ""
    #: Digest of the plan premises a call carried (Q7.5,
    #: :meth:`remora.governance.plan_binding.PlanBinding.digest`). Bound only
    #: on the ACCEPT path, where no approval envelope covers the plan
    #: (AACP-F-01): a token decided while a plan read one revision is refused,
    #: unspent, when its call is presented with a plan rewritten to read
    #: another. Omitted from the hash when empty, so a call without a plan
    #: hashes exactly as before.
    plan_hash: str = ""

    def hash(self) -> str:
        # The optional fields are omitted rather than defaulted to "" (see
        # to_dict): a key present with an empty value changes the preimage
        # exactly as much as a populated one, so defaulting would rewrite the
        # hash of every existing context.
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def task_identity(self) -> "TaskIdentity | None":
        """The bound task, or None when this context carries none.

        A context holding exactly one half is a caller error rather than a
        partial binding, and ``TaskIdentity.from_fields`` refuses it.
        """
        from remora.governance.task_identity import TaskIdentity

        return TaskIdentity.from_fields(
            {
                "context_id": self.context_id or None,
                "task_id": self.task_id or None,
            }
        )

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
                "context_id",
                "task_id",
                "execution_context_hash",
                "request_ref_hash",
                "delegated_executor",
                "ws1_binding_hash",
                "plan_hash",
            )
            if (getattr(self, name) or "") != (getattr(other, name) or "")
        ]

    def to_dict(self) -> dict[str, str]:
        """The fields :meth:`hash` covers, under the same omit-when-empty rule.

        Exported beside a grant so a verifier can recompute ``context_hash``
        without importing this class.
        """
        out = {
            "intent_authority_hash": self.intent_authority_hash or "",
            "policy_bundle_hash": self.policy_bundle_hash or "",
            "principal": self.principal or "",
            "target_environment": self.target_environment or "",
            "tenant": self.tenant or "",
            "toolspec_hash": self.toolspec_hash or "",
        }
        for name in ("context_id", "task_id", "execution_context_hash",
                     "request_ref_hash", "delegated_executor", "ws1_binding_hash",
                     "plan_hash"):
            if getattr(self, name):
                out[name] = getattr(self, name)
        return out


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
    format: str = "",
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
    if format:
        payload["format"] = format
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


#: The token formats. "" is v1, frozen: no format field, untagged preimage.
FORMAT_V1 = ""
FORMAT_V2 = "v2"
#: Ed25519 in REMORA/POLICY-GRANT/v3, with a derived kid (RMR-CR-002).
FORMAT_V3 = "v3"
_FORMATS = (FORMAT_V1, FORMAT_V2, FORMAT_V3)


class GrantMintingRefused(RuntimeError):
    """This process holds verification material only and must not mint grants.

    Raised instead of issuing an unsigned token: an unsigned token from a
    verify-only redeemer would be exactly the forgery the split exists to
    prevent, merely labelled honestly.
    """

    code = "grant_minting_refused"


def _compute_signature(payload_bytes: bytes, key: bytes, format: str = FORMAT_V1) -> str:
    if format == FORMAT_V2:
        from remora.crypto import SignatureDomain, preimage

        payload_bytes = preimage(SignatureDomain.POLICY_GRANT, payload_bytes)
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
    if serializable.get("execution_context_hash") == "":
        serializable = {k: v for k, v in serializable.items() if k != "execution_context_hash"}
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
    #: Signature format (RMR-CR-011): "" is v1 (frozen), "v2" is the
    #: REMORA/POLICY-GRANT/v2 domain (HMAC), "v3" is Ed25519 in
    #: REMORA/POLICY-GRANT/v3 (RMR-CR-002). Signed when set, so it cannot be stripped.
    format: str = ""

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

        issued_dt = datetime.fromisoformat(issued_at)
        if expires_at is None:
            # Expiry is mandatory (closes the legacy no-expiry replay window):
            # compute the default TTL when the issuer does not set one.
            expires_at = (
                issued_dt + timedelta(seconds=DEFAULT_TOKEN_TTL_SECONDS)
            ).isoformat()
        else:
            expiry_dt = datetime.fromisoformat(expires_at)
            ttl = (expiry_dt - issued_dt).total_seconds()
            if ttl <= 0 or ttl > MAX_TOKEN_TTL_SECONDS:
                raise ValueError(
                    f"token TTL must be in (0, {MAX_TOKEN_TTL_SECONDS}] seconds, got {ttl}"
                )
        jti = str(_uuid.uuid4())
        context_hash = context.hash() if context is not None else ""
        from remora.crypto.formats import signature_format

        issuer = os.environ.get(_ENV_ISSUER, "").strip()
        if _ed25519_seed():
            from remora.crypto import SignatureDomain, sign

            signing_key = _v3_signing_key()
            payload = _canonical_payload(
                action, observation_hash, request_id, issued_at, expires_at,
                jti, audience, signing_key.kid, issuer, context_hash, FORMAT_V3,
            )
            return cls(
                action=action, observation_hash=observation_hash,
                request_id=request_id, issued_at=issued_at,
                signature=sign(SignatureDomain.POLICY_GRANT_ASYMMETRIC, payload,
                               signing_key).value,
                is_signed=True, expires_at=expires_at, jti=jti, audience=audience,
                kid=signing_key.kid, issuer=issuer, context_hash=context_hash,
                format=FORMAT_V3,
            )
        if verify_only():
            raise GrantMintingRefused(
                "this process holds only REMORA_PDP_VERIFY_KEYS_ED25519: it redeems "
                "decision grants and cannot mint them (RMR-CR-002)")
        token_format = FORMAT_V2 if signature_format() == "v2" else FORMAT_V1
        key = _get_signing_key()
        kid = _current_kid()
        if key:
            payload = _canonical_payload(
                action, observation_hash, request_id, issued_at, expires_at,
                jti, audience, kid, issuer, context_hash, token_format,
            )
            sig = _compute_signature(payload, key, token_format)
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
                format=token_format,
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
            format=token_format,
        )

    def signed_payload(self) -> bytes:
        """The exact bytes this token's signature covers, before any domain tag."""
        return _canonical_payload(
            self.action, self.observation_hash, self.request_id, self.issued_at,
            self.expires_at, self.jti, self.audience, self.kid, self.issuer,
            self.context_hash, self.format,
        )

    def verify_historical(self) -> TokenVerificationResult:
        """The signature only, as evidence: never an authorization (CR-011).

        For historical evidence, offline replay and migration diagnostics. A
        v1 token that a strict v2 contract refuses as live authority verifies
        here as ``historical_v1``; expiry, issuer and bindings are not
        checked, because nothing is being authorized.
        """
        refused = self._signature_refusal(live=False)
        if refused is not None:
            return refused
        return TokenVerificationResult(
            verified=True, is_signed=True,
            reason="historical_v1" if self.format == FORMAT_V1 else "ok")

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
        refused = self._signature_refusal(live=True)
        if refused is not None:
            return refused

        # RMR-CR-002: the issuer was signed but never compared. When this
        # process names an expected issuer, a token from any other issuer is
        # refused, even with a valid signature under a shared key.
        expected_issuer = os.environ.get(_ENV_ISSUER, "").strip()
        if expected_issuer and self.issuer != expected_issuer:
            return TokenVerificationResult(
                verified=False,
                reason="issuer_mismatch",
                is_signed=True,
            )

        return self.check_bindings(observation_hash, now=now, context=context)

    def _signature_refusal(self, *, live: bool) -> TokenVerificationResult | None:
        """Why the signature does not hold, or None when it does.

        ``live`` is whether the token is presented as authority: under a
        strict v2 contract a live v1 token is refused (``token_format_legacy``)
        without being read further.
        """
        if self.format == FORMAT_V3:
            return self._v3_refusal(live=live)
        if self.format not in _FORMATS:
            return TokenVerificationResult(
                verified=False, reason="token_format_unknown", is_signed=True)
        if live and not hmac_accepted():
            # Refused as policy, not as a signature verdict, so the audit trail
            # tells a downgrade attempt or a stale issuer from a forgery.
            return TokenVerificationResult(
                verified=False, reason="token_hmac_refused", is_signed=self.is_signed)
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
        if live and self.format == FORMAT_V1:
            from remora.crypto.formats import v1_live_refused

            if v1_live_refused():
                return TokenVerificationResult(
                    verified=False, reason="token_format_legacy", is_signed=True)

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

        payload = self.signed_payload()

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
            # A kid-less token never names the key it was signed with, so the
            # revocation list has to be applied to the keys themselves: a
            # revoked kid's key must not stay a candidate just because the
            # token omits the kid.
            revoked = _revoked_kids()
            candidate_keys = [] if _current_kid() in revoked else [key]
            candidate_keys += [
                k for kid, k in _previous_keys().items() if kid not in revoked
            ]
            if not candidate_keys:
                return TokenVerificationResult(
                    verified=False,
                    reason="kid_revoked",
                    is_signed=True,
                )

        sig_ok = any(
            hmac.compare_digest(_compute_signature(payload, k, self.format), self.signature)
            for k in candidate_keys
        )
        if not sig_ok:
            return TokenVerificationResult(
                verified=False,
                reason="signature_invalid",
                is_signed=True,
            )
        return None

    def _v3_refusal(self, *, live: bool) -> TokenVerificationResult | None:
        """The v3 signature: Ed25519 against the configured verify keys only.

        No HMAC key is read or needed, which is what lets a redeemer hold
        nothing that can mint.
        """
        if not self.is_signed or not self.signature:
            return TokenVerificationResult(
                verified=False, reason="token_not_signed", is_signed=False)
        from remora.crypto import ALGORITHM, Signature, SignatureDomain, verify

        try:
            keys = _v3_verification_keys()
        except (ValueError, RuntimeError):
            # A configured key that cannot be decoded is "cannot check", never
            # "checked and fine", and never a crash in the gate.
            return TokenVerificationResult(
                verified=False, reason="verification_key_unusable", is_signed=True)
        if not keys:
            return TokenVerificationResult(
                verified=False, reason="no_verification_key", is_signed=True)
        payload = self.signed_payload()
        domain = SignatureDomain.POLICY_GRANT_ASYMMETRIC
        result = verify(domain, payload,
                        Signature(ALGORITHM, domain.value, self.kid, self.signature),
                        keys, revoked=_revoked_kids() if live else ())
        if result.ok:
            return None
        reason = {"key_revoked": "kid_revoked", "unknown_kid": "unknown_kid"}.get(
            result.reason, "signature_invalid")
        return TokenVerificationResult(verified=False, reason=reason, is_signed=True)

    def check_bindings(
        self,
        observation_hash: str | None = None,
        now: str | None = None,
        context: "AuthorizationContext | None" = None,
        require_expiry: bool = True,
    ) -> TokenVerificationResult:
        """Every check that binds this token to the request it is redeemed on.

        Split out of :meth:`verify` so the two questions stay separable:
        the signature answers *who minted this*, these answer *was it minted
        for this request*. The signature checks return early on an unsigned
        token, which silently skipped all of this for a non-strict gate --
        a token bound to one observation authorised another. The gate now
        runs these on the unsigned path too, so ``strict=False`` waives the
        signature and nothing else.

        ``require_expiry`` is relaxed only on that unsigned development
        path, where a hand-built legacy token carries no expiry and the
        gate's own maximum-age bound stands in for it.
        """
        if context is not None:
            if not self.context_hash:
                return TokenVerificationResult(
                    verified=False,
                    reason="context_unbound",
                    is_signed=self.is_signed,
                )
            if self.context_hash != context.hash():
                return TokenVerificationResult(
                    verified=False,
                    reason="context_mismatch",
                    is_signed=self.is_signed,
                )

        if self.expires_at is None and require_expiry:
            # Mandatory-expiry policy: legacy no-expiry tokens are rejected
            # outright (audit finding F-2 / replay review finding).
            return TokenVerificationResult(
                verified=False,
                reason="missing_expiry",
                is_signed=self.is_signed,
            )
        if self.expires_at is not None:
            from datetime import datetime

            try:
                issued = datetime.fromisoformat(self.issued_at)
                expiry = datetime.fromisoformat(self.expires_at)
                current = (
                    datetime.fromisoformat(now)
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
                    is_signed=self.is_signed,
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
                    is_signed=self.is_signed,
                )
            if current >= expiry:
                return TokenVerificationResult(
                    verified=False,
                    reason="token_expired",
                    is_signed=self.is_signed,
                )

        if observation_hash is not None and observation_hash != self.observation_hash:
            return TokenVerificationResult(
                verified=False,
                reason="observation_hash_mismatch",
                is_signed=self.is_signed,
            )

        return TokenVerificationResult(
            verified=True,
            reason="ok",
            is_signed=self.is_signed,
        )

    def to_dict(self) -> dict[str, Any]:
        """Complete serialisation — every signed field round-trips.

        ``format`` appears only on v2 and v3 tokens, so a v1 token serialises
        exactly as it did before v2 existed.
        """
        out = {
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
        if self.format:
            out["format"] = self.format
        return out

    _FIELDS = frozenset({
        "action", "observation_hash", "request_id", "issued_at",
        "expires_at", "jti", "audience", "kid", "issuer",
        "context_hash", "signature", "is_signed", "format",
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
