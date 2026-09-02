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

INTEGRATION STATUS: library-level PEP. Durable, multi-process nonce storage is
implemented and wired (``nonce_store.DurableNonceStore`` over Postgres/SQLite/D1);
its activation is configuration/profile dependent and is not claimed as
production evidence. Deployment integration in front of real tool credentials
and external validation remain open under REM-024/REM-030 in
docs/assurance/remediation_register.yaml. Do not cite this module alone as
evidence of integrated, unbypassable enforcement.
"""
from __future__ import annotations

from remora.errors import RemoraError

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

from remora.enforcement import lease_signing as _signing
from remora.enforcement.nonce_store import NonceStore, NonceStoreUnavailable
from remora.observability.events import governance_event
from remora.policy.observation import canonical_tool_call_hash

_ENV_KEY = "REMORA_LEASE_SIGNING_KEY"
_FALLBACK_ENV_KEY = "REMORA_PDP_SIGNING_KEY"

# Leases authorize execute-now semantics: keep them short. The hard cap keeps
# an operator misconfiguration from minting hour-plus standing authorizations.
DEFAULT_LEASE_TTL_SECONDS = 120
MAX_LEASE_TTL_SECONDS = 3600


class ToolExecutionStateUnknown(RemoraError, RuntimeError):
    """The tool raised after its nonce was consumed: state at the tool is unknown.

    Subclasses ``RuntimeError`` so existing handlers keep working, but carries
    the identifiers an operator needs to act — this is not a retryable error
    and not a clean failure, it is the one case where REMORA knows it does not
    know what happened (issue #45).
    """

    code = "tool_execution_state_unknown"
    category = "enforcement"

    def __init__(
        self, message: str, *, proposal_id: str = "", tenant_id: str = "",
        tool_name: str = "",
    ) -> None:
        super().__init__(message)
        self.proposal_id = proposal_id
        self.tenant_id = tenant_id
        self.tool_name = tool_name


class LeaseRefused(RemoraError):
    """Raised when a lease cannot be issued (non-accept decision)."""

    code = "lease_refused"
    category = "enforcement"


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
    #: ADR-A: the signature scheme, carried INSIDE the signed payload so an
    #: attacker cannot strip ed25519 down to hmac-sha256 without invalidating
    #: the signature over the field they changed.
    sig_alg: str = _signing.ALG_HMAC
    #: Key identifier, so rotation and multi-key verification do not need a
    #: flag day. Empty when the deployment runs a single key.
    kid: str = ""
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
    #: ADR-D: the identity hash of the runtime this authorization was granted
    #: under (see :mod:`remora.enforcement.runtime_identity`). Bound and
    #: SIGNED, so the executing process can refuse a lease minted for a
    #: different deployment, image or worker generation — the one case where
    #: every other bound field can match and the action still ran against an
    #: implementation nobody authorized. Empty string means the authorizing
    #: side declared no runtime; it is carried, never invented here.
    runtime_identity_hash: str = ""

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
        runtime_identity_hash: str = "",
    ) -> ExecutionLease:
        """Issue a lease for an ACCEPTED decision; refuse everything else.

        ``issued_at`` is a UTC ISO-8601 string supplied by the caller (same
        convention as PolicyDecisionToken.issue, keeps issuance testable).
        """
        if decision != "accept":
            raise LeaseRefused(
                f"execution lease refused: decision {decision!r} is not 'accept'"
            )
        from remora.enforcement.custody import assert_may_mint_authority

        assert_may_mint_authority()
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
            "runtime_identity_hash": runtime_identity_hash,
        }
        alg = _signing.issuer_algorithm()
        if alg:
            # sig_alg and kid are inside the payload the signature covers.
            fields["sig_alg"] = alg
            fields["kid"] = _signing.issuer_kid()
            signature = _signing.sign_payload(
                cls._canonical_payload(fields), alg=alg
            )
            lease = cls(**fields, signature=signature, is_signed=True)
        elif _signing.public_key_only():
            # Found by tests/test_lease_authority_custody.py: a process holding
            # ONLY verification material silently produced an UNSIGNED lease
            # here instead of refusing. Not directly exploitable — verify()
            # rejects an unsigned lease — but "quietly emit a degraded
            # authority object" is the failure mode this ADR exists to remove,
            # and a caller that asked for a lease and got one has no reason to
            # suspect it is worthless. A verifier must not be able to produce
            # an authority object at all, valid or otherwise.
            raise LeaseRefused(
                "this process holds only lease VERIFICATION material and "
                "cannot issue authority; issuing requires the PDP private key"
            )
        else:
            lease = cls(**fields, sig_alg=_signing.ALG_HMAC, kid="",
                        signature="", is_signed=False)
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
    def _canonical_payload(fields: dict[str, Any]) -> bytes:
        """The exact bytes a lease signature covers.

        Built from typed fields rather than parsed out of a self-describing
        token: the verifier reconstructs what it expects and compares, so a
        presenter cannot influence which bytes get checked.
        """
        return json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()

    @staticmethod
    def _compute_signature(fields: dict[str, Any], key: bytes) -> str:
        """HMAC signature over the canonical payload. Retained for the
        migration window and for callers that pass an explicit key."""
        return hmac.new(
            key, ExecutionLease._canonical_payload(fields), hashlib.sha256
        ).hexdigest()

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
            "runtime_identity_hash": self.runtime_identity_hash,
            "sig_alg": self.sig_alg,
            "kid": self.kid,
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
        if not self.is_signed or not self.signature:
            return LeaseVerificationResult(False, "lease_not_signed")
        payload = self._canonical_payload(self._signed_fields())
        try:
            signature_ok = _signing.verify_payload(
                payload, self.signature, alg=self.sig_alg
            )
        except _signing.SigningUnavailable as exc:
            # Cannot reach a verdict. Never reported as a valid signature, and
            # kept distinct from "forged" so a downgrade attempt or a missing
            # key is diagnosable as itself.
            reason = (
                "signature_algorithm_refused"
                if self.sig_alg == _signing.ALG_HMAC
                else "no_signing_key"
            )
            governance_event(
                "lease.verification_unavailable", level=logging.WARNING,
                sig_alg=self.sig_alg, tenant_id=self.tenant_id,
                tool_name=self.tool_name, detail=str(exc),
            )
            return LeaseVerificationResult(False, reason)
        if not signature_ok:
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
        "proposal_id", "grant_jti", "runtime_identity_hash", "sig_alg", "kid",
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

    A durable adapter DOES exist and is wired: ``DurableNonceStore`` in
    ``remora/enforcement/nonce_store.py``, constructed by
    ``servers/execution_api.py::_lease_nonce_store`` from the same three
    variables as the durability guard in ``servers/api.py`` and passed to the
    dispatcher. This class is the library default for deployments that
    configure none of them, and the control in the durability tests. It is
    not a fallback: falling back to it when a configured backend fails would
    silently reintroduce the replay window.

    So the limitation is narrower than "no durable storage exists". It is
    that a deployment which configures no backend keeps a per-process
    guarantee, and that activation on any particular deployment is
    unclaimed (CAP-013 caveat).

    Corrected 2026-08-30: this docstring previously said the ledger had no
    durable adapter and attributed the work to REM-025. Both were wrong.
    ``nonce_store.py`` shipped before that text was last read, and REM-025 is
    "Durable audit integrity", an unrelated item. Documentation that
    understates the code is still a defect: it sends a reader looking for
    something that is already there, and an auditor to the wrong register
    entry.
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
    #: Whether the registered callable was actually invoked.
    #:
    #: Structural, and reported by the only component that knows. Settlement
    #: used to infer this from ``refusal_reason``, so FAILED was decided by
    #: string matching and every new refusal reason silently reclassified an
    #: outcome. A dispatch that never began is the one negative claim REMORA
    #: can make first-hand; one that began and then raised is not.
    dispatch_began: bool = False
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
        nonce_store: "NonceStore | None" = None,
    ) -> None:
        """
        ``nonce_store`` (ADR-B) makes single-use consumption durable and
        tenant-scoped. When supplied it REPLACES the in-process ledger for the
        consume decision: a lease then spends exactly once across restarts,
        replacement containers and independent dispatcher instances, which the
        ``NonceLedger`` set cannot do and does not claim to.

        The in-process ledger stays the default so library and research use are
        unaffected. Deployments are compelled by the durability guard in
        ``servers/api.py``, which is where compulsion belongs.
        """
        if not expected_policy_bundle_hash:
            raise ValueError("expected_policy_bundle_hash is mandatory to prevent stale policy execution")
        self._tools: dict[str, Callable[[Any], Any]] = {}
        self._expected_bundle = expected_policy_bundle_hash
        self._ledger = ledger or NonceLedger()
        self._nonce_store = nonce_store
        self._spec_identity: Callable[[str], tuple[str, int] | None] | None = None

    def bind_toolspec_identity(
        self, resolver: "Callable[[str], tuple[str, int] | None]"
    ) -> None:
        """Supply the signed spec identity this process would run RIGHT NOW.

        ``ExecutionLease`` has always carried ``toolspec_hash`` and
        ``toolspec_version``, and ``verify`` has always been able to check
        them. Nothing supplied them, so the signed spec identity was inside
        the signature and inert at the final PEP (RMR-004): the lease proved
        which spec was approved and nothing compared it to the spec about to
        run.

        The resolver returns ``None`` when this process has no bundle
        configured, which is the unenforced research path and stays permitted.
        It must not be used to express "I could not look it up" -- see
        ``dispatch``, which refuses on a raise rather than treating a failed
        lookup as an absent bundle.
        """
        self._spec_identity = resolver

    def register(self, tool_name: str, fn: Callable[[Any], Any]) -> None:
        """Register the callable that actually executes ``tool_name``.

        Under a strict runtime profile the authority domain is refused here
        (property E). The callable closes over the downstream credential, so
        registering it in the process that also mints authority recreates the
        single-process configuration whose bypasses the conformance suite
        demonstrates.
        """
        from remora.enforcement.custody import assert_may_hold_tool_callables

        assert_may_hold_tool_callables()
        self._tools[tool_name] = fn

    @staticmethod
    def _runtime_refusal(lease: ExecutionLease) -> str | None:
        """Name the reason this runtime may not execute this lease, or None.

        Three cases, and the middle one is why the empty hash is a distinct
        value rather than a hash over blanks:

        - the lease names a runtime that is not this one: refuse under every
          profile. This is the discriminating case ADR-D exists for.
        - the lease names no runtime and the profile is strict: refuse, so the
          binding cannot be dropped by simply not setting it.
        - the lease names no runtime outside a strict profile: allow, and
          record that the binding was absent. Library and research use are
          unchanged, and the property is claimable only under strict.
        """
        from remora.enforcement.custody import custody_is_enforced
        from remora.enforcement.runtime_identity import current_runtime_identity_hash

        if lease.runtime_identity_hash:
            if lease.runtime_identity_hash != current_runtime_identity_hash():
                return "runtime_identity_mismatch"
            return None
        # The test is whether the LEASE carries a binding, not whether this
        # process happens to declare one: a strict deployment whose executor is
        # declared must still refuse an authorization that named no runtime,
        # or the binding could be dropped by simply never setting it at issue.
        if custody_is_enforced():
            return "runtime_identity_undeclared"
        governance_event(
            "dispatch.runtime_unbound",
            tenant_id=lease.tenant_id, tool_name=lease.tool_name,
            proposal_id=lease.proposal_id, grant_jti=lease.grant_jti,
        )
        return None

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
        # The signed spec identity, resolved at the moment of dispatch. A
        # mismatch means the spec moved between approval and execution: the
        # action about to run is not the action that was reviewed.
        #
        # A resolver that RAISES refuses. Falling through would turn "I could
        # not check" into "there was nothing to check", which is the failure
        # direction this whole file exists to avoid.
        spec_hash: str | None = None
        spec_version: int | None = None
        if self._spec_identity is not None:
            try:
                identity = self._spec_identity(tool_name)
            except Exception as exc:
                governance_event(
                    "dispatch.refused", level=logging.ERROR,
                    reason="toolspec_unresolvable", tenant_id=tenant_id,
                    tool_name=tool_name, proposal_id=proposal_id,
                    grant_jti=lease.grant_jti, detail=str(exc),
                )
                return DispatchResult(
                    executed=False, refusal_reason="toolspec_unresolvable",
                    proposal_id=proposal_id,
                )
            if identity is not None:
                spec_hash, spec_version = identity[0], int(identity[1])

        verdict = lease.verify(
            tool_name=tool_name, arguments=arguments,
            tenant_id=tenant_id,
            target_environment=target_environment or "",
            now=now,
            expected_policy_bundle_hash=self._expected_bundle,
            actor_identity=actor_identity,
            toolspec_hash=spec_hash,
            toolspec_version=spec_version,
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
        # ADR-D. The runtime binding is checked HERE rather than in verify():
        # this is a property of the place the action is performed, and verify()
        # may legitimately run anywhere. It is checked BEFORE the nonce is
        # consumed, so a rejected runtime does not burn a single-use nonce and
        # turn an authorization failure into an unknown-state incident.
        runtime_refusal = self._runtime_refusal(lease)
        if runtime_refusal is not None:
            governance_event(
                "dispatch.refused", level=logging.WARNING,
                reason=runtime_refusal, tenant_id=tenant_id,
                tool_name=tool_name, proposal_id=proposal_id,
                grant_jti=lease.grant_jti,
            )
            return DispatchResult(
                executed=False, refusal_reason=runtime_refusal,
                proposal_id=proposal_id,
            )

        if self._nonce_store is not None:
            # Durable path. An unknown outcome must refuse WITHOUT burning the
            # nonce: the grant may still be unspent, and destroying it would
            # turn a transient outage into a permanently dead authorization.
            try:
                consumed = self._nonce_store.try_consume(
                    lease.nonce, tenant_id=lease.tenant_id
                )
            except NonceStoreUnavailable as exc:
                governance_event(
                    "dispatch.refused", level=logging.ERROR,
                    reason="nonce_store_unavailable", tenant_id=tenant_id,
                    tool_name=tool_name, proposal_id=proposal_id,
                    grant_jti=lease.grant_jti, detail=str(exc),
                )
                return DispatchResult(
                    executed=False, refusal_reason="nonce_store_unavailable",
                    proposal_id=proposal_id,
                )
            if not consumed:
                governance_event(
                    "dispatch.refused", level=logging.WARNING,
                    reason="nonce_already_consumed", tenant_id=tenant_id,
                    tool_name=tool_name, proposal_id=proposal_id,
                    grant_jti=lease.grant_jti,
                )
                return DispatchResult(
                    executed=False, refusal_reason="nonce_already_consumed",
                    proposal_id=proposal_id,
                )
        elif not self._ledger.consume(lease.nonce):
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
                dispatch_began=True,
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
