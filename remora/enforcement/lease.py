# Author: Stian Skogbrott
# License: Apache-2.0
"""ExecutionLease + GovernedToolDispatcher — REM-024 groundwork.

A short-lived, HMAC-signed execution lease that binds ONE accepted decision to
ONE exact tool call, and a dispatcher (tool proxy) that refuses every
invocation not covered by a valid lease. Together they make VERIFY / ABSTAIN /
ESCALATE technically unexecutable:

  - ``ExecutionLease.issue`` raises ``LeaseRefused`` for any decision other
    than ``"accept"`` — a lease for a non-accepted action cannot exist.
  - ``GovernedToolDispatcher`` holds the tool callables (and thus any
    downstream credentials); the agent only ever holds a lease. Without a
    valid, unexpired, unconsumed lease matching the exact call, the dispatcher
    refuses.
  - The dispatcher recomputes ``canonical_tool_call_hash`` over the presented
    arguments immediately before execution, so an approved lease cannot be
    replayed for mutated arguments (security audit CLAIM 6 binding).
  - Every lease carries a single-use nonce consumed atomically at dispatch
    time, an expiry (default 120 s, hard cap 1 h), and the policy bundle hash
    that produced the decision.

Signed binding set (REM-024): tenant_id, actor_identity, tool_name,
tool_args_hash (canonical, full arguments), target_environment,
policy_bundle_hash, decision, nonce, issued_at, expires_at.

Key management: ``REMORA_LEASE_SIGNING_KEY`` (falls back to
``REMORA_PDP_SIGNING_KEY``). Without a key, issued leases are unsigned and the
dispatcher refuses them — fail closed, never fail open.

INTEGRATION STATUS: library-level PEP with in-process nonce ledger. Durable /
multi-process nonce storage, deployment integration in front of real tool
credentials, and external validation remain open under REM-024/REM-025/REM-030
in docs/assurance/remediation_register.yaml. Do not cite this module alone as
evidence of integrated, unbypassable enforcement.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from remora.policy.observation import canonical_tool_call_hash

_ENV_KEY = "REMORA_LEASE_SIGNING_KEY"
_FALLBACK_ENV_KEY = "REMORA_PDP_SIGNING_KEY"

# Leases authorize execute-now semantics: keep them short. The hard cap keeps
# an operator misconfiguration from minting hour-plus standing authorizations.
DEFAULT_LEASE_TTL_SECONDS = 120
MAX_LEASE_TTL_SECONDS = 3600


class LeaseRefused(Exception):
    """Raised when a lease cannot be issued (non-accept decision)."""


def _get_signing_key() -> bytes | None:
    for env in (_ENV_KEY, _FALLBACK_ENV_KEY):
        val = os.environ.get(env, "").strip()
        if val:
            return val.encode()
    return None


def _parse_utc(ts: str) -> datetime:
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


@dataclass(frozen=True)
class LeaseVerificationResult:
    """Result of ExecutionLease.verify()."""

    verified: bool
    reason: str


@dataclass(frozen=True)
class ExecutionLease:
    """Short-lived signed authorization for exactly one tool execution."""

    decision: str
    tenant_id: str
    actor_identity: str
    tool_name: str
    tool_args_hash: str
    target_environment: str
    policy_bundle_hash: str
    nonce: str
    issued_at: str
    expires_at: str
    signature: str
    is_signed: bool

    @classmethod
    def issue(
        cls,
        *,
        decision: str,
        tenant_id: str,
        actor_identity: str,
        tool_name: str,
        arguments: Any,
        target_environment: str,
        policy_bundle_hash: str,
        issued_at: str,
        expires_at: str | None = None,
    ) -> ExecutionLease:
        """Issue a lease for an ACCEPTED decision; refuse everything else.

        ``issued_at`` is a UTC ISO-8601 string supplied by the caller (same
        convention as PolicyDecisionToken.issue, keeps issuance testable).
        """
        if decision != "accept":
            raise LeaseRefused(
                f"execution lease refused: decision {decision!r} is not 'accept'"
            )
        issued_dt = _parse_utc(issued_at)
        if expires_at is None:
            expires_at = (
                issued_dt + timedelta(seconds=DEFAULT_LEASE_TTL_SECONDS)
            ).isoformat()
        else:
            ttl = (_parse_utc(expires_at) - issued_dt).total_seconds()
            if ttl <= 0 or ttl > MAX_LEASE_TTL_SECONDS:
                raise ValueError(
                    f"lease TTL must be in (0, {MAX_LEASE_TTL_SECONDS}] seconds, got {ttl}"
                )
        fields: dict[str, Any] = {
            "decision": decision,
            "tenant_id": tenant_id,
            "actor_identity": actor_identity,
            "tool_name": tool_name,
            "tool_args_hash": canonical_tool_call_hash(
                name=tool_name,
                arguments=arguments,
                tenant=tenant_id,
                target=target_environment,
            ),
            "target_environment": target_environment,
            "policy_bundle_hash": policy_bundle_hash,
            "nonce": str(uuid.uuid4()),
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
        key = _get_signing_key()
        if key:
            signature = cls._compute_signature(fields, key)
            return cls(**fields, signature=signature, is_signed=True)
        return cls(**fields, signature="", is_signed=False)

    @staticmethod
    def _compute_signature(fields: dict[str, Any], key: bytes) -> str:
        payload = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(key, payload, hashlib.sha256).hexdigest()

    def _signed_fields(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "tenant_id": self.tenant_id,
            "actor_identity": self.actor_identity,
            "tool_name": self.tool_name,
            "tool_args_hash": self.tool_args_hash,
            "target_environment": self.target_environment,
            "policy_bundle_hash": self.policy_bundle_hash,
            "nonce": self.nonce,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def verify(
        self,
        *,
        tool_name: str,
        arguments: Any,
        tenant_id: str,
        target_environment: str,
        now: str | None = None,
        expected_policy_bundle_hash: str | None = None,
    ) -> LeaseVerificationResult:
        """Verify signature, expiry, and the full binding against a concrete call.

        Every check fails closed; the first failed check names the reason.
        """
        key = _get_signing_key()
        if not key:
            return LeaseVerificationResult(False, "no_signing_key")
        if not self.is_signed or not self.signature:
            return LeaseVerificationResult(False, "lease_not_signed")
        expected_sig = self._compute_signature(self._signed_fields(), key)
        if not hmac.compare_digest(expected_sig, self.signature):
            return LeaseVerificationResult(False, "signature_invalid")
        if self.decision != "accept":
            return LeaseVerificationResult(False, "decision_not_accept")
        try:
            issued = _parse_utc(self.issued_at)
            expiry = _parse_utc(self.expires_at)
            current = _parse_utc(now) if now is not None else datetime.now(UTC)
        except (ValueError, TypeError):
            return LeaseVerificationResult(False, "expiry_unparseable")
        # Not-before: a future-dated issued_at must not mint an immediately
        # usable lease whose real lifetime exceeds the TTL cap (clock-skewed
        # or malicious issuer). The lease is valid only inside
        # [issued_at, expires_at), and issue() bounds that window to
        # MAX_LEASE_TTL_SECONDS.
        if current < issued:
            return LeaseVerificationResult(False, "lease_not_yet_valid")
        if current >= expiry:
            return LeaseVerificationResult(False, "lease_expired")
        if tool_name != self.tool_name:
            return LeaseVerificationResult(False, "tool_name_mismatch")
        if tenant_id != self.tenant_id:
            return LeaseVerificationResult(False, "tenant_mismatch")
        if (target_environment or "") != self.target_environment:
            return LeaseVerificationResult(False, "target_environment_mismatch")
        recomputed = canonical_tool_call_hash(
            name=tool_name,
            arguments=arguments,
            tenant=tenant_id,
            target=target_environment,
        )
        if not hmac.compare_digest(recomputed, self.tool_args_hash):
            return LeaseVerificationResult(False, "tool_args_hash_mismatch")
        if (
            expected_policy_bundle_hash is not None
            and expected_policy_bundle_hash != self.policy_bundle_hash
        ):
            return LeaseVerificationResult(False, "policy_bundle_mismatch")
        return LeaseVerificationResult(True, "ok")

    def to_dict(self) -> dict[str, Any]:
        return {**self._signed_fields(), "signature": self.signature, "is_signed": self.is_signed}

    _FIELDS = frozenset({
        "decision", "tenant_id", "actor_identity", "tool_name", "tool_args_hash",
        "target_environment", "policy_bundle_hash", "nonce", "issued_at",
        "expires_at", "signature", "is_signed",
    })

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionLease:
        """Reconstruct a lease; unknown keys are rejected (fail closed)."""
        unknown = set(data) - cls._FIELDS
        if unknown:
            raise ValueError(f"unknown lease fields: {sorted(unknown)}")
        return cls(**data)


class NonceLedger:
    """Atomic single-use nonce consumption.

    In-process only (threading.Lock + set) — the same limitation as
    EnforcementGate's consumed-jti set and the REM-035 execution queues.
    Durable, multi-process storage is REM-025 scope.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._consumed: set[str] = set()

    def consume(self, nonce: str) -> bool:
        """Return True exactly once per nonce; False on any replay."""
        with self._lock:
            if nonce in self._consumed:
                return False
            self._consumed.add(nonce)
            return True


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of a GovernedToolDispatcher.dispatch() call."""

    executed: bool
    refusal_reason: str | None = None
    result: Any = None


class GovernedToolDispatcher:
    """Tool proxy that refuses every execution without a valid lease.

    The dispatcher — not the agent — holds the registered tool callables and
    therefore any downstream credentials those callables close over. The agent
    presents (lease, tool_name, arguments); the dispatcher re-verifies the
    entire binding immediately before execution and consumes the lease nonce
    atomically, so a lease authorizes at most one execution of exactly the
    approved call.
    """

    def __init__(
        self,
        *,
        expected_policy_bundle_hash: str | None = None,
        ledger: NonceLedger | None = None,
    ) -> None:
        self._tools: dict[str, Callable[[Any], Any]] = {}
        self._expected_bundle = expected_policy_bundle_hash
        self._ledger = ledger or NonceLedger()

    def register(self, tool_name: str, fn: Callable[[Any], Any]) -> None:
        """Register the callable that actually executes ``tool_name``."""
        self._tools[tool_name] = fn

    def dispatch(
        self,
        lease: ExecutionLease | None,
        tool_name: str,
        arguments: Any,
        *,
        tenant_id: str = "",
        target_environment: str | None = None,
        now: str | None = None,
    ) -> DispatchResult:
        """Execute ``tool_name`` iff the lease covers this exact call."""
        if lease is None:
            return DispatchResult(executed=False, refusal_reason="missing_lease")
        fn = self._tools.get(tool_name)
        if fn is None:
            return DispatchResult(executed=False, refusal_reason="unknown_tool")
        verdict = lease.verify(
            tool_name=tool_name,
            arguments=arguments,
            tenant_id=tenant_id,
            target_environment=target_environment or "",
            now=now,
            expected_policy_bundle_hash=self._expected_bundle,
        )
        if not verdict.verified:
            return DispatchResult(executed=False, refusal_reason=verdict.reason)
        if not self._ledger.consume(lease.nonce):
            return DispatchResult(executed=False, refusal_reason="nonce_already_consumed")
        # The nonce is consumed BEFORE execution: if the tool raises, the lease
        # is burned and the caller must obtain a fresh accept. Fail closed —
        # a retry never reuses an authorization whose effect is unknown.
        return DispatchResult(executed=True, result=fn(arguments))
