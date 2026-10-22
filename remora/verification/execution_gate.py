# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""WS1 at the canonical execution path (WS1 SDD §7.1, §13.2 WP5, §13.3).

The execution core (CORE) never imports this module. It sees a
``Ws1GatePort`` (``remora/execution/ports.py``); ``servers/execution_api.py``
builds the gate from the deployment's configuration and passes it in.

Modes, chosen by the deployment and never by a request:

* ``off`` (default): no gate is built; every decision is as before.
* ``shadow``: the gate runs and its record is audited; the decision, the
  token and the review item are exactly what they would be without it.
* ``enforce``: the WS1 composition caps the decision, its binding enters the
  ACCEPT token's authorization context, and every dispatch path runs the
  gate again with fresh lookups before anything is consumed. Refused at
  construction unless flow control is on and the deployment names evidence
  for every prerequisite work package (``ENFORCE_DEPENDENCIES``).

One review route exists. When the only WS1 caps are REVIEW preconditions
that name one role, ``enforce`` returns ESCALATE and records that role. At
execution the approval the queue stored (approver and authenticated role)
reaches the re-gate as a :class:`~remora.verification.check.ReviewAttestation`
and closes those preconditions only if the role matches exactly. Every other
WS1 cap under ``enforce`` is an ABSTAIN: there is no grant route (IFC-08 is not
started), and an approval never stands in for a MACHINE precondition.

