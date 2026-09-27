# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Process-local REMORA tool runtime with separately recorded surface evidence.

All execution still requires the existing signed ExecutionLease. Shadow mode
only observes; the explicit experimental enforce mode adds refusal checks.
This process boundary cannot attest credentials or tools in another process.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Callable, Mapping

from remora.enforcement.lease import (
    DispatchResult, ExecutionLease, GovernedToolDispatcher, ToolExecutionStateUnknown,
)
from remora.governance.effect_verification import PostconditionContract
from remora.governance.tenant_chain import TenantAuditChain
from remora.toolcall.surface_authority import AuthorityReport, analyze_authority
from remora.toolcall.surface_effect_evidence import build_effect_evidence, recheck_effect_evidence
from remora.policy.observation import canonical_tool_call_hash
from remora.toolcall.runtime_surface import (
    RuntimeTool, RuntimeToolSurface, SurfaceContinuity, SurfaceReport,
    SurfaceVerdict, canonical_json, compare_surfaces, evaluate_surface,
)


@dataclass(frozen=True)
class SurfaceAssessment:
    assessment_id: str
    surface: RuntimeToolSurface
    report: SurfaceReport
    action_hash: str
    principal: str
    expires_at: float


@dataclass(frozen=True)
class SurfaceExecution:
    execution: DispatchResult
    surface: SurfaceReport
    continuity: SurfaceContinuity
    runtime_outcome: str
    effect_verdict: str = "NOT_ESTABLISHED"
    authority: AuthorityReport | None = None


