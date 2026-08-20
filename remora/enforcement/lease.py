# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
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
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from remora.observability.events import governance_event
from remora.policy.observation import canonical_tool_call_hash

_ENV_KEY = "REMORA_LEASE_SIGNING_KEY"
_FALLBACK_ENV_KEY = "REMORA_PDP_SIGNING_KEY"

# Leases authorize execute-now semantics: keep them short. The hard cap keeps
# an operator misconfiguration from minting hour-plus standing authorizations.
DEFAULT_LEASE_TTL_SECONDS = 120
MAX_LEASE_TTL_SECONDS = 3600


class ToolExecutionStateUnknown(RuntimeError):
    """The tool raised after its nonce was consumed: state at the tool is unknown.

    Subclasses ``RuntimeError`` so existing handlers keep working, but carries
    the identifiers an operator needs to act — this is not a retryable error
    and not a clean failure, it is the one case where REMORA knows it does not
    know what happened (issue #45).
    """

    def __init__(
        self, message: str, *, proposal_id: str = "", tenant_id: str = "",
        tool_name: str = "",
    ) -> None:
        super().__init__(message)
        self.proposal_id = proposal_id
        self.tenant_id = tenant_id
        self.tool_name = tool_name


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
    #: Hash of the frozen ToolContractRegistry bundle active at issue time.
    #: Empty string means no bundle was declared (legacy / pre-SHELF-020 path).
    tool_contract_bundle_hash: str = ""
    #: Hash identifying the frozen intent-authority source (model version +
    #: prompt + decoding params + cache SHA) active at issue time.
    intent_authority_hash: str = ""
    #: FT-03 binding chain (handoff gate §1.5): the identity of the signed
    #: ToolSpec this authorization was granted under. Bound and SIGNED, so a
    #: redeployed spec cannot be substituted at dispatch — an approval must
    #: never be reusable with a different ToolSpec.
    toolspec_hash: str = ""
    toolspec_version: int = 0
    #: Issue #45/#37: the lifecycle identity this authorization belongs to.
    #: Bound and SIGNED, so the audit chain can join an executed side effect
    #: back to the decision that authorized it without re-deriving hashes out
    #: of band. Empty string means the caller minted no proposal identity
    #: (library use, legacy path) — it is carried, never invented here.
    proposal_id: str = ""
    #: The jti of the PolicyDecisionToken consumed at the PEP for this
    #: execution. Signed for the same reason: a lease and the grant it was
    #: redeemed against must be joinable from either end.
    grant_jti: str = ""

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
        tool_contract_bundle_hash: str = "",
        intent_authority_hash: str = "",
        toolspec_hash: str = "",
        toolspec_version: int = 0,
        proposal_id: str = "",
        grant_jti: str = "",
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
            "tool_contract_bundle_hash": tool_contract_bundle_hash,
            "intent_authority_hash": intent_authority_hash,
            "toolspec_hash": toolspec_hash,
            "toolspec_version": toolspec_version,
            "proposal_id": proposal_id,
            "grant_jti": grant_jti,
        }
        key = _get_signing_key()
        if key:
            signature = cls._compute_signature(fields, key)
            lease = cls(**fields, signature=signature, is_signed=True)
        else:
            lease = cls(**fields, signature="", is_signed=False)
        governance_event(
            "lease.issued",
            decision=lease.decision,
            tenant_id=lease.tenant_id,
            tool_name=lease.tool_name,
            tool_args_hash=lease.tool_args_hash,
            target_environment=lease.target_environment,
            policy_bundle_hash=lease.policy_bundle_hash,
            expires_at=lease.expires_at,
            signed=lease.is_signed,
            proposal_id=lease.proposal_id,
            grant_jti=lease.grant_jti,
        )
        return lease

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
            "tool_contract_bundle_hash": self.tool_contract_bundle_hash,
            "intent_authority_hash": self.intent_authority_hash,
            "toolspec_hash": self.toolspec_hash,
            "toolspec_version": self.toolspec_version,
            "proposal_id": self.proposal_id,
            "grant_jti": self.grant_jti,
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
        actor_identity: str | None = None,
        toolspec_hash: str | None = None,
        toolspec_version: int | None = None,
        expected_proposal_id: str | None = None,
    ) -> LeaseVerificationResult:
        """Verify signature, expiry, and the full binding against a concrete call.

        Every check fails closed; the first failed check names the reason.

        ``actor_identity`` is the authenticated identity of the caller
        presenting the lease. A lease issued to a named actor is enforced:
        presenting it without an actor identity, or with a different one,
        is refused. The identity string must come from an authenticated
        transport context, never from the request body; transport-anchored
        workload identity (credential/key ID binding) is REM-024 residual
        scope.
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
        # Actor binding: a lease issued to a named actor may only be used by
        # that actor. actor_identity was previously signed audit metadata but
        # never enforced at dispatch (external review 2026-07-24, F-02); a
        # stolen lease was usable by any caller with matching tenant/tool/args.
        if self.actor_identity:
            if actor_identity is None:
                return LeaseVerificationResult(False, "actor_identity_required")
            if not hmac.compare_digest(
                actor_identity.encode(), self.actor_identity.encode()
            ):
                return LeaseVerificationResult(False, "actor_identity_mismatch")
        if (target_environment or "") != self.target_environment:
            return LeaseVerificationResult(False, "target_environment_mismatch")
        # FT-03: the spec at dispatch must be the spec the authorization was
        # granted under. An absent binding is NOT a wildcard — a lease issued
        # before spec binding existed must not verify against a spec-bearing
        # check, or upgrading the check would silently amnesty old leases.
        if toolspec_hash is not None:
            if not hmac.compare_digest(
                (self.toolspec_hash or "").encode(), toolspec_hash.encode()
            ):
                return LeaseVerificationResult(False, "toolspec_hash_mismatch")
        if toolspec_version is not None and toolspec_version != self.toolspec_version:
            return LeaseVerificationResult(False, "toolspec_version_mismatch")
        recomputed = canonical_tool_call_hash(
            name=tool_name,
            arguments=arguments,
            tenant=tenant_id,
            target=target_environment,
        )
        if not hmac.compare_digest(recomputed, self.tool_args_hash):
            return LeaseVerificationResult(False, "tool_args_hash_mismatch")
        if expected_policy_bundle_hash is not None:
            # A lease with no bundle identity can never satisfy a binding
            # check — "" == "" previously passed, so an unset config value
            # silently disabled the protection (issue #16). Constant-time
            # compare for parity with the signature/actor/args checks.
            if not self.policy_bundle_hash:
                return LeaseVerificationResult(False, "policy_bundle_missing")
            if not hmac.compare_digest(
                expected_policy_bundle_hash.encode(), self.policy_bundle_hash.encode()
            ):
                return LeaseVerificationResult(False, "policy_bundle_mismatch")
        if expected_proposal_id is not None:
            # Same fail-closed shape as the bundle check above: a lease with no
            # lifecycle identity can never satisfy a binding check, so an unset
            # caller value cannot silently disable it.
            if not self.proposal_id:
                return LeaseVerificationResult(False, "proposal_binding_missing")
            if not hmac.compare_digest(
                expected_proposal_id.encode(), self.proposal_id.encode()
            ):
                return LeaseVerificationResult(False, "proposal_mismatch")
        return LeaseVerificationResult(True, "ok")

    def to_dict(self) -> dict[str, Any]:
        return {**self._signed_fields(), "signature": self.signature, "is_signed": self.is_signed}

    _FIELDS = frozenset({
        "decision", "tenant_id", "actor_identity", "tool_name", "tool_args_hash",
        "target_environment", "policy_bundle_hash", "nonce", "issued_at",
        "expires_at", "signature", "is_signed",
        "tool_contract_bundle_hash", "intent_authority_hash",
        "toolspec_hash", "toolspec_version",
        "proposal_id", "grant_jti",
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

    In-process only (threading.Lock + set). A nonce consumed in one process
    is unknown to another, so a lease is single-use *per process*, not
    globally: with several workers, or after a restart, the same lease can be
    dispatched again.

    Unlike ``EnforcementGate``'s consumed-jti ledger, which does persist to
    ``pep_consumed`` when a DSN or SQLite path is supplied, this ledger has
    no durable adapter. Deployments that run more than one dispatcher process
    must not treat a lease nonce as a global single-use guarantee. Durable,
    multi-process storage is REM-025 scope.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._consumed: set[str] = set()
        self._failed: dict[str, str] = {}

    def consume(self, nonce: str) -> bool:
        """Return True exactly once per nonce; False on any replay."""
        with self._lock:
            if nonce in self._consumed:
                return False
            self._consumed.add(nonce)
            return True

    def fail_consume(self, nonce: str, reason: str) -> None:
        """Record that this nonce was burned by a tool that raised."""
        with self._lock:
            self._failed[nonce] = reason

    def failure(self, nonce: str) -> str | None:
        """The recorded failure for a burned nonce, or None.

        Lets the dispatcher distinguish a plain replay from a retry after a
        failed execution with unknown state — and gives post-mortems the
        original error instead of a write-only record.
        """
        with self._lock:
            return self._failed.get(nonce)


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of a GovernedToolDispatcher.dispatch() call."""

    executed: bool
    refusal_reason: str | None = None
    result: Any = None
    #: Issue #45: the lifecycle identity carried out of the dispatcher, so a
    #: recorded effect joins back to the decision without re-deriving hashes.
    #: Empty when the refusal happened before a lease was available to read it
    #: from — a missing lease has no identity to report, and inventing one here
    #: would be worse than the gap.
    proposal_id: str = ""


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
        expected_policy_bundle_hash: str,
        ledger: NonceLedger | None = None,
    ) -> None:
        if not expected_policy_bundle_hash:
            raise ValueError("expected_policy_bundle_hash is mandatory to prevent stale policy execution")
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
        actor_identity: str | None = None,
    ) -> DispatchResult:
        """Execute ``tool_name`` iff the lease covers this exact call.

        ``actor_identity`` must be the AUTHENTICATED identity of the caller
        (transport/session context), never taken from the payload the agent
        controls. A lease issued to a named actor refuses to dispatch without
        a matching identity.
        """
        if lease is None:
            governance_event(
                "dispatch.refused", level=logging.WARNING,
                reason="missing_lease", tenant_id=tenant_id, tool_name=tool_name,
                proposal_id="",
            )
            return DispatchResult(executed=False, refusal_reason="missing_lease")
        proposal_id = lease.proposal_id
        if tool_name not in self._tools:
            governance_event(
                "dispatch.refused", level=logging.WARNING,
                reason="unknown_tool", tenant_id=tenant_id, tool_name=tool_name,
                proposal_id=proposal_id,
            )
            return DispatchResult(
                executed=False, refusal_reason="unknown_tool",
                proposal_id=proposal_id,
            )

        fn = self._tools[tool_name]
        verdict = lease.verify(
            tool_name=tool_name, arguments=arguments,
            tenant_id=tenant_id,
            target_environment=target_environment or "",
            now=now,
            expected_policy_bundle_hash=self._expected_bundle,
            actor_identity=actor_identity,
        )
        if not verdict.verified:
            governance_event(
                "dispatch.refused", level=logging.WARNING,
                reason=verdict.reason, tenant_id=tenant_id, tool_name=tool_name,
                proposal_id=proposal_id, grant_jti=lease.grant_jti,
            )
            return DispatchResult(
                executed=False, refusal_reason=verdict.reason,
                proposal_id=proposal_id,
            )
        if not self._ledger.consume(lease.nonce):
            # A nonce burned by a raising tool is not a plain replay: the
            # caller must learn the previous attempt failed with unknown
            # state, not merely that the nonce was used.
            failure = getattr(self._ledger, "failure", lambda _n: None)(lease.nonce)
            reason = (
                "nonce_consumed_by_failed_execution"
                if failure is not None
                else "nonce_already_consumed"
            )
            governance_event(
                "dispatch.refused", level=logging.WARNING,
                reason=reason, tenant_id=tenant_id, tool_name=tool_name,
                proposal_id=proposal_id, grant_jti=lease.grant_jti,
            )
            return DispatchResult(
                executed=False, refusal_reason=reason, proposal_id=proposal_id,
            )

        # execution
        try:
            res = fn(arguments)
            governance_event(
                "dispatch.executed",
                tenant_id=tenant_id, tool_name=tool_name,
                proposal_id=proposal_id, grant_jti=lease.grant_jti,
                tool_args_hash=lease.tool_args_hash,
            )
            return DispatchResult(
                executed=True, result=res, proposal_id=proposal_id,
            )
        except Exception as e:
            # Burn is recorded with its reason so failure() can surface it;
            # the nonce stays consumed — state at the tool is unknown.
            if hasattr(self._ledger, "fail_consume"):
                self._ledger.fail_consume(lease.nonce, str(e))
            # The single most alert-worthy condition in the system used to
            # raise a bare RuntimeError with no log line and no distinct type
            # (issue #45 item 2). It is now both: an ERROR-level governance
            # event carrying the lifecycle identity, and a named exception a
            # handler can route on without matching message text.
            governance_event(
                "dispatch.state_unknown", level=logging.ERROR,
                tenant_id=tenant_id, tool_name=tool_name,
                proposal_id=proposal_id, grant_jti=lease.grant_jti,
                nonce_burned=True, error_type=type(e).__name__,
            )
            raise ToolExecutionStateUnknown(
                f"Tool execution failed, nonce burned and state unknown/failed: {e}",
                proposal_id=proposal_id,
                tenant_id=tenant_id,
                tool_name=tool_name,
            ) from e