The monitor sees the :class:`ProposalContext` and the checked precondition
states: hashes, IDs and states, never argument values or tool output. A
resolver sends the precondition's subject to its registered source only.
"""
from __future__ import annotations

import dataclasses
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from remora.decision_providers.composition_adapter import (
    AssessmentOutcome,
    MonitorMode,
    MonitorProfile,
    assess_monitor_response,
)
from remora.policy.observation import canonical_tool_call_hash
from remora.policy.report import DecisionAction, DecisionReason, DecisionReport
from remora.verification.check import CheckedPreconditions, ReviewAttestation, Verifier
from remora.verification.compose import compose_authorized_decision
from remora.verification.planner import (
    RESERVED,
    Reserve,
    TaskCallLedger,
    FamilyLedger,
    LookupEstimate,
    PlannerMode,
    VerificationBudget,
    run_verification,
)
from remora.verification.preconditions import (
    INTENT_SUBJECT,
    LogicalState,
    ProposalContext,
    RequirementSet,
    derive_preconditions,
    tagged_digest,
)
from remora.verification.records import CompositionRecord
from remora.verification.registry import PredicateSpec, PreconditionRegistry
from remora.verification.resolvers import Resolver

__all__ = ["ENFORCE_DEPENDENCIES", "WS1_MODES", "Ws1Deployment", "Ws1Gate", "Ws1Outcome"]

WS1_MODES = ("off", "shadow", "enforce")
#: Work packages WS1 SDD §13.2 names before H-EDV reads sensitive data in
#: production: source provenance, result labelling, egress, read capabilities
#: and dispatch control. ``enforce`` needs evidence named for each.
ENFORCE_DEPENDENCIES = ("IFC-04b", "IFC-06", "IFC-11", "IFC-12", "IFC-13")
#: The deployment-declared absence of flow state, bound like any digest.
FLOW_ABSENT = tagged_digest("flow-absent", {"flow_control": "off"})
_RUNTIME_MODES = (PlannerMode.H0, PlannerMode.H_DET, PlannerMode.H_COST, PlannerMode.H_AR,
                  PlannerMode.H_EDV)
_COST_MODES = (PlannerMode.H_COST, PlannerMode.H_AR)
#: The engine's grounding signals a PROVED precondition can establish
#: (``_GROUNDING_SIGNALS`` in remora/policy/decision_engine.py).
GROUNDING_FIELDS = ("tool_matches_goal", "expected_effect_matches",
                    "argument_values_supported", "argument_values_grounded")
_ARGUMENT_FIELDS = ("argument_values_supported", "argument_values_grounded")
_HINT_MODES = (PlannerMode.H_EDV, PlannerMode.H_AR)
_HEX = frozenset("0123456789abcdef")


def _aligned(specs: Sequence[PredicateSpec], requirements: RequirementSet
             ) -> list[tuple[Any, PredicateSpec]] | None:
    """The call's preconditions paired with the specs they were compiled from,
    or None when they do not line up one to one."""
    pres = requirements.preconditions
    if not requirements.authorizable or len(pres) != len(specs) or any(
            p.predicate_id != s.predicate_id for p, s in zip(pres, specs, strict=True)):
        return None
    return list(zip(pres, specs, strict=True))


def _arguments_proved(pairs: list[tuple[Any, PredicateSpec]], checked: CheckedPreconditions,
                      arguments: Mapping[str, Any]) -> bool:
    """Every argument is the subject of a required PROVED precondition."""
    subjects = {s.subject_argument for p, s in pairs
                if p.required and checked.state(p.precondition_id) is LogicalState.PROVED}
    return set(arguments) <= subjects - {None, INTENT_SUBJECT}


def grounding_facts(grounding: Mapping[str, Sequence[str]], specs: Sequence[PredicateSpec],
                    requirements: RequirementSet, checked: CheckedPreconditions,
                    arguments: Mapping[str, Any]) -> dict[str, bool]:
    """The engine grounding signals this call's PROVED preconditions establish.

    A signal holds when at least one precondition's predicate declares it in
    the deployment's *grounding* map and every precondition that declares it
    is required and PROVED. The two argument signals also need every argument
    to be a PROVED subject, so a free-text argument is never called grounded.
    Only signals that hold are returned, and only as ``True``: unknown stays
    unknown. Anything that does not line up with the registry grounds nothing.
    """
    pairs = _aligned(specs, requirements)
    if pairs is None:
        return {}
    facts: dict[str, bool] = {}
    for name in GROUNDING_FIELDS:
        declaring = [p for p, s in pairs if name in grounding.get(s.predicate_id, ())]
        if not declaring or not all(p.required and checked.state(p.precondition_id)
                                    is LogicalState.PROVED for p in declaring):
            continue
        if name in _ARGUMENT_FIELDS and not _arguments_proved(pairs, checked, arguments):
            continue
        facts[name] = True
    return facts


def settled_uncertainty(specs: Sequence[PredicateSpec], requirements: RequirementSet,
                        checked: CheckedPreconditions,
                        arguments: Mapping[str, Any]) -> frozenset[str]:
    """The monitor uncertainty codes this call's PROVED evidence settles.

    ``missing_context`` and ``ambiguous_intent`` are settled by a PROVED
    precondition on the server-resolved intent authority. ``ambiguous_target``
    and ``unverified_value`` are settled only when every argument is the
    subject of a PROVED precondition; an argument no precondition is about
    (free text, a payload) leaves them open. Anything that does not line up
    with the registry settles nothing.
    """
    pairs = _aligned(specs, requirements)
    if pairs is None:
        return frozenset()
    settled: set[str] = set()
    if any(s.subject_argument == INTENT_SUBJECT and p.required
           and checked.state(p.precondition_id) is LogicalState.PROVED for p, s in pairs):
        settled |= {"missing_context", "ambiguous_intent"}
    if _arguments_proved(pairs, checked, arguments):
        settled |= {"ambiguous_target", "unverified_value"}
    return frozenset(settled)


def _as_digest(name: str, value: str) -> str:
    """A bound value as a 64-hex digest: itself when it is one (``sha256:``
    prefix dropped), otherwise a tagged digest of the exact string. The same
    value gives the same digest at assessment and at every re-gate."""
    bare = value.removeprefix("sha256:")
    if len(bare) == 64 and set(bare) <= _HEX:
        return bare
    return tagged_digest("bound-value", {"field": name, "value": value})


@dataclass(frozen=True)
class Ws1Deployment:
    """Everything the gate runs with. Built by the deployment, not the request."""

    registry: PreconditionRegistry
    verifiers: Mapping[str, Verifier]
    resolvers: Mapping[str, Resolver]
    monitor_profile: MonitorProfile
    resolve_capabilities: Callable[[str, str], frozenset[str]]
    clock_ms: Callable[[], int]
    monitor: Callable[[ProposalContext, CheckedPreconditions], bytes | None] | None = None
    planner_mode: PlannerMode = PlannerMode.H_DET
    budget: VerificationBudget = field(default_factory=VerificationBudget)
    family_ledger: FamilyLedger | None = None
    enforce_dependencies: Mapping[str, str] = field(default_factory=dict)
    #: Durable task budget (SQLite, single host). When set, every resolver
    #: lookup and every monitor call is reserved against the call's task before
    #: it runs, across assessment, every re-gate, retries and restarts; a call
    #: that names no task is refused. ``task_call_cap`` is units per task.
    task_ledger: TaskCallLedger | None = None
    task_call_cap: int = 30
    #: H_COST and H_AR (SDD v2 AR-025, AR-026): estimated cost and settlement
    #: per (predicate_id, resolver_id), owned by the deployment, and the cost
    #: units one evaluation may spend. Keyed by predicate rather than
    #: precondition, because a precondition ID carries a per-call binding.
    #: Cost here is estimated, not metered.
    estimates: Mapping[tuple[str, str], LookupEstimate] | None = None
    cost_budget_units: int | None = None
    #: Grounding from proofs (opt-in): predicate_id to the engine grounding
    #: signals its PROVED state establishes (``grounding_facts``). With it, an
    #: assessment re-runs the engine on the observation plus those signals,
    #: and the WS1 caps then apply to that decision. The engine decides; WS1
    #: only supplies facts read from the systems of record.
    grounding: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.planner_mode not in _RUNTIME_MODES:
            raise ValueError(f"planner mode {self.planner_mode.value!r} is a research control, "
                             "not a runtime mode")
        if self.planner_mode in _COST_MODES:
            if self.estimates is None or self.cost_budget_units is None:
                raise ValueError(f"{self.planner_mode.name} requires deployment estimates "
                                 "and a cost budget")
            if type(self.cost_budget_units) is not int or self.cost_budget_units < 0:
                raise ValueError("invalid cost budget")
            declared = {(spec.predicate_id, rid) for specs in self.registry.tools.values()
                        for spec in specs for rid in spec.resolver_ids}
            if not declared <= set(self.estimates):
                raise ValueError("missing deployment estimate")
        predicates = {s.predicate_id for specs in self.registry.tools.values() for s in specs}
        for predicate, signals in self.grounding.items():
            if predicate not in predicates or not signals \
                    or set(signals) - set(GROUNDING_FIELDS):
                raise ValueError(f"invalid grounding for {predicate!r}")

    def call_estimates(self, requirements: RequirementSet
                       ) -> dict[tuple[str, str], LookupEstimate] | None:
        """The deployment's estimates keyed by this call's precondition IDs."""
        if self.estimates is None or self.planner_mode not in _COST_MODES:
            return None
        return {(p.precondition_id, rid): self.estimates[(p.predicate_id, rid)]
                for p in requirements.preconditions for rid in p.resolver_ids
                if (p.predicate_id, rid) in self.estimates}

    @property
    def binding_terms(self) -> dict[str, Any]:
        return {"profile_hash": self.monitor_profile.profile_hash,
                "registry_hash": self.registry.registry_hash,
                "planner_mode": self.planner_mode.value,
                **({"cost_budget_units": self.cost_budget_units,
                    "estimates": sorted([*key, e.cost_units, e.settle_ppm, e.refute_ppm]
                                        for key, e in (self.estimates or {}).items())}
                   if self.planner_mode in _COST_MODES else {}),
                **({"grounding": {k: sorted(v) for k, v in sorted(self.grounding.items())}}
                   if self.grounding else {}),
                "budget": {k: v for k, v in dataclasses.asdict(self.budget).items()
                           if k.startswith(("max_", "requests_", "wall_", "resolver_"))}}


@dataclass(frozen=True)
class Ws1Outcome:
    mode: str
    final_action: DecisionAction
    status: str
    binding_hash: str = ""
    record: CompositionRecord | None = None
    stop_reason: str = ""
    #: The one role whose approval would close every remaining WS1 cap, or "".
    review_role: str = ""
    #: Grounding from proofs: the signals PROVED evidence established, and the
    #: engine's decision on the observation with them. None without grounding.
    grounding: tuple[str, ...] = ()
    grounded_report: DecisionReport | None = None
    #: Lookups this evaluation issued, by resolver, and the cost units charged
    #: for them under the deployment's estimates (None without estimates).
    #: The units are declared, not metered; recording both lets a deployment
    #: reconcile its estimates with what its sources bill.
    lookups: Mapping[str, int] = field(default_factory=dict)
    cost_units_charged: int | None = None
    #: WS1-M4 admission: the authority subject each precondition's evidence
    #: depends on (``source:<source_id>``), and the required preconditions,
    #: so the dispatch path can build receipts (remora/verification/receipts.py).
    #: A precondition whose resolvers span several sources has no subject,
    #: and admission refuses it rather than pick one.
    subjects: Mapping[str, str] = field(default_factory=dict)
    required_preconditions: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        """No WS1 cap: every required precondition PROVED, no monitor cap."""
        return self.record is not None and all(c.source == "engine" for c in self.record.all_caps)

    @property
    def monitor_veto(self) -> bool:
        return self.record is not None and self.record.monitor_veto

    def audit_block(self) -> dict[str, Any]:
        block: dict[str, Any] = {"mode": self.mode, "status": self.status,
                                 "final_action": self.final_action.value,
                                 "binding_hash": self.binding_hash,
                                 "stop_reason": self.stop_reason,
                                 "monitor_veto": self.monitor_veto,
                                 "review_role": self.review_role,
                                 "lookups": dict(sorted(self.lookups.items())),
                                 "cost_units_charged": self.cost_units_charged}
        if self.grounded_report is not None:
            block["grounding"] = list(self.grounding)
            block["grounded_action"] = self.grounded_report.action.value
        if self.record is not None:
            block["record"] = {**self.record.body(), "record_hash": self.record.record_hash}
        return block

    def apply(self, report: DecisionReport) -> DecisionReport:
        """The decision under this mode. Shadow returns *report* unchanged;
        enforce returns it, ESCALATE on the WS1 review route, or ABSTAIN."""
        if self.mode != "enforce" or (self.clean and self.status == "evaluated"):
            return report
        if self.review_role and report.action is not DecisionAction.ABSTAIN:
            return dataclasses.replace(report, action=DecisionAction.ESCALATE,
                                       reasons=(*report.reasons, DecisionReason.PRECONDITION_CAP),
                                       human_review_required=True)
        monitor_only = self.record is not None and all(
            c.source in ("engine", "monitor") for c in self.record.all_caps)
        reason = DecisionReason.MONITOR_CAP if monitor_only else DecisionReason.PRECONDITION_CAP
        return dataclasses.replace(report, action=DecisionAction.ABSTAIN,
                                   reasons=(*report.reasons, reason),
                                   human_review_required=False)


def _sources(registry: PreconditionRegistry, resolver_ids: Sequence[str]) -> set[str]:
    return {registry.resolvers[r].source_id for r in resolver_ids if r in registry.resolvers}


def _subjects(requirements: RequirementSet, registry: PreconditionRegistry) -> dict[str, str]:
    """``precondition_id -> subject`` for admission's epoch checks.

    ``source:<id>`` for a precondition read from one source, and
    ``review:<role>`` for a REVIEW precondition, which an approval of that
    role closes: revoking the role's authority advances that epoch.
    """
    out: dict[str, str] = {}
    for pre in requirements.preconditions:
        sources = _sources(registry, pre.resolver_ids)
        if len(sources) == 1:
            out[pre.precondition_id] = f"source:{sources.pop()}"
        elif not sources and pre.review_role:
            out[pre.precondition_id] = f"review:{pre.review_role}"
    return out


def _review_route(record: CompositionRecord, requirements: Any) -> str:
    """The role when every WS1 cap is a REVIEW precondition of that one role."""
    ws1_caps = [c for c in record.all_caps if c.source != "engine"]
    if not ws1_caps or any(c.code != "review_required" for c in ws1_caps):
        return ""
    roles = set()
    for cap in ws1_caps:
        pre = requirements.by_id(cap.source.removeprefix("precondition:"))
        roles.add(pre.review_role if pre is not None else None)
    if len(roles) != 1:
        return ""
    role = roles.pop()
    return role if isinstance(role, str) and role else ""


def _task_reservation(ledger: TaskCallLedger, cap: int, *, tenant: str, principal: str,
                      task_id: str, context: ProposalContext) -> Reserve | None:
    """The reserve hook for one evaluation, or None on a binding mismatch.

    The budget belongs to (tenant, task). Its binding adds the principal and
    the intent authority, so a different authority cannot draw on it. Each
    evaluation is one attempt with its own operation keys: a re-gate or a
    retry is new external activity and is charged again; nothing refunds or
    resets the task's spend. Within an attempt a key reserved twice is a
    duplicate and does not run twice.
    """
    ledger_task = tagged_digest("ledger-task", {"tenant": tenant, "task": task_id})
    binding = tagged_digest("ledger-binding", {
        "tenant": tenant, "task": task_id, "principal": principal,
        "intent_authority_hash": context.intent_authority_hash})
    try:
        ledger.ensure(ledger_task, binding, cap)
    except ValueError:
        return None
    attempt = secrets.token_hex(16)
    request_hash = tagged_digest("ledger-request", {"call_hash": context.call_hash,
                                                    "tool": context.tool_name})

    def reserve(kind: str, key: str) -> str:
        operation = tagged_digest("ledger-operation", {
            "attempt": attempt, "context_hash": context.context_hash, "kind": kind,
            "key": key})
        return ledger.reserve_status(ledger_task, binding, operation, request_hash)

    return reserve


class Ws1Gate:
    """Builds the context, runs the bounded loop and composes; never raises."""

    def __init__(self, mode: str, deployment: Ws1Deployment, *, flow_control: bool) -> None:
        if mode not in WS1_MODES or mode == "off":
            raise ValueError(f"WS1 mode must be 'shadow' or 'enforce' to build a gate, not {mode!r}")
        if mode == "enforce":
            if not flow_control:
                raise ValueError("WS1 enforce needs REMORA_FLOW_CONTROL=1")
            missing = [d for d in ENFORCE_DEPENDENCIES
                       if not str(deployment.enforce_dependencies.get(d, "")).strip()]
            if missing:
                raise ValueError(f"WS1 enforce needs evidence for {missing} (WS1 SDD §13.2 WP5)")
        self.mode = mode
        self.deployment = deployment

    def subjects_for_tool(self, tool_name: str) -> frozenset[str]:
        """Every authority subject a call of ``tool_name`` can read evidence from.

        Admission reads their epochs before the re-gate's lookups, so a
        receipt records the epoch its evidence was read under.
        """
        registry = self.deployment.registry
        specs = registry.tools.get(tool_name, ())
        return frozenset(
            {f"source:{s}" for spec in specs for s in _sources(registry, spec.resolver_ids)}
            | {f"review:{spec.review_role.strip().lower()}" for spec in specs
               if spec.review_role and not spec.resolver_ids})

    def _capability_hash(self, capability: Mapping[str, Any] | None) -> str:
        if capability is None:
            return tagged_digest("capability-none", {})
        return tagged_digest("capability", {
            "allowed": bool(capability.get("allowed")),
            "policy_version": str(capability.get("policy_version") or ""),
            "task_type": str(capability.get("task_type") or ""),
            "allowed_tools": sorted(str(t) for t in capability.get("allowed_tools") or ())})

    def evaluate(self, *, proposal_id: str, tenant: str, principal: str, tool_name: str,
                 arguments: Mapping[str, Any], intent_authority_hash: str,
                 policy_bundle_hash: str, toolspec_hash: str,
                 capability: Mapping[str, Any] | None, flow_digest: str | None,
                 flow_epoch: int | None, attempt_family_id: str | None,
                 base: DecisionReport, veto_on_record: bool = False,
                 review_attestation: tuple[str, str] | None = None,
                 task_id: str | None = None,
                 redecide: Callable[[Mapping[str, bool]], DecisionReport] | None = None,
                 ) -> Ws1Outcome:
        """*review_attestation* is ``(approver, approver_role)`` from the stored
        approval, passed on the review path's re-gate only. *task_id* is the
        server-bound task identity the call is made under (``context_id/task_id``).
        *redecide* re-runs the caller's decision on its observation plus the
        given grounding signals; it is used only when the deployment declares
        ``grounding`` (assessment, never a re-gate)."""
        try:
            review = (ReviewAttestation(proposal_id, *review_attestation)
                      if review_attestation is not None else None)
            return self._evaluate(proposal_id, tenant, principal, tool_name, arguments,
                                  intent_authority_hash, policy_bundle_hash, toolspec_hash,
                                  capability, flow_digest, flow_epoch, attempt_family_id,
                                  base, veto_on_record, review, task_id, redecide)
        except Exception as exc:  # a gate fault refuses; its text never reaches the record
            return Ws1Outcome(self.mode, DecisionAction.ABSTAIN, f"error:{type(exc).__name__}")

    def _evaluate(self, proposal_id: str, tenant: str, principal: str, tool_name: str,
                  arguments: Mapping[str, Any], intent_authority_hash: str,
                  policy_bundle_hash: str, toolspec_hash: str,
                  capability: Mapping[str, Any] | None, flow_digest: str | None,
                  flow_epoch: int | None, attempt_family_id: str | None,
                  base: DecisionReport, veto_on_record: bool,
                  review: ReviewAttestation | None, task_id: str | None,
                  redecide: Callable[[Mapping[str, bool]], DecisionReport] | None = None,
                  ) -> Ws1Outcome:
        d = self.deployment
        for name, value in (("intent_authority", intent_authority_hash),
                            ("policy_bundle", policy_bundle_hash), ("toolspec", toolspec_hash)):
            if not value:
                return Ws1Outcome(self.mode, DecisionAction.ABSTAIN, f"refused:{name}_unbound")
        args = dict(arguments)
        context = ProposalContext(
            proposal_id=proposal_id, tenant_id=tenant, principal_id=principal,
            tool_name=tool_name,
            call_hash=canonical_tool_call_hash(name=tool_name, arguments=args, tenant=tenant),
            intent_authority_hash=_as_digest("intent_authority_hash", intent_authority_hash),
            policy_bundle_hash=_as_digest("policy_bundle_hash", policy_bundle_hash),
            toolspec_hash=_as_digest("toolspec_hash", toolspec_hash),
            profile_hash=d.monitor_profile.profile_hash,
            capability_hash=self._capability_hash(capability),
            flow_digest=_as_digest("flow_digest", flow_digest) if flow_digest else FLOW_ABSENT,
            flow_epoch=int(flow_epoch or 0), context_version=1)
        if d.family_ledger is not None and attempt_family_id \
                and not d.family_ledger.admit(attempt_family_id, context):
            return Ws1Outcome(self.mode, DecisionAction.ABSTAIN,
                              "refused:attempt_family_budget_exhausted")
        reserve = None
        if d.task_ledger is not None:
            if not task_id:
                return Ws1Outcome(self.mode, DecisionAction.ABSTAIN,
                                  "refused:task_identity_required")
            reserve = _task_reservation(d.task_ledger, d.task_call_cap, tenant=tenant,
                                        principal=principal, task_id=task_id, context=context)
            if reserve is None:
                return Ws1Outcome(self.mode, DecisionAction.ABSTAIN,
                                  "refused:task_binding_mismatch")
        requirements = derive_preconditions(context, args, d.registry)
        monitor_calls = 0
        monitor_veto = veto_on_record

        def ask(checked: CheckedPreconditions) -> tuple[bytes | None, str | None]:
            nonlocal monitor_calls
            if d.monitor is None:
                return None, "no_monitor"
            if monitor_calls >= d.budget.max_monitor_calls:
                return None, "monitor_budget_exhausted"
            if reserve is not None and reserve("monitor", str(monitor_calls)) != RESERVED:
                return None, "task_budget_exhausted"
            monitor_calls += 1
            try:
                return d.monitor(context, checked), None
            except Exception as exc:  # an outage, never a low-risk reading
                return None, f"provider_error:{type(exc).__name__}"

        def assess(checked: CheckedPreconditions) -> Any:
            nonlocal monitor_veto
            raw, error = ask(checked)
            if raw is None and error == "no_monitor":
                return None
            assessment = assess_monitor_response(
                raw, profile=d.monitor_profile, context_hash=context.context_hash,
                evidence_digest=checked.evidence_digest, input_digest=checked.evidence_digest,
                now_s=d.clock_ms() // 1000, error=error)
            if d.monitor_profile.mode is not MonitorMode.SHADOW \
                    and assessment.outcome is AssessmentOutcome.ASSESSED and assessment.crossed:
                monitor_veto = True
            return assessment

        def hints(checked: CheckedPreconditions) -> tuple[str, ...]:
            # The last monitor call is kept for the final assessment. A hint
            # request that spent it turned a required monitor's final answer
            # into monitor_budget_exhausted, an outage that refuses the call.
            if d.monitor is None or monitor_calls >= d.budget.max_monitor_calls - 1:
                return ()
            a = assess(checked)
            return a.hint_precondition_ids if a is not None else ()

        run = run_verification(
            context, requirements, registry=d.registry, verifiers=d.verifiers,
            resolvers=d.resolvers, held_capabilities=d.resolve_capabilities(tenant, principal),
            mode=d.planner_mode, budget=d.budget, clock_ms=d.clock_ms,
            hints_for=hints if d.planner_mode in _HINT_MODES else None, review=review,
            estimates=d.call_estimates(requirements),
            cost_budget_units=d.cost_budget_units if d.planner_mode in _COST_MODES else None,
            # Monitor calls are reserved in ask(); the loop reserves lookups.
            reserve=None if reserve is None else (
                lambda kind, key: RESERVED if kind == "monitor" else reserve(kind, key)))
        issued = list(run.issued.values())
        lookups: dict[str, int] = {}
        for request in issued:
            lookups[request.resolver_id] = lookups.get(request.resolver_id, 0) + 1
        call_estimates = d.call_estimates(requirements)
        charged = (sum(call_estimates[(r.precondition_id, r.resolver_id)].cost_units
                       for r in issued if (r.precondition_id, r.resolver_id) in call_estimates)
                   if call_estimates is not None else None)
        specs = d.registry.tools.get(tool_name, ())
        facts = (grounding_facts(d.grounding, specs, requirements, run.checked, args)
                 if redecide is not None and d.grounding else {})
        grounded = redecide(facts) if facts and redecide is not None else None
        record = compose_authorized_decision(
            grounded or base, context, requirements, run.checked, assess(run.checked),
            d.monitor_profile,
            now_s=d.clock_ms() // 1000, budget_exhausted=run.budget_exhausted,
            monitor_veto_on_record=monitor_veto,
            uncertainty_settled=settled_uncertainty(specs, requirements, run.checked, args))
        outcome = Ws1Outcome(self.mode, DecisionAction(record.final_action), "evaluated",
                             record=record, stop_reason=run.stop_reason,
                             review_role=_review_route(record, requirements),
                             grounding=tuple(sorted(facts)), grounded_report=grounded,
                             lookups=lookups, cost_units_charged=charged,
                             subjects=_subjects(requirements, d.registry),
                             required_preconditions=tuple(sorted(
                                 p.precondition_id for p in requirements.preconditions
                                 if p.required)))
        if outcome.clean or outcome.review_role:
            binding = tagged_digest("execution-binding", {
                "context_hash": context.context_hash,
                "requirements_hash": requirements.requirements_hash, **d.binding_terms})
            outcome = dataclasses.replace(outcome, binding_hash=binding)
        return outcome