class SurfaceRuntime:
    """Own offered tool metadata and route every call through a dispatcher.

    The opaque assessment handle is local, action-bound and one-use. It never
    replaces the signed lease. Changes made via this runtime are serialized
    through dispatch. Direct mutation of the executor by host code remains
    outside this runtime's lock and is not a process-compromise guarantee.
    """

    def __init__(self, dispatcher: GovernedToolDispatcher,
                 governed_tools: Mapping[str, str], *, mode: str = "shadow",
                 clock: Callable[[], float] = time.monotonic,
                 assessment_ttl: float = 60.0,
                 governed_authority: Mapping[str, RuntimeTool] | None = None,
                 inventory_complete: bool = False,
                 trusted_verifiers: Mapping[str, str] | None = None) -> None:
        if mode not in {"shadow", "enforce"} or assessment_ttl <= 0:
            raise ValueError("invalid mode or assessment_ttl")
        self.dispatcher = dispatcher
        self.mode = mode
        self._clock = clock
        self._ttl = assessment_ttl
        self._pid = os.getpid()
        self._identity = f"remora:{self._pid}:{uuid.uuid4()}"
        self._governed = dict(governed_tools)
        self._metadata: dict[str, RuntimeTool] = {}
        self._pending: dict[str, SurfaceAssessment] = {}
        self._lock = RLock()
        self._authority = dict(governed_authority or {})
        self._inventory_complete = inventory_complete
        self._trusted_verifiers = dict(trusted_verifiers or {})
        self._contracts: dict[str, dict[str, Any]] = {}
        self._executions: dict[tuple[str, str], dict[str, Any]] = {}
        self._effects: dict[tuple[str, str], dict[str, Any]] = {}
        self._chain = TenantAuditChain()

    def register(self, tool: RuntimeTool, fn: Callable[[Any], Any]) -> None:
        with self._lock, self.dispatcher.registry_guard():
            self.dispatcher.register(tool.tool_id, fn)
            self._metadata[tool.tool_id] = tool

    def snapshot(self) -> RuntimeToolSurface:
        with self._lock, self.dispatcher.registry_guard():
            if os.getpid() != self._pid:
                raise ValueError("runtime_process_changed")
            registered = set(self.dispatcher.registered_tool_names())
            versions = self.dispatcher.registration_versions()
            tools = []
            for name in sorted(registered | self._metadata.keys()):
                declared = self._metadata.get(name, RuntimeTool(
                    name, "runtime-only", None, None, None))
                tools.append(replace(declared, registration_generation=versions.get(name),
                                     registered=name in registered,
                                     callable_at_dispatch=name in registered,
                                     offered_to_agent=(name in registered and
                                                       declared.offered_to_agent is True)))
            return RuntimeToolSurface(self._identity, "agent-runtime", True,
                                      tuple(tools), datetime.now(UTC).isoformat())

    def offered_tools(self) -> list[dict[str, Any]]:
        return [{"name": t.tool_id, "inputSchema": json.loads(t.argument_schema_json)}
                for t in self.snapshot().tools if t.offered_to_agent]

    def assess(self, tool_name: str, arguments: Any, *, tenant: str,
               principal: str, target: str,
               postcondition: PostconditionContract | None = None) -> SurfaceAssessment:
        with self._lock, self.dispatcher.registry_guard():
            now = self._clock()
            self._pending = {k: v for k, v in self._pending.items() if v.expires_at > now}
            # A contract is needed only while its assessment can still dispatch
            # or after it did; the pending cap must bound both maps.
            executed = {aid for _, aid in self._executions}
            self._contracts = {k: v for k, v in self._contracts.items()
                               if k in self._pending or k in executed}
            if len(self._pending) >= 1000:
                raise ValueError("assessment_capacity_exceeded")
            observed = self.snapshot()
            # Validate JSON before the legacy hash helper can stringify values.
            canonical_json(arguments)
            assessment = SurfaceAssessment(
                str(uuid.uuid4()), observed,
                evaluate_surface(observed, self._governed, expected_runtime_identity=self._identity),
                canonical_tool_call_hash(name=tool_name, arguments=arguments, tenant=tenant, target=target),
                principal, now + self._ttl,
            )
            if postcondition is not None:
                if postcondition.tool_id != tool_name:
                    raise ValueError("postcondition_tool_mismatch")
                self._contracts[assessment.assessment_id] = json.loads(canonical_json(dict(
                    tool_id=postcondition.tool_id, reader=postcondition.reader,
                    target_selector=dict(postcondition.target_selector),
                    expected_fields=dict(postcondition.expected_fields),
                    comparison_rules=dict(postcondition.comparison_rules),
                    observation_deadline_seconds=postcondition.observation_deadline_seconds,
                    repeatable=postcondition.repeatable, evidence_fields=list(postcondition.evidence_fields))))
            self._pending[assessment.assessment_id] = assessment
            self._chain.append(tenant, dict(event="surface_assessment", assessment_id=assessment.assessment_id,
                                           surface=observed.identity(), surface_digest=observed.digest(),
                                           report=asdict(assessment.report), action_hash=assessment.action_hash))
            return assessment

    def dispatch(self, assessment_id: str, lease: ExecutionLease | None,
                 tool_name: str, arguments: Any, *, tenant: str,
                 principal: str, target: str) -> SurfaceExecution:
        with self._lock, self.dispatcher.registry_guard():
            assessment = self._pending.pop(assessment_id, None)
            if assessment is None:
                raise ValueError("assessment_not_found")
            if assessment.expires_at <= self._clock():
                self._contracts.pop(assessment_id, None)
                raise ValueError("assessment_expired")
            # Detach caller-owned mutable arguments before comparing and invoking.
            arguments = json.loads(canonical_json(arguments))
            call_hash = canonical_tool_call_hash(name=tool_name, arguments=arguments,
                                                 tenant=tenant, target=target)
            if assessment.action_hash != call_hash or assessment.principal != principal:
                raise ValueError("assessment_binding_mismatch")
            current = self.snapshot()
            report = evaluate_surface(current, self._governed, expected_runtime_identity=self._identity)
            continuity = compare_surfaces(assessment.surface, current)
            authority = analyze_authority(current, self._authority,
                                          inventory_complete=self._inventory_complete)
            authority_blocked = bool(self._authority) and authority.verdict is not SurfaceVerdict.MATCHED_OBSERVATION
            if self.mode not in {"shadow", "enforce"}:
                raise ValueError("invalid_surface_mode")
            if self.mode == "enforce" and (authority_blocked or any(
                r.verdict is not SurfaceVerdict.MATCHED_OBSERVATION
                for r in (assessment.report, report, continuity)
            )):
                result = DispatchResult(executed=False,
                                        refusal_reason="surface_not_established")
            else:
                try:
                    result = self.dispatcher.dispatch(lease, tool_name, arguments,
                                                      tenant_id=tenant, actor_identity=principal,
                                                      target_environment=target)
                except ToolExecutionStateUnknown:
                    result = DispatchResult(executed=False, dispatch_began=True,
                                            refusal_reason="tool_execution_state_unknown")
            outcome = "SUCCEEDED" if result.executed else "REFUSED"
            if result.dispatch_began and not result.executed:
                outcome = "UNKNOWN"
            entry = self._chain.append(tenant, dict(
                event="execution_result", proposal_id=assessment.assessment_id,
                tool_call_hash=call_hash, grant_jti=lease.nonce if lease else "",
                tool_executed=result.executed, state_unknown=outcome == "UNKNOWN",
                surface=current.identity(), surface_digest=current.digest(),
                surface_report=asdict(report), continuity=asdict(continuity),
                authority=asdict(authority), runtime_outcome=outcome,
                refusal_reason=result.refusal_reason))
            self._executions[(tenant, assessment.assessment_id)] = dict(
                event="execution_result", timestamp=entry.timestamp, payload=dict(entry.payload))
            return SurfaceExecution(result, report, continuity, outcome, authority=authority)

    def record_effect(self, assessment_id: str, *, tenant: str, principal: str,
                      verifier_identity: str, observed: Mapping[str, Any] | None) -> dict[str, Any]:
        """Record a separate authenticated read; never execute the tool again."""
        with self._lock:
            key = (tenant, assessment_id)
            event = self._executions.get(key)
            if event is None:
                raise ValueError("execution_not_found")
            previous = self._effects.get(key)
            if previous and previous["property_verdict"] != "NOT_ESTABLISHED":
                raise ValueError("effect_already_settled")
            raw_contract = self._contracts.get(assessment_id)
            if raw_contract is None:
                raise ValueError("postcondition_not_declared")
            payload = event["payload"]
            evidence = build_effect_evidence(
                contract=PostconditionContract(**raw_contract), observed=observed, events=[event],
                proposal_id=assessment_id, tool_call_hash=payload["tool_call_hash"],
                grant_jti=payload["grant_jti"], verified_at=datetime.now(UTC).isoformat(),
                verifier_identity=verifier_identity, principal=principal,
                trusted_verifiers=self._trusted_verifiers)
            self._chain.append(tenant, dict(event="effect_evidence", evidence=evidence))
            self._effects[key] = evidence
            return json.loads(canonical_json(evidence))

    def recheck_effect(self, assessment_id: str, *, tenant: str) -> dict[str, Any]:
        with self._lock:
            key = (tenant, assessment_id)
            if key not in self._effects:
                raise ValueError("effect_not_found")
            if not self.audit_valid(tenant):
                raise ValueError("audit_integrity_failure")
            evidence = self._effects[key]
            return recheck_effect_evidence(
                evidence, contract=PostconditionContract(**self._contracts[assessment_id]),
                events=[self._executions[key]], principal=evidence["principal"],
                trusted_verifiers=self._trusted_verifiers)

    def audit_valid(self, tenant: str) -> bool:
        return self._chain.verify(tenant)[0]

    def audit_entries(self, tenant: str) -> list[dict[str, Any]]:
        """Export detached evidence for retention outside this process."""
        with self._lock:
            return json.loads(canonical_json([entry.to_dict() for entry in self._chain.entries(tenant)]))
