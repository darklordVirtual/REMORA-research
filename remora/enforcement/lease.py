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
policy_bundle_hash, decision, nonce, issued_at, expires_at. When the
authorization was granted under a task, also context_id and task_id (quality
program Q7.2); an unbound lease signs exactly the bytes it signed before
those fields existed.

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

import copy
import hashlib
import hmac
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, ContextManager, Mapping, Sequence

from remora.enforcement import lease_signing as _signing
from remora.enforcement.nonce_store import NonceStore, NonceStoreUnavailable
from remora.observability.events import governance_event
from remora.policy.observation import canonical_tool_call_hash

if TYPE_CHECKING:
    from remora.governance.execution_identity import ExecutionContextV1, ExecutionContextProvider
    from remora.audit.recorder import RecorderClient
    from remora.capabilities.model import EffectiveCapabilitySet
    from remora.enforcement.resolved_effect import EffectResolver, ResolvedEffect
    from remora.governance.plan_binding import PlanBinding, RevisionReader
    from remora.governance.procedure import ProcedureContract, Step
    from remora.governance.task_identity import TaskIdentity

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
        #: The effects a mediated tool requested before it raised (NTA-2): an
        #: unknown parent can still carry which children executed.
        self.nested_effects: dict[str, Any] = dict(_UNMEDIATED)
        self.effect_graph: Any = None
        self.execution_context_hash = ""
        self.execution_id = ""
        self.dispatch_check: dict[str, Any] | None = None


class LeaseRefused(RemoraError):
    """Raised when a lease cannot be issued (non-accept decision)."""

    code = "lease_refused"
    category = "enforcement"


