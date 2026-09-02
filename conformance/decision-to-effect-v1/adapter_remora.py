# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REMORA adapter for the decision-to-effect conformance suite.

Maps REMORA's native refusal reasons onto the suite's normalized outcome
classes. The mapping table is the interesting part of this file and is written
out explicitly rather than by prefix matching, so that a new REMORA refusal
reason fails loudly here instead of being silently classified as something it
is not.

Authority in REMORA is spent at two boundaries, and the suite exercises both:
the PDP grant is consumed by the enforcement gate, and the narrower execution
lease is consumed by the dispatcher at the moment of the call.
"""
from __future__ import annotations

import os
import tempfile
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.lease import (
    ExecutionLease,
    GovernedToolDispatcher,
    ToolExecutionStateUnknown,
)
from remora.enforcement.token import AuthorizationContext, PolicyDecisionToken
from remora.governance.review_queue import (
    ExecutionDecision,
    ReviewQueue,
)
from remora.policy.report import DecisionAction
from remora.policy.observation import PolicyObservation
from remora.governance.effect_verification import (
    PostconditionContract,
    verify_declared_delta,
)
from remora.enforcement.runtime_identity import current_runtime_identity_hash
from remora.policy.observation import canonical_tool_call_hash

#: REMORA refusal reason -> suite outcome class. Anything not listed is a
#: mapping gap and is reported as such rather than guessed at.
REASON_CLASS = {
    "tool_args_mismatch": "CALL_BINDING_MISMATCH",
    "tool_args_hash_mismatch": "CALL_BINDING_MISMATCH",
    "tool_name_mismatch": "CALL_BINDING_MISMATCH",
    "tenant_mismatch": "CALL_BINDING_MISMATCH",
    "target_mismatch": "CALL_BINDING_MISMATCH",
    "observation_mismatch": "CALL_BINDING_MISMATCH",
    "nonce_already_consumed": "AUTHORITY_ALREADY_CONSUMED",
    "token_already_consumed": "AUTHORITY_ALREADY_CONSUMED",
    "expired": "AUTHORITY_EXPIRED",
    "token_expired": "AUTHORITY_EXPIRED",
    "lease_expired": "AUTHORITY_EXPIRED",
    "audience_mismatch": "AUDIENCE_MISMATCH",
    "context_mismatch": "CONTEXT_CHANGED",
    "context_unbound": "CONTEXT_CHANGED",
    "policy_bundle_mismatch": "CONTEXT_CHANGED",
    "toolspec_mismatch": "CONTEXT_CHANGED",
    "toolspec_hash_mismatch": "CONTEXT_CHANGED",
    "toolspec_version_mismatch": "CONTEXT_CHANGED",
    "principal_revoked": "PRINCIPAL_REVOKED",
    "revocation_store_unavailable": "PRINCIPAL_REVOKED",
    "runtime_identity_mismatch": "RUNTIME_NOT_AUTHORIZED",
    "runtime_identity_undeclared": "RUNTIME_NOT_AUTHORIZED",
}

BUNDLE_A = "bundle-hash-a"
BUNDLE_B = "bundle-hash-b"
SPEC_A = ("toolspec-hash-a", 1)
SPEC_B = ("toolspec-hash-b", 2)
PRINCIPAL = "svc-payments"


def _classify(reason: str) -> str:
    return REASON_CLASS.get(reason, f"UNMAPPED:{reason}")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RemoraAdapter:
    """REMORA under the suite's contract."""

    name = "remora"

    def __init__(self) -> None:
        os.environ.setdefault("REMORA_PDP_SIGNING_KEY", "conformance-suite-key")
        from remora import __version__ as remora_version

        self.version = remora_version
        self._tmp = tempfile.mkdtemp(prefix="d2e-conformance-")
        self.reset()

    # -- lifecycle ---------------------------------------------------------

    def reset(self) -> None:
        self._bundle = BUNDLE_A
        self._spec = SPEC_A
        self._revoked: set[str] = set()
        self._runtime_moved = False
        self._executed: list[dict[str, Any]] = []
        self._grants: dict[str, tuple[PolicyDecisionToken, ExecutionLease, dict]] = {}
        self._observations: dict[str, Any] = {}
        self._gate = EnforcementGate(
            strict=True,
            audience="pep-a",
            db_path=os.path.join(self._tmp, f"gate-{uuid.uuid4().hex}.sqlite3"),
        )
        # The review queue owns the revocation re-gate, which is the mechanism
        # V-11 must exercise. Deciding revocation in this adapter would make
        # the vector pass on the adapter's own branch and prove nothing.
        self._queue = ReviewQueue(tenant_id="t-1")
        self._items: dict[str, str] = {}
        self._dispatcher = GovernedToolDispatcher(expected_policy_bundle_hash=BUNDLE_A)
        self._dispatcher.bind_toolspec_identity(lambda _name: self._spec)
        self._dispatcher.register("transfer_funds", self._tool)

    def _tool(self, arguments: Any) -> dict[str, Any]:
        self._executed.append(dict(arguments))
        return {"ok": True, **dict(arguments)}

    # -- steps -------------------------------------------------------------

    def authorize(self, call: dict[str, Any], *, audience: str = "pep-a") -> str:
        call_hash = canonical_tool_call_hash(
            name=call["name"],
            arguments=call["arguments"],
            tenant=call["tenant"],
            target=call["target"],
        )
        context = AuthorizationContext(
            tenant=call["tenant"],
            principal=PRINCIPAL,
            target_environment=call["target"],
            policy_bundle_hash=self._bundle,
            toolspec_hash=self._spec[0],
        )
        issued = _now()
        token = PolicyDecisionToken.issue(
            action="accept",
            observation_hash=call_hash,
            request_id=str(uuid.uuid4()),
            issued_at=issued,
            audience=audience,
            context=context,
        )
        lease = ExecutionLease.issue(
            decision="accept",
            tenant_id=call["tenant"],
            actor_identity=PRINCIPAL,
            tool_name=call["name"],
            arguments=call["arguments"],
            target_environment=call["target"],
            policy_bundle_hash=self._bundle,
            issued_at=issued,
            toolspec_hash=self._spec[0],
            toolspec_version=self._spec[1],
            proposal_id=str(uuid.uuid4()),
            grant_jti=token.jti,
            runtime_identity_hash=(
                "runtime-not-this-one" if self._runtime_moved
                else current_runtime_identity_hash()
            ),
        )
        handle = str(uuid.uuid4())
        obs = PolicyObservation.from_tool_call(
            name=call["name"], arguments=call["arguments"],
            target_environment=call["target"], risk_tier="critical",
        )
        item = self._queue.enqueue(obs, DecisionAction.ESCALATE)
        self._queue.approve(item.item_id, PRINCIPAL, timedelta(minutes=5))
        self._items[handle] = item.item_id
        self._observations[handle] = obs
        self._grants[handle] = (token, lease, {"call": call, "hash": call_hash,
                                               "context": context})
        return handle

    def redeem_grant(self, handle: str, *, audience: str = "pep-a") -> str:
        token, _lease, meta = self._grants[handle]
        # The re-gate before the PEP: REMORA decides whether the approval
        # still holds, this adapter only reports what it decided.
        try:
            outcome = self._queue.execute(
                self._items[handle], self._observations[handle]
            )
        except ValueError as exc:
            # The queue refuses to re-authorize an item it already authorized.
            # This is the third single-use boundary the suite touches, and it
            # is reported as a spent authority rather than as a crash.
            if "not approved" in str(exc):
                return "AUTHORITY_ALREADY_CONSUMED"
            raise
        if outcome.decision is ExecutionDecision.APPROVAL_INVALIDATED:
            return "PRINCIPAL_REVOKED"
        gate = self._gate if audience == "pep-a" else EnforcementGate(
            strict=True, audience=audience,
            db_path=os.path.join(self._tmp, f"gate-{uuid.uuid4().hex}.sqlite3"),
        )
        result = gate.check(
            token, meta["hash"], consume=True, context=meta["context"]
        )
        return "EXECUTED" if result.allowed else _classify(result.reason)

    def dispatch(
        self, handle: str, call: dict[str, Any], *, now: str | None = None
    ) -> str:
        _token, lease, meta = self._grants[handle]
        if self._runtime_moved:
            # The authority was issued for a different executor. Re-issued
            # rather than field-edited, because editing a signed object tests
            # the signature and not the runtime binding.
            lease = ExecutionLease.issue(
                decision="accept",
                tenant_id=meta["call"]["tenant"],
                actor_identity=PRINCIPAL,
                tool_name=meta["call"]["name"],
                arguments=meta["call"]["arguments"],
                target_environment=meta["call"]["target"],
                policy_bundle_hash=self._bundle,
                issued_at=_now(),
                toolspec_hash=self._spec[0],
                toolspec_version=self._spec[1],
                proposal_id=lease.proposal_id,
                grant_jti=lease.grant_jti,
                runtime_identity_hash="runtime-not-this-one",
            )
        dispatcher = self._dispatcher
        if self._bundle != BUNDLE_A:
            dispatcher = GovernedToolDispatcher(expected_policy_bundle_hash=self._bundle)
            dispatcher.bind_toolspec_identity(lambda _name: self._spec)
            dispatcher.register("transfer_funds", self._tool)
        result = dispatcher.dispatch(
            lease,
            call["name"],
            call["arguments"],
            tenant_id=call["tenant"],
            target_environment=call["target"],
            now=now,
            actor_identity=PRINCIPAL,
        )
        if result.executed:
            return "EXECUTED"
        return _classify(result.refusal_reason or "")

    def dispatch_concurrent(
        self, handle: str, call: dict[str, Any], workers: int
    ) -> str:
        outcomes: list[str] = []
        lock = threading.Lock()
        barrier = threading.Barrier(workers)

        def attempt() -> None:
            barrier.wait()
            outcome = self.dispatch(handle, call)
            with lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=attempt) for _ in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        executed = outcomes.count("EXECUTED")
        if executed == 1 and len(self._executed) == 1:
            return "EXACTLY_ONE_EXECUTED"
        return f"EXECUTED_{executed}_TIMES"

    def dispatch_indeterminate(self, handle: str, call: dict[str, Any]) -> str:
        _token, lease, _meta = self._grants[handle]
        dispatcher = GovernedToolDispatcher(expected_policy_bundle_hash=self._bundle)
        dispatcher.bind_toolspec_identity(lambda _name: self._spec)

        def unknown(arguments: Any) -> Any:
            raise ToolExecutionStateUnknown(
                "the downstream call was sent and no outcome was returned",
                tool_name=call["name"],
            )

        dispatcher.register(call["name"], unknown)
        try:
            dispatcher.dispatch(
                lease,
                call["name"],
                call["arguments"],
                tenant_id=call["tenant"],
                target_environment=call["target"],
                actor_identity=PRINCIPAL,
            )
        except ToolExecutionStateUnknown:
            return "EFFECT_INDETERMINATE"
        return "ASSERTED_AN_OUTCOME"

    def revoke_principal(self) -> None:
        self._queue.revoke_principal(PRINCIPAL, reason="conformance vector V-11")
        self._revoked.add(PRINCIPAL)

    def change_toolspec(self) -> None:
        self._spec = SPEC_B

    def change_policy_bundle(self) -> None:
        self._bundle = BUNDLE_B

    def change_runtime(self) -> None:
        self._runtime_moved = True

    def verify_effect(self, handle: str, observed: dict[str, Any]) -> str:
        _token, lease, meta = self._grants[handle]
        if not self._executed:
            return "EFFECT_UNLINKED"
        contract = PostconditionContract(
            tool_id=lease.tool_name,
            reader="conformance-reader",
            target_selector={"to": meta["call"]["arguments"]["to"]},
            expected_fields=dict(meta["call"]["arguments"]),
        )
        verification = verify_declared_delta(
            contract,
            observed,
            proposal_id=lease.proposal_id,
            execution_id=lease.nonce,
            toolspec_hash=lease.toolspec_hash,
            verifier_identity="conformance-suite",
        )
        return verification.status.value.replace("EFFECT_", "EFFECT_")


def build() -> RemoraAdapter:
    return RemoraAdapter()