def _get_signing_key() -> bytes | None:
    # Each name read directly rather than in a loop, so the credential
    # topology scanner resolves both reads (scripts/check_credential_topology.py).
    val = (os.environ.get(_ENV_KEY, "").strip()
           or os.environ.get(_FALLBACK_ENV_KEY, "").strip())
    return val.encode() if val else None


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
    execution_context_hash: str = ""
    #: Q7.2: the task this authorization was granted under
    #: (:mod:`remora.governance.task_identity`). Signed only when set, so an
    #: unbound lease signs byte-identical bytes to one issued before these
    #: fields existed and every issued lease still verifies. Both halves or
    #: neither: a lease carrying one is refused at verification.
    context_id: str = ""
    task_id: str = ""
    #: Q7.4: digest of the effect the call resolved to when authorised
    #: (:mod:`remora.enforcement.resolved_effect`). Signed only when set, like
    #: the task fields; the dispatcher resolves again and compares.
    resolved_effect_hash: str = ""
    #: Q7.5: digest of the plan binding (:mod:`remora.governance.plan_binding`)
    #: whose premises this write depends on. Signed only when set.
    plan_binding_hash: str = ""
    #: Q3.2: digest of the tool surface observed at assessment
    #: (``RuntimeToolSurface.digest``). Signed only when set; the dispatcher
    #: compares it with the surface it observes at dispatch.
    surface_digest: str = ""
    #: Q8.2: digest of the EffectiveCapabilitySet the call was authorised
    #: under (:mod:`remora.capabilities`). Signed only when set; the
    #: dispatcher requires the matching set and checks the tool against it.
    capability_digest: str = ""

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
        execution_context: ExecutionContextV1 | None = None,
        task_identity: "TaskIdentity | None" = None,
        resolved_effect: ResolvedEffect | None = None,
        plan: PlanBinding | None = None,
        surface_digest: str = "",
        capability_set: EffectiveCapabilitySet | None = None,
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
        if execution_context is not None:
            execution_context.check_binding(
                proposal_id=proposal_id, tenant=tenant_id, principal=actor_identity,
                tool_call_hash=canonical_tool_call_hash(
                    name=tool_name, arguments=arguments, tenant=tenant_id,
                    target=target_environment))
            if (runtime_identity_hash
                    and runtime_identity_hash != execution_context.runtime.runtime_identity_hash):
                raise LeaseRefused("execution_context_runtime_mismatch")
            runtime_identity_hash = execution_context.runtime.runtime_identity_hash
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
        # Omitted when absent, never defaulted to "": a present key changes
        # the signed bytes exactly as much as a populated one.
        from remora.governance.task_identity import task_fields

        fields.update(task_fields(task_identity))
        if resolved_effect is not None:
            fields["resolved_effect_hash"] = resolved_effect.digest()
        if plan is not None:
            fields["plan_binding_hash"] = plan.digest()
        if surface_digest:
            fields["surface_digest"] = surface_digest
        if capability_set is not None:
            fields["capability_digest"] = capability_set.digest
        if execution_context is not None:
            fields["execution_context_hash"] = execution_context.digest()
        task_event_fields: dict[str, Any] = dict(task_fields(task_identity))
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
            **task_event_fields,
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

    def digest(self) -> str:
        """Identity of this exact lease: its signed fields and its signature.

        What a nested execution names as its parent (NTA-2): two leases for
        the same call differ by nonce, so they never share a digest.
        """
        return hashlib.sha256(
            ExecutionLease._canonical_payload(self._signed_fields())
            + b"." + self.signature.encode()
        ).hexdigest()

    def _signed_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {
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
        # Each half is signed when set, so a lease carrying only one is still
        # covered by its signature and is refused as malformed in verify().
        if self.context_id:
            fields["context_id"] = self.context_id
        if self.task_id:
            fields["task_id"] = self.task_id
        if self.resolved_effect_hash:
            fields["resolved_effect_hash"] = self.resolved_effect_hash
        if self.plan_binding_hash:
            fields["plan_binding_hash"] = self.plan_binding_hash
        if self.surface_digest:
            fields["surface_digest"] = self.surface_digest
        if self.capability_digest:
            fields["capability_digest"] = self.capability_digest
        if self.execution_context_hash:
            fields["execution_context_hash"] = self.execution_context_hash
        return fields

    def task_identity(self) -> "TaskIdentity | None":
        """The bound task, or None. Raises ValueError when only one half is set."""
        from remora.governance.task_identity import TaskIdentity

        return TaskIdentity.from_fields({
            "context_id": self.context_id or None,
            "task_id": self.task_id or None,
        })

    def verify_authenticity(self, *, now: str | None = None) -> LeaseVerificationResult:
        """Signature, decision and validity window, without the call binding.

        The first half of :meth:`verify`, shared so the two cannot drift. The
        effect domain (NTA-2 phase 3) uses it on its own: it serves effects
        for an execution, not a call, so it has no arguments to bind.
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
        return LeaseVerificationResult(True, "authentic")

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
        task_identity: "TaskIdentity | None" = None,
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

        ``task_identity`` is the task the call is being made under now. When
        given, the lease must have been granted under exactly that task: an
        unbound lease is ``task_unbound`` and a different task is
        ``task_mismatch``, so a caller can tell a missing binding from a
        replay into another task. When omitted, the task is not checked, the
        same convention as ``toolspec_hash``; a dispatcher that must always
        check refuses the omission itself (``require_task_identity``).
        """
        authenticity = self.verify_authenticity(now=now)
        if not authenticity.verified:
            return authenticity
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
        try:
            recomputed = canonical_tool_call_hash(
                name=tool_name,
                arguments=arguments,
                tenant=tenant_id,
                target=target_environment,
            )
        except (TypeError, ValueError):
            # Outside the JSON domain the hash would be shared with another
            # call, so there is no exact call to compare.
            return LeaseVerificationResult(False, "tool_args_not_canonical")
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
        try:
            bound_task = self.task_identity()
        except (TypeError, ValueError):
            return LeaseVerificationResult(False, "task_identity_malformed")
        if task_identity is not None:
            if bound_task is None:
                return LeaseVerificationResult(False, "task_unbound")
            if not task_identity.matches(bound_task):
                return LeaseVerificationResult(False, "task_mismatch")
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
        "context_id", "task_id", "resolved_effect_hash", "plan_binding_hash",
        "surface_digest", "capability_digest",
        "execution_context_hash",
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


#: The nested-effect summary of a tool that was not mediated. A statement
#: about the mediator, not about what the implementation did on its own.
_UNMEDIATED: dict[str, Any] = {"mediated": False, "count": 0, "settled": True}


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
    #: Q7.6: the independent recorder's sequence number for this dispatch's
    #: intent, when recording was mandatory for the tool. None otherwise.
    recorder_seq: int | None = None
    #: NTA-2: what a mediated tool asked for through its CapabilityMediator.
    #: ``nested_effects`` is the summary the audit chain carries;
    #: ``effect_graph`` the full, bounded ResolvedEffectGraph.
    nested_effects: Mapping[str, Any] = field(default_factory=lambda: dict(_UNMEDIATED))
    effect_graph: Any = None
    execution_context_hash: str = ""
    execution_id: str = ""
    dispatch_check: Mapping[str, Any] | None = None


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
        *,
        require_task_identity: bool = False,
        require_capability_set: bool = False,
        require_downstream_declaration: bool | None = None,
        require_execution_context: bool = False,
        execution_context_provider: ExecutionContextProvider | None = None,
    ) -> None:
        """
        ``require_capability_set`` (Q8.2) refuses a lease that carries no
        capability digest, so every dispatch runs under a capability set.
        Off by default for the same reason as ``require_task_identity``.

        ``require_task_identity`` (Q7.2) refuses any dispatch that does not
        present the current task, and any lease not granted under one. Off by
        default, because a caller that sends no task would be refused on
        every call; ``REMORA_REQUIRE_TASK_IDENTITY`` turns it on for the
        execution API.

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
        self._tools: dict[str, Callable[..., Any]] = {}
        self._mediated: set[str] = set()
        self._downstream_ceilings: Callable[[str], Any] | None = None
        self._effect_executors: dict[str, Callable[[str, Mapping[str, Any]], Any]] = {}
        self._registry_lock = threading.RLock()
        self._registry_versions: dict[str, int] = {}
        self._expected_bundle = expected_policy_bundle_hash
        self._ledger = ledger or NonceLedger()
        self._nonce_store = nonce_store
        self._spec_identity: Callable[[str], tuple[str, int] | None] | None = None
        self._require_task = require_task_identity
        self._require_capability = require_capability_set
        self._require_execution_context = require_execution_context
        self._execution_context_provider = execution_context_provider
        # NTA-2 phase 3: under a strict profile a mediated tool whose spec
        # declares no downstream ceiling is refused rather than run with none.
        if require_downstream_declaration is None:
            from remora.enforcement.custody import custody_is_enforced

            require_downstream_declaration = custody_is_enforced()
        self._require_declaration = require_downstream_declaration
        self._effect_domain: Any = None
        self._capability_state: Callable[[str, Any], Any] | None = None
        self._capability_epochs: Any = None
        self._effect_resolver: "EffectResolver | None" = None
        self._revisions: "RevisionReader | None" = None
        self._recorder: "RecorderClient | None" = None
        self._surface_observer: Callable[[], str] | None = None
        self._surface_enforced = False
        self._surface_digest_required = False
        #: Q3.2 shadow metrics: how many bound leases were compared with the
        #: observed surface, and how many found it changed.
        self.surface_checks = 0
        self.surface_changes = 0
        self._procedure: "tuple[ProcedureContract, Callable[[ExecutionLease], Sequence[Step]]] | None" = None
        self._recording_mandatory: Callable[[str], bool] = lambda _tool: False

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

    def bind_effect_resolver(self, resolver: "EffectResolver") -> None:
        """Resolve every call again immediately before it runs (Q7.4).

        A lease carrying ``resolved_effect_hash`` must resolve to the same
        effect now, or it refuses as ``resolved_effect_mismatch``. A reference
        the resolver does not know refuses as ``unresolved_reference``; a
        resolver that fails otherwise refuses as
        ``resolved_effect_unresolvable``, never as "nothing to check". A lease
        with no resolved effect is refused under a strict runtime profile and
        allowed, with an event, outside one.
        """
        self._effect_resolver = resolver

    def _effect_refusal(self, lease: ExecutionLease, tool_name: str,
                        arguments: Any, target_environment: str) -> str | None:
        from remora.enforcement.custody import custody_is_enforced
        from remora.enforcement.resolved_effect import UnresolvedReference

        if self._effect_resolver is None:
            if lease.resolved_effect_hash:
                governance_event(
                    "dispatch.resolved_effect_unchecked", tenant_id=lease.tenant_id,
                    tool_name=tool_name, proposal_id=lease.proposal_id)
            return None
        try:
            current = self._effect_resolver.resolve(tool_name, arguments, target_environment)
        except UnresolvedReference:
            return "unresolved_reference"
        except Exception:  # noqa: BLE001 - a failed lookup is not an absent one
            return "resolved_effect_unresolvable"
        if lease.resolved_effect_hash:
            if not hmac.compare_digest(current.digest(), lease.resolved_effect_hash):
                return "resolved_effect_mismatch"
            return None
        if custody_is_enforced():
            return "resolved_effect_unbound"
        governance_event(
            "dispatch.resolved_effect_unbound", tenant_id=lease.tenant_id,
            tool_name=tool_name, proposal_id=lease.proposal_id)
        return None

    def bind_recorder(self, recorder: "RecorderClient",
                      mandatory_for: Callable[[str], bool]) -> None:
        """Record outside this process before a named tool runs (Q7.6).

        For every tool ``mandatory_for`` accepts, the dispatch intent is
        appended to the independent recorder BEFORE the nonce is consumed. If
        the recorder cannot confirm the append the call refuses as
        ``recorder_unavailable``: an action that could not be recorded
        outside the agent's control does not happen. The outcome is appended
        afterwards; a failure there cannot undo the effect and is reported as
        an ERROR event instead.
        """
        self._recorder = recorder
        self._recording_mandatory = mandatory_for

    def _record(self, lease: ExecutionLease, tool_name: str, phase: str,
                **detail: Any) -> int | None:
        if self._recorder is None or not self._recording_mandatory(tool_name):
            return None
        receipt = self._recorder.append("dispatch", {
            "phase": phase, "tenant_id": lease.tenant_id, "tool_name": tool_name,
            "proposal_id": lease.proposal_id, "grant_jti": lease.grant_jti,
            "tool_args_hash": lease.tool_args_hash, "nonce": lease.nonce, **detail})
        return receipt.seq

    def bind_procedure(self, contract: "ProcedureContract",
                       trace_for: "Callable[[ExecutionLease], Sequence[Step]]") -> None:
        """Refuse a step that would violate the procedure's safety obligations (Q7.7).

        ``trace_for`` returns the steps already executed in the lease's
        context, from the deployment's own record. The contract is replayed
        over them and the proposed step is checked with the same automata the
        replay uses. A trace that cannot be read refuses as
        ``procedure_trace_unavailable``; a step that would violate refuses as
        ``procedure_violation``. Liveness obligations never block a step.
        """
        self._procedure = (contract, trace_for)

    def _procedure_refusal(self, lease: ExecutionLease, tool_name: str,
                           arguments: Any) -> str | None:
        if self._procedure is None:
            return None
        from remora.governance.procedure import Step, replay

        contract, trace_for = self._procedure
        try:
            trace = trace_for(lease)
        except Exception:  # noqa: BLE001 - an unreadable history is not an empty one
            return "procedure_trace_unavailable"
        refused = replay(contract, trace).admits(
            Step(tool_name, arguments if isinstance(arguments, dict) else {}))
        if not refused:
            return None
        governance_event(
            "dispatch.procedure_refused", level=logging.WARNING,
            tenant_id=lease.tenant_id, tool_name=tool_name,
            proposal_id=lease.proposal_id, contract_id=contract.contract_id,
            obligations=list(refused))
        return "procedure_violation"

    def bind_capability_epochs(self, source: Any) -> None:
        """Read the current revocation epochs at dispatch (Q8.6).

        A set issued under an older principal, tenant, policy or ToolSpec
        epoch refuses as ``capability_stale``, a revoked set as
        ``capability_revoked``, and a source that cannot answer as
        ``capability_epoch_unverifiable``.
        """
        self._capability_epochs = source

    def bind_capability_state(self, reader: Callable[[str, Any], Any]) -> None:
        """Supply the trusted-state reader capability constraints use (Q8.4)."""
        self._capability_state = reader

    def _capability_refusal(self, lease: ExecutionLease, tool_name: str,
                            tenant_id: str, target_environment: str,
                            capability_set: EffectiveCapabilitySet | None,
                            now: str | None, arguments: Any = None) -> str | None:
        """Q8.2. A lease that names a capability set runs only under that set.

        The set travels with the call and is checked against the signed
        digest, then against the call itself: the lease's actor, the tenant,
        the target environment, the set's validity window and membership.
        A lease with no digest is refused only when the dispatcher requires
        capability sets.
        """
        if not lease.capability_digest:
            return "capability_set_required" if self._require_capability else None
        if capability_set is None:
            return "capability_set_required"
        if not hmac.compare_digest(capability_set.digest, lease.capability_digest):
            return "capability_digest_mismatch"
        moment = _parse_utc(now) if now is not None else datetime.now(UTC)
        refusal = capability_set.check(
            tool_name, principal_id=lease.actor_identity, tenant_id=tenant_id,
            environment=target_environment, now=moment) or capability_set.check_arguments(
            tool_name, arguments, self._capability_state)
        if refusal is None:
            from remora.capabilities.revocation import revocation_refusal

            refusal = revocation_refusal(capability_set, self._capability_epochs)
        return refusal.value if refusal is not None else None

    def bind_surface_observer(self, observer: Callable[[], str], *,
                              enforce: bool = False,
                              require_digest: bool = False) -> None:
        """Compare the tool surface a lease was granted under with the one
        observed now (Q3.2).

        ``observer`` returns the digest of the currently offered surface. In
        shadow (``enforce=False``, the default) a changed surface is counted
        and recorded but not refused, which is the measuring period the
        design asks for before enforcement. Enforced, or under a strict
        runtime profile, a changed surface refuses as ``surface_changed`` and
        an observer that fails refuses as ``surface_unobservable``.

        ``require_digest`` (CR-006) refuses a lease that names no surface, as
        ``surface_unbound``, when enforcing. Off by default: the reference
        runtime checks its surface itself and issues leases without a digest,
        and its committed interop artifacts must not change.
        """
        self._surface_observer = observer
        self._surface_enforced = enforce
        self._surface_digest_required = require_digest

    def _surface_refusal(self, lease: ExecutionLease) -> str | None:
        if self._surface_observer is None:
            return None
        from remora.enforcement.custody import custody_is_enforced

        enforcing = self._surface_enforced or custody_is_enforced()
        if not lease.surface_digest:
            # CR-006: an observer is bound, so this dispatcher can compare,
            # and the lease names no surface to compare against. Where the
            # binding is required, an unbound surface is not an unchanged one.
            if enforcing and self._surface_digest_required:
                return "surface_unbound"
            return None
        try:
            current = self._surface_observer()
        except Exception:  # noqa: BLE001 - an unobservable surface is not an unchanged one
            return "surface_unobservable" if enforcing else None
        self.surface_checks += 1
        if hmac.compare_digest(current, lease.surface_digest):
            return None
        self.surface_changes += 1
        governance_event(
            "dispatch.surface_changed", level=logging.WARNING,
            tenant_id=lease.tenant_id, tool_name=lease.tool_name,
            proposal_id=lease.proposal_id, enforced=enforcing)
        return "surface_changed" if enforcing else None

    def bind_state_revisions(self, reader: "RevisionReader") -> None:
        """Supply current state revisions, so a plan's premises are re-read
        immediately before the write it justified (Q7.5)."""
        self._revisions = reader

    def _plan_refusal(self, lease: ExecutionLease,
                      plan: PlanBinding | None) -> str | None:
        from remora.governance.plan_binding import revalidate

        if not lease.plan_binding_hash:
            return None
        if plan is None:
            return "plan_binding_required"
        if not hmac.compare_digest(plan.digest(), lease.plan_binding_hash):
            return "plan_binding_mismatch"
        if self._revisions is None:
            # The lease asserts premises and this process cannot read them.
            return "plan_state_unverifiable"
        check = revalidate(plan, self._revisions)
        if check.refusal is not None:
            governance_event(
                "dispatch.plan_refused", level=logging.WARNING,
                tenant_id=lease.tenant_id, tool_name=lease.tool_name,
                proposal_id=lease.proposal_id, plan_id=plan.plan_id,
                reason=check.refusal, moved=list(check.moved_dependencies),
                unreadable=list(check.unreadable))
        return check.refusal

    def registered_tool_names(self) -> tuple[str, ...]:
        """A detached view of this executor's registry, not agent visibility."""
        with self._registry_lock:
            return tuple(sorted(self._tools))

    def registry_guard(self) -> ContextManager[bool]:
        """Serialize a local observation/dispatch transaction with registration."""
        return self._registry_lock

    def registration_versions(self) -> dict[str, int]:
        """Process-local generations detect replacement, including the same name."""
        with self._registry_lock:
            return dict(self._registry_versions)

    def register(self, tool_name: str, fn: Callable[..., Any], *,
                 mediated: bool = False) -> None:
        """Register the callable that actually executes ``tool_name``.

        Under a strict runtime profile the authority domain is refused here
        (property E). The callable closes over the downstream credential, so
        registering it in the process that also mints authority recreates the
        single-process configuration whose bypasses the conformance suite
        demonstrates.
        """
        from remora.enforcement.custody import assert_may_hold_tool_callables

        assert_may_hold_tool_callables()
        with self._registry_lock:
            self._tools[tool_name] = fn
            if mediated:
                self._mediated.add(tool_name)
            else:
                self._mediated.discard(tool_name)
            self._registry_versions[tool_name] = self._registry_versions.get(tool_name, 0) + 1

    def bind_downstream_ceilings(self, resolver: Callable[[str], Any]) -> None:
        """Supply each tool's declared downstream ceiling (NTA-2).

        ``resolver(tool_name)`` returns the signed ToolSpec's
        ``DownstreamCeiling``, or None when the spec declares none. A mediated
        tool without one may run, and every effect it requests refuses.
        """
        self._downstream_ceilings = resolver

    def bind_effect_executors(
            self, executors: Mapping[str, Callable[[str, Mapping[str, Any]], Any]]) -> None:
        """Register the primitives mediated effects run on (NTA-2).

        Each executor closes over the client or credential its effect needs,
        so this is refused where tool callables are (custody property E).
        """
        from remora.enforcement.custody import assert_may_hold_effect_executors

        assert_may_hold_effect_executors()
        with self._registry_lock:
            self._effect_executors = dict(executors)

    def bind_effect_domain(self, client: Any) -> None:
        """Send mediated effects to a separate effect domain (NTA-2 phase 3).

        ``client`` is a ``RemoteEffectClient``. With it bound, a mediated
        tool's effects run in the effect domain, which re-verifies the lease
        and derives the authority itself; this process then needs no effect
        credential. Local effect executors are not used.
        """
        self._effect_domain = client

    def _prepare_mediation(self, lease: ExecutionLease, tool_name: str,
                           capability_set: EffectiveCapabilitySet | None,
                           now: str | None) -> tuple[Any, str | None]:
        """The mediator for a mediated tool, or why the call is refused.

        Runs before the nonce is spent. The effect authority is derived from
        the capability set the lease is bound to, so a lease without one has
        nothing to derive from and refuses rather than running unmediated.
        """
        if tool_name not in self._mediated:
            return None, None
        if capability_set is None or not lease.capability_digest:
            return None, "capability_set_required"
        from remora.capabilities.ceiling import DownstreamCeiling
        from remora.capabilities.delegation import DelegationDenied
        from remora.enforcement.capability_mediator import CapabilityMediator
        from remora.enforcement.effect_capability import derive_effect_authority
        from remora.enforcement.execution_context import ExecutionContext

        try:
            ceiling = (self._downstream_ceilings(tool_name)
                       if self._downstream_ceilings is not None else None)
        except Exception:  # noqa: BLE001 - an unreadable ceiling is not an empty one
            return None, "downstream_ceiling_unavailable"
        if ceiling is None:
            if self._require_declaration:
                return None, "downstream_declaration_required"
            ceiling = DownstreamCeiling(tool=tool_name, capabilities=())
        moment = _parse_utc(now) if now is not None else datetime.now(UTC)
        try:
            authority = derive_effect_authority(capability_set, tool_name=tool_name,
                                                ceiling=ceiling, now=moment)
        except DelegationDenied:
            return None, "capability_delegation_denied"
        context = ExecutionContext.for_dispatch(
            tool_name=tool_name, capability_set=capability_set,
            proposal_id=lease.proposal_id, policy_bundle_hash=lease.policy_bundle_hash,
            toolspec_hash=lease.toolspec_hash, lease_digest=lease.digest(),
            context_id=lease.context_id, task_id=lease.task_id,
            runtime_identity_hash=getattr(lease, "runtime_identity_hash", "") or "")
        executors = (self._effect_domain.executors_for(
                         lease, capability_set, [c.capability for c in ceiling.capabilities])
                     if self._effect_domain is not None else self._effect_executors)
        return CapabilityMediator(
            context, authority, executors=executors,
            epochs=self._capability_epochs, state_reader=self._capability_state), None

    def _record_outcome(self, lease: ExecutionLease, tool_name: str,
                        intent_seq: int | None, outcome: str) -> None:
        """Append the outcome after the effect. Cannot refuse any more, so a
        failure is surfaced as an ERROR event rather than raised."""
        if intent_seq is None:
            return
        from remora.audit.recorder import RecorderUnavailable

        try:
            self._record(lease, tool_name, "outcome", intent_seq=intent_seq,
                         outcome=outcome)
        except RecorderUnavailable as exc:
            governance_event(
                "dispatch.recorder_outcome_unrecorded", level=logging.ERROR,
                tenant_id=lease.tenant_id, tool_name=tool_name,
                proposal_id=lease.proposal_id, intent_seq=intent_seq,
                outcome=outcome, detail=str(exc))

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
        task_identity: "TaskIdentity | None" = None,
        plan: PlanBinding | None = None,
        capability_set: EffectiveCapabilitySet | None = None,
        execution_context: ExecutionContextV1 | None = None,
    ) -> DispatchResult:
        """Execute ``tool_name`` iff the lease covers this exact call.

        ``actor_identity`` must be the AUTHENTICATED identity of the caller
        (transport/session context), never taken from the payload the agent
        controls. A lease issued to a named actor refuses to dispatch without
        a matching identity.

        ``task_identity`` is the task the call is made under, from the
        orchestration context rather than the lease; the lease is checked
        against it. See ``ExecutionLease.verify``.
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

        # The tool runs on a private copy. The caller's object stays aliased
        # outside this call, so verifying it and then executing it would leave
        # a window in which the executed call is not the verified one.
        try:
            arguments = copy.deepcopy(arguments)
        except Exception:  # noqa: BLE001 - an uncopyable payload has no exact form
            governance_event(
                "dispatch.refused", level=logging.WARNING,
                reason="tool_args_not_canonical", tenant_id=tenant_id,
                tool_name=tool_name, proposal_id=proposal_id,
            )
            return DispatchResult(
                executed=False, refusal_reason="tool_args_not_canonical",
                proposal_id=proposal_id,
            )

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

        # Read AFTER the spec is resolved, with its generation, so a callable
        # replaced during resolution is not the one that runs under the new
        # spec's identity. The generation is re-checked before the nonce is
        # spent.
        with self._registry_lock:
            fn = self._tools.get(tool_name)
            fn_generation = self._registry_versions.get(tool_name, 0)
        if fn is None:
            governance_event(
                "dispatch.refused", level=logging.WARNING,
                reason="unknown_tool", tenant_id=tenant_id, tool_name=tool_name,
                proposal_id=proposal_id,
            )
            return DispatchResult(
                executed=False, refusal_reason="unknown_tool",
                proposal_id=proposal_id,
            )

        if self._require_task and task_identity is None:
            governance_event(
                "dispatch.refused", level=logging.WARNING,
                reason="task_identity_required", tenant_id=tenant_id,
                tool_name=tool_name, proposal_id=proposal_id,
                grant_jti=lease.grant_jti,
            )
            return DispatchResult(
                executed=False, refusal_reason="task_identity_required",
                proposal_id=proposal_id,
            )

        verdict = lease.verify(
            tool_name=tool_name, arguments=arguments,
            tenant_id=tenant_id,
            target_environment=target_environment or "",
            now=now,
            expected_policy_bundle_hash=self._expected_bundle,
            actor_identity=actor_identity,
            toolspec_hash=spec_hash,
            toolspec_version=spec_version,
            task_identity=task_identity,
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
        check: dict[str, Any] | None = None
        if lease.execution_context_hash or execution_context is not None or self._require_execution_context:
            from remora.governance.execution_identity import ExecutionContextRefused
            from remora.enforcement.runtime_identity import current_runtime_identity_hash

            observed_runtime = current_runtime_identity_hash()
            check = {
                "expected_runtime_identity_hash": lease.runtime_identity_hash,
                "observed_runtime_identity_hash": observed_runtime,
                "checked_at": now or datetime.now(UTC).isoformat(),
                "result": "refused",
            }
            try:
                if execution_context is None:
                    raise ExecutionContextRefused("execution_context_missing")
                if execution_context.digest() != lease.execution_context_hash:
                    raise ExecutionContextRefused("execution_context_hash_mismatch")
                execution_context.check_binding(
                    proposal_id=lease.proposal_id, tenant=tenant_id,
                    principal=lease.actor_identity, tool_call_hash=lease.tool_args_hash)
                if (lease.runtime_identity_hash != execution_context.runtime.runtime_identity_hash
                        or observed_runtime != lease.runtime_identity_hash):
                    raise ExecutionContextRefused("runtime_identity_mismatch")
                provider = self._execution_context_provider
                if provider is None:
                    raise ExecutionContextRefused("execution_context_provider_missing")
                observed_build = provider.current_build_provenance_digest()
                check["expected_build_provenance_digest"] = execution_context.runtime.build_provenance_digest
                check["observed_build_provenance_digest"] = observed_build
                if observed_build != execution_context.runtime.build_provenance_digest:
                    raise ExecutionContextRefused("build_provenance_mismatch")
                if provider.data_scope_valid(execution_context) is not True:
                    raise ExecutionContextRefused("execution_context_data_scope_invalid")
                check["result"] = "matched"
            except ExecutionContextRefused as exc:
                check["reason"] = exc.reason
                governance_event(
                    "dispatch.refused", level=logging.WARNING, reason=exc.reason,
                    tenant_id=tenant_id, tool_name=tool_name, proposal_id=proposal_id)
                return DispatchResult(
                    executed=False, refusal_reason=exc.reason, proposal_id=proposal_id,
                    execution_context_hash=lease.execution_context_hash,
                    execution_id=lease.grant_jti, dispatch_check=check)
        if task_identity is None and (lease.context_id or lease.task_id):
            # Allowed, because the caller opted out of the check, but recorded:
            # a task-bound authorization that ran with no task compared is the
            # case an auditor needs to find.
            governance_event(
                "dispatch.task_unchecked", tenant_id=tenant_id,
                tool_name=tool_name, proposal_id=proposal_id,
                grant_jti=lease.grant_jti, context_id=lease.context_id,
                task_id=lease.task_id,
            )
        # ADR-D. The runtime binding is checked HERE rather than in verify():
        # this is a property of the place the action is performed, and verify()
        # may legitimately run anywhere. It is checked BEFORE the nonce is
        # consumed, so a rejected runtime does not burn a single-use nonce and
        # turn an authorization failure into an unknown-state incident.
        runtime_refusal = (
            self._capability_refusal(lease, tool_name, tenant_id,
                                     target_environment or "", capability_set, now,
                                     arguments)
            or self._runtime_refusal(lease)
            or self._effect_refusal(lease, tool_name, arguments, target_environment or "")
            or self._plan_refusal(lease, plan)
            or self._procedure_refusal(lease, tool_name, arguments)
            or self._surface_refusal(lease))
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
                execution_context_hash=lease.execution_context_hash,
                execution_id=lease.grant_jti, dispatch_check=check,
            )

        # NTA-2: the mediated execution's authority, prepared before anything
        # is spent so a refusal here leaves the nonce unspent too.
        mediator, mediation_refusal = self._prepare_mediation(
            lease, tool_name, capability_set, now)
        if mediation_refusal is not None:
            governance_event(
                "dispatch.refused", level=logging.WARNING,
                reason=mediation_refusal, tenant_id=tenant_id,
                tool_name=tool_name, proposal_id=proposal_id,
                grant_jti=lease.grant_jti,
            )
            return DispatchResult(
                executed=False, refusal_reason=mediation_refusal,
                proposal_id=proposal_id,
            )

        # The refusal hooks above received the verified payload and the
        # registry may have been rewritten meanwhile. Re-establish both before
        # anything is spent: the call that runs must be the call that verified.
        with self._registry_lock:
            registry_moved = (
                self._tools.get(tool_name) is not fn
                or self._registry_versions.get(tool_name, 0) != fn_generation
            )
        final_hop_refusal: str | None = None
        if registry_moved:
            final_hop_refusal = "tool_registry_changed"
        else:
            try:
                rehashed = canonical_tool_call_hash(
                    name=tool_name, arguments=arguments, tenant=tenant_id,
                    target=target_environment or "")
            except (TypeError, ValueError):
                rehashed = ""
            if not hmac.compare_digest(rehashed, lease.tool_args_hash):
                final_hop_refusal = "tool_args_changed_after_verify"
        if final_hop_refusal is not None:
            governance_event(
                "dispatch.refused", level=logging.ERROR,
                reason=final_hop_refusal, tenant_id=tenant_id,
                tool_name=tool_name, proposal_id=proposal_id,
                grant_jti=lease.grant_jti,
            )
            return DispatchResult(
                executed=False, refusal_reason=final_hop_refusal,
                proposal_id=proposal_id,
            )

        # Q7.6: recorded outside this process before anything is spent. A
        # refusal here leaves the nonce unspent, like every refusal above.
        from remora.audit.recorder import RecorderUnavailable

        try:
            recorder_seq = self._record(lease, tool_name, "intent")
        except RecorderUnavailable as exc:
            governance_event(
                "dispatch.refused", level=logging.ERROR,
                reason="recorder_unavailable", tenant_id=tenant_id,
                tool_name=tool_name, proposal_id=proposal_id,
                grant_jti=lease.grant_jti, detail=str(exc),
            )
            return DispatchResult(
                executed=False, refusal_reason="recorder_unavailable",
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
                # Same distinction the in-process branch draws below. The
                # burn is recorded in the in-process ledger on BOTH paths,
                # and this branch did not read it, so the refusal that says
                # "the previous attempt ran and its outcome is unknown" was
                # reachable only where no durable store was configured. The
                # ledger answers for this process only, so a retry landing
                # on another worker still reads nonce_already_consumed; that
                # is a weaker answer, not a wrong one.
                failure = getattr(self._ledger, "failure", lambda _n: None)(
                    lease.nonce)
                reason = (
                    "nonce_consumed_by_failed_execution"
                    if failure is not None
                    else "nonce_already_consumed"
                )
                governance_event(
                    "dispatch.refused", level=logging.WARNING,
                    reason=reason, tenant_id=tenant_id,
                    tool_name=tool_name, proposal_id=proposal_id,
                    grant_jti=lease.grant_jti,
                )
                return DispatchResult(
                    executed=False, refusal_reason=reason,
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
        def _nested() -> tuple[dict[str, Any], Any]:
            if mediator is None:
                return dict(_UNMEDIATED), None
            from remora.enforcement.effect_graph import ResolvedEffectGraph

            mediator.close()
            if self._effect_domain is not None:
                try:
                    self._effect_domain.close(lease)
                except Exception as exc:  # noqa: BLE001 - it expires with its authority
                    governance_event(
                        "dispatch.effect_domain_close_failed", level=logging.WARNING,
                        tenant_id=lease.tenant_id, tool_name=tool_name,
                        proposal_id=lease.proposal_id, error_type=type(exc).__name__)
            graph = ResolvedEffectGraph.from_mediator(
                mediator, root_effect_digest=lease.resolved_effect_hash or None)
            return graph.summary(), graph

        try:
            res = fn(arguments, mediator) if mediator is not None else fn(arguments)
            nested_effects, effect_graph = _nested()
            self._record_outcome(lease, tool_name, recorder_seq, "executed")
            governance_event(
                "dispatch.executed",
                tenant_id=tenant_id, tool_name=tool_name,
                proposal_id=proposal_id, grant_jti=lease.grant_jti,
                tool_args_hash=lease.tool_args_hash,
            )
            return DispatchResult(
                executed=True, result=res, proposal_id=proposal_id,
                dispatch_began=True, recorder_seq=recorder_seq,
                nested_effects=nested_effects, effect_graph=effect_graph,
                execution_context_hash=lease.execution_context_hash,
                execution_id=lease.grant_jti, dispatch_check=check,
            )
        except Exception as e:
            # Burn is recorded with its reason so failure() can surface it;
            # the nonce stays consumed — state at the tool is unknown.
            if hasattr(self._ledger, "fail_consume"):
                self._ledger.fail_consume(lease.nonce, str(e))
            self._record_outcome(lease, tool_name, recorder_seq, "state_unknown")
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
            unknown = ToolExecutionStateUnknown(
                f"Tool execution failed, nonce burned and state unknown/failed: {e}",
                proposal_id=proposal_id,
                tenant_id=tenant_id,
                tool_name=tool_name,
            )
            unknown.nested_effects, unknown.effect_graph = _nested()
            unknown.execution_context_hash = lease.execution_context_hash
            unknown.execution_id = lease.grant_jti
            unknown.dispatch_check = check
            raise unknown from e
