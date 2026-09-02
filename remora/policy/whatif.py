# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Decision-boundary analysis: what would have to change for a call to reach a verdict.

``explain()`` says which rule fired. This module answers the next question a
reviewer, an integrator or an agent developer asks: *what would it take* for
the same call to be ACCEPTed (or, for an ABSTAIN, to at least reach a human
as VERIFY)? It answers by bounded, exhaustive search over a declared set of
**levers**, each one an observation field (or a few fields the engine only
reads together) set to the value the engine treats as most favourable, and
reports:

* whether **model signals alone** (oracle trust, consensus phase, evidence
  confidence, oracle quorum, temperature) can reach the target. For a critical
  production write the answer is no, and the report proves it by enumeration
  rather than by assertion. That is the property the whole architecture rests
  on: a confident model cannot buy autonomy that the deployment did not
  declare.
* whether **the agent alone** can reach it: model signals plus every property
  of the proposal the agent controls (its target, its schema, its payload),
  with nothing the deployment declares. This is the stronger statement a
  security reviewer wants, because a persuasive agent controls both.
* the **smallest change sets** that do reach the target, each change tagged
  with who can bring it about. ``deployment_fact`` levers are declared by the
  deployment (tool registry, Signed ToolSpec, state index, intent source);
  ``proposal`` levers are properties of the call the agent chose to make;
  ``model_signal`` levers are model output.
* the **effect of every single lever** on its own, so a reader sees which
  changes move the verdict at all and which are inert for this call.
* the **hard guard** currently blocking the call, if any, because a hard guard
  is the one class of block that no combination of softer signals can pass.

Everything here is read-only over :class:`RemoraDecisionEngine`. The engine is
never modified or subclassed; each candidate is a fresh
:class:`PolicyObservation` produced by ``dataclasses.replace`` and decided by
the same ``decide()`` that governs real traffic, so a reported counterfactual
is exactly reproducible by constructing that observation and calling the
engine. A report is an analysis of the policy, not a decision, and it grants
nothing: the only way to obtain the target verdict is to establish the named
facts and be assessed again.

Search bounds are explicit. ``max_depth`` caps how many levers may be combined
and ``max_evaluations`` caps distinct engine calls; the report states whether
the space was exhausted, so "no path found" is never mistaken for "no path
exists" when the budget ran out. Two devices keep the search cheap without
changing its answer: a memo so a combination evaluated in a sub-space search
is never decided twice, and, for target ACCEPT only, hard-guard pruning: when
a hard guard is firing, a combination that leaves every field of that guard
untouched still hits the floor and cannot reach ACCEPT, so it is skipped
without an engine call. ``prune=False`` disables it; the test suite asserts
the two modes return identical paths.

Relation to ``remora.causal``: that package replays hand-declared *concept*
interventions (do-calculus over a ``CausalDecisionModel``) and refuses to
intervene on non-actionable signals. This module searches raw observation
fields automatically and includes the non-actionable signals on purpose, to
show that they cannot carry a call past the deployment's declarations.
"""
from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from remora.policy.decision_engine import (
    MIN_REQUIRED_ORACLE_VOTES,
    RemoraDecisionEngine,
    _normalize_observation,
    hard_guard_floor,
)
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason, DecisionReport


class LeverKind(str, Enum):
    """Who can bring a change about."""

    #: Declared by the deployment: registry risk tier, ToolSpec action type,
    #: permitted-tool set, intent authority, grounding against the system of
    #: record, provenance tracking, rollback availability, resolvers.
    DEPLOYMENT_FACT = "deployment_fact"
    #: A property of the call the agent chose to make: its target, its
    #: well-formedness, whether its payload passes the admission firewall.
    PROPOSAL = "proposal"
    #: Produced by models or oracles: trust, consensus phase, evidence
    #: confidence, quorum, temperature. The class an agent's confidence could
    #: influence.
    MODEL_SIGNAL = "model_signal"


#: The kinds an agent can influence without the deployment declaring anything.
AGENT_KINDS: frozenset[LeverKind] = frozenset({LeverKind.PROPOSAL, LeverKind.MODEL_SIGNAL})


@dataclass(frozen=True)
class Lever:
    """One favourable assignment the search may apply to an observation.

    A lever may set more than one field when the engine only reads them
    together (``evidence_action`` with ``evidence_confidence``, a quorum of
    valid oracles with zero failures). It still counts as one change.
    """

    name: str
    kind: LeverKind
    assignments: tuple[tuple[str, Any], ...]
    description: str

    @property
    def fields(self) -> frozenset[str]:
        return frozenset(field for field, _ in self.assignments)

    def applies_to(self, obs: PolicyObservation) -> bool:
        """True when applying the lever would change at least one field."""
        return any(getattr(obs, field) != value for field, value in self.assignments)

    def apply(self, obs: PolicyObservation) -> PolicyObservation:
        return dataclasses.replace(obs, **dict(self.assignments))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "assignments": {field: _jsonable(value) for field, value in self.assignments},
            "description": self.description,
        }


@dataclass(frozen=True)
class Change:
    """One lever as applied to a concrete observation: before and after."""

    lever: str
    kind: LeverKind
    field: str
    before: Any
    after: Any
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "lever": self.lever,
            "kind": self.kind.value,
            "field": self.field,
            "before": _jsonable(self.before),
            "after": _jsonable(self.after),
            "description": self.description,
        }


@dataclass(frozen=True)
class Counterfactual:
    """A set of changes and the verdict the engine returns once they hold."""

    changes: tuple[Change, ...]
    action: DecisionAction
    reasons: tuple[str, ...]

    @property
    def levers(self) -> tuple[str, ...]:
        return tuple(sorted({c.lever for c in self.changes}))

    @property
    def kinds(self) -> frozenset[LeverKind]:
        return frozenset(c.kind for c in self.changes)

    @property
    def size(self) -> int:
        """Number of levers applied (a multi-field lever counts once)."""
        return len(self.levers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "levers": list(self.levers),
            "kinds": sorted(k.value for k in self.kinds),
            "changes": [c.to_dict() for c in self.changes],
            "action": self.action.value,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class LeverEffect:
    """What one lever does on its own: the verdict with only that change."""

    lever: str
    kind: LeverKind
    action: DecisionAction
    reasons: tuple[str, ...]
    #: True when the lever alone changes the verdict from the current one.
    moves: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "lever": self.lever,
            "kind": self.kind.value,
            "action": self.action.value,
            "reasons": list(self.reasons),
            "moves": self.moves,
        }


@dataclass(frozen=True)
class WhatIfReport:
    """The answer to "what would it take for this call to reach *target*?"."""

    target: DecisionAction
    current_action: DecisionAction
    current_reasons: tuple[str, ...]
    #: The hard-guard reason currently firing, or None. A hard guard cannot be
    #: passed by any model signal; only the named fact changing removes it.
    hard_guard: str | None
    #: The smallest model-signal-only change set that reaches the target, or
    #: None when no combination of model signals does. The model-signal
    #: sub-space is always searched to its full depth, so None is a proof over
    #: the catalogue, not a budget artefact.
    model_signals_alone: Counterfactual | None
    #: The smallest change set using only what the agent can influence
    #: (proposal and model-signal levers), or None when none reaches the
    #: target within ``max_depth``.
    without_deployment: Counterfactual | None
    #: Every change set of minimal size that reaches the target, in a stable
    #: order: fewest deployment facts first, then fewest proposal changes,
    #: then fewest changed fields, then lever names.
    minimal_paths: tuple[Counterfactual, ...]
    #: Each applicable lever applied on its own, in catalogue order.
    single_lever_effects: tuple[LeverEffect, ...]
    #: Distinct engine calls made.
    evaluations: int
    max_depth: int
    max_evaluations: int
    #: True when every combination up to ``max_depth`` was evaluated. False
    #: means the evaluation budget stopped the search early.
    exhausted: bool
    #: True when hard-guard pruning skipped combinations that could not have
    #: reached the target.
    pruned: bool
    #: Levers that were applicable to this observation (their favourable value
    #: differed from the current one), by name.
    levers_considered: tuple[str, ...]

    @property
    def already_at_target(self) -> bool:
        return self.current_action is self.target

    @property
    def reachable(self) -> bool:
        return self.already_at_target or bool(self.minimal_paths)

    @property
    def confidence_can_lift(self) -> bool:
        """True when model signals alone reach the target."""
        return self.already_at_target or self.model_signals_alone is not None

    @property
    def agent_alone_can_reach(self) -> bool:
        """True when proposal and model-signal levers reach the target with no
        deployment-declared fact changing."""
        return self.already_at_target or self.without_deployment is not None

    @property
    def deployment_facts_required(self) -> bool:
        """True when the target is reachable within the bound, and only with
        at least one fact the deployment declares."""
        return (
            not self.already_at_target
            and bool(self.minimal_paths)
            and self.without_deployment is None
        )

    @property
    def moving_levers(self) -> tuple[str, ...]:
        """Levers that change the verdict on their own."""
        return tuple(e.lever for e in self.single_lever_effects if e.moves)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.value,
            "current_action": self.current_action.value,
            "current_reasons": list(self.current_reasons),
            "hard_guard": self.hard_guard,
            "already_at_target": self.already_at_target,
            "reachable": self.reachable,
            "confidence_can_lift": self.confidence_can_lift,
            "agent_alone_can_reach": self.agent_alone_can_reach,
            "deployment_facts_required": self.deployment_facts_required,
            "model_signals_alone": (
                self.model_signals_alone.to_dict()
                if self.model_signals_alone is not None else None
            ),
            "without_deployment": (
                self.without_deployment.to_dict()
                if self.without_deployment is not None else None
            ),
            "minimal_paths": [p.to_dict() for p in self.minimal_paths],
            "minimal_path_size": (
                self.minimal_paths[0].size if self.minimal_paths else None
            ),
            "single_lever_effects": [e.to_dict() for e in self.single_lever_effects],
            "moving_levers": list(self.moving_levers),
            "search": {
                "evaluations": self.evaluations,
                "max_depth": self.max_depth,
                "max_evaluations": self.max_evaluations,
                "exhausted": self.exhausted,
                "pruned": self.pruned,
                "levers_considered": list(self.levers_considered),
            },
        }

    def summary(self) -> str:
        """Plain-text rendering, one fact per line, ASCII only."""
        t = self.target.value.upper()
        lines = [
            f"verdict now: {self.current_action.value.upper()}"
            f" ({', '.join(self.current_reasons) or 'no reason recorded'})",
        ]
        if self.hard_guard:
            lines.append(
                f"hard guard: {self.hard_guard}; no model signal can pass it")
        if self.already_at_target:
            lines.append(f"already {t}; nothing to change")
            return "\n".join(lines)
        if self.model_signals_alone is not None:
            lines.append(
                f"model signals alone: reach {t} via "
                + " + ".join(self.model_signals_alone.levers))
        else:
            lines.append(
                f"model signals alone: cannot reach {t}"
                " (trust, phase, evidence, quorum and temperature tried in every combination)")
        if self.without_deployment is not None:
            lines.append(
                f"agent alone (proposal + model signals): reach {t} via "
                + " + ".join(self.without_deployment.levers))
        else:
            lines.append(
                f"agent alone (proposal + model signals): cannot reach {t}"
                f" within {self.max_depth} changes")
        moving = self.moving_levers
        lines.append(
            "single levers that move the verdict: "
            + (", ".join(moving) if moving else "none"))
        if not self.minimal_paths:
            scope = "up to the search bound" if self.exhausted else "within the evaluation budget"
            lines.append(f"no change set reaches {t} {scope}"
                         f" (depth {self.max_depth}, {self.evaluations} evaluations)")
            return "\n".join(lines)
        size = self.minimal_paths[0].size
        lines.append(
            f"smallest change sets reaching {t}: {len(self.minimal_paths)} of size {size}"
            f" ({self.evaluations} evaluations)")
        for i, path in enumerate(self.minimal_paths, start=1):
            lines.append(f"  {i}.")
            for c in path.changes:
                lines.append(
                    f"     {c.field}: {c.before!r} -> {c.after!r}"
                    f"  [{c.kind.value}]  {c.description}")
        if self.deployment_facts_required:
            lines.append("every path needs a fact only the deployment can declare")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lever catalogue
# ---------------------------------------------------------------------------

def _lever(name: str, kind: LeverKind, description: str, **assignments: Any) -> Lever:
    return Lever(name=name, kind=kind,
                 assignments=tuple(sorted(assignments.items())),
                 description=description)


_D = LeverKind.DEPLOYMENT_FACT
_P = LeverKind.PROPOSAL
_M = LeverKind.MODEL_SIGNAL

#: The catalogue. Each entry sets a field to the value the engine treats as
#: most favourable; the search combines them. A lever is only considered for
#: an observation when its value differs from the current one.
LEVERS: tuple[Lever, ...] = (
    # -- model signals ------------------------------------------------------
    _lever("high_trust", _M, "oracle consensus trust at 0.95", trust_score=0.95),
    _lever("ordered_phase", _M, "consensus phase reported as ordered", phase="ordered"),
    _lever("evidence_supports", _M,
           "an evidence provider answers in favour at confidence 0.95",
           evidence_action="answer", evidence_confidence=0.95),
    _lever("oracle_quorum", _M,
           f"{MIN_REQUIRED_ORACLE_VOTES} valid oracle votes and no failures",
           valid_oracle_count=MIN_REQUIRED_ORACLE_VOTES, oracle_failures=0),
    _lever("low_temperature", _M,
           "oracle distribution temperature at 0.0 (only read by an engine "
           "configured with a temperature threshold)",
           temperature=0.0),
    # -- the proposal itself -------------------------------------------------
    _lever("non_production_target", _P, "the call targets a non-production environment",
           target_environment="staging"),
    _lever("firewall_clear", _P, "the payload passes the admission firewall",
           adversarial_detected=False),
    _lever("schema_valid", _P, "the call validates against the tool schema",
           schema_valid=True),
    _lever("no_coercion", _P, "no coercion pattern in the request",
           coercion_detected=False),
    _lever("no_blackmail", _P, "no blackmail pattern in the request",
           blackmail_pattern_detected=False),
    _lever("untainted_arguments", _P,
           "no argument value originates from untrusted content",
           argument_tainted=False, untrusted_controlled_arguments=()),
    # -- deployment-declared facts -------------------------------------------
    _lever("risk_low", _D, "the tool registry declares the tool low risk",
           risk_tier="low"),
    _lever("risk_medium", _D, "the tool registry declares the tool medium risk",
           risk_tier="medium"),
    _lever("read_only_action", _D, "the Signed ToolSpec declares the action read-only",
           action_type="read"),
    _lever("tool_permitted", _D, "the tool is on the permitted list",
           tool_forbidden=False),
    _lever("tool_available", _D, "the tool is in the declared available set",
           tool_not_in_available_set=False),
    _lever("intent_authority", _D,
           "an intent authority (work order) resolves server-side for this call",
           intent_authority_present=True),
    _lever("intent_provenance", _D, "the intent's provenance is resolved",
           intent_provenance_resolved=True),
    _lever("tool_matches_goal", _D, "the declared tool contract matches the goal",
           tool_matches_goal=True),
    _lever("effect_matches", _D, "the declared effect matches the requested one",
           expected_effect_matches=True),
    _lever("values_in_system_of_record", _D,
           "every argument value exists in the system of record",
           argument_values_supported=True),
    _lever("values_grounded", _D, "every argument value traces to this context",
           argument_values_grounded=True, ungrounded_arguments=()),
    _lever("scope_valid", _D, "no argument crosses the tenant scope boundary",
           argument_scope_valid=True),
    _lever("arguments_complete", _D, "no required argument is missing",
           missing_required_arguments=(), arguments_satisfiable=True),
    _lever("arguments_validated", _D, "every required argument is validated",
           unvalidated_required_arguments=()),
    _lever("rollback_available", _D, "a rollback path is declared",
           rollback_available=True),
    _lever("state_transition_known", _D, "the state transition is understood",
           state_transition_uncertain=False),
    _lever("no_distribution_shift", _D, "no distribution shift is flagged",
           distribution_shift_detected=False),
    _lever("environment_confirmed", _D, "the target environment is confirmed",
           environment_mismatch_detected=False, environment_confidence=1.0),
    _lever("counterfactual_passed", _D, "the counterfactual check passed",
           counterfactual_passed=True),
    _lever("no_contradiction", _D, "no contradicting evidence is recorded",
           evidence_contradictions=0, contradiction_cycles=0, claim_graph_betti_1=0),
    _lever("classification_settled", _D,
           "the action classification has no critical or high-risk alternative",
           classification_alternatives=None, classification_confidence=1.0,
           model_misspecification_risk=0.0),
    _lever("session_within_bounds", _D, "session risk and action count are within bounds",
           session_cumulative_risk=0.0, session_action_count=0),
    _lever("fleet_local", _D, "the action's fleet-level effect is local",
           fleet_level_effect="local", policy_generalization_risk=0.0,
           similar_action_seen_count=0),
    _lever("parametric_allowed", _D, "no evidence requirement is imposed by policy",
           refuse_parametric_verdict=False, require_rag=False),
)

_FIELD_NAMES: frozenset[str] = frozenset(f.name for f in dataclasses.fields(PolicyObservation))
for _lv in LEVERS:
    _unknown = _lv.fields - _FIELD_NAMES
    if _unknown:  # pragma: no cover - a catalogue typo fails at import
        raise AssertionError(f"lever {_lv.name!r} names unknown fields {sorted(_unknown)}")

#: Observation fields the engine reads that no lever sets, each with the
#: reason. The completeness test in ``tests/test_policy_whatif.py`` fails when
#: the engine starts reading a field that is neither levered nor listed here,
#: so a new gate cannot silently fall outside the analysis.
UNLEVERED_ENGINE_FIELDS: Mapping[str, str] = {
    "proposed_tool_name": "call identity; changing it would analyse a different call",
    "intent_provenance_required": "policy requirement; the lever resolves provenance instead",
    "argument_resolver_tools": "the lever completes the arguments instead of adding a resolver",
    "assurance_root": "audit anchor only; not read by any gate",
    "weighted_support": "credal input folded into trust; high_trust covers the accept paths",
}

#: For each hard-guard reason, the observation fields its predicate reads. For
#: target ACCEPT a combination touching none of them cannot leave the floor.
_GUARD_FIELDS: Mapping[DecisionReason, frozenset[str]] = {
    DecisionReason.ADMISSION_FIREWALL_BLOCKED: frozenset({"adversarial_detected"}),
    DecisionReason.MALFORMED_CALL_BLOCKED: frozenset({"schema_valid"}),
    DecisionReason.FORBIDDEN_TOOL_BLOCKED: frozenset({"tool_forbidden"}),
    DecisionReason.CROSS_TENANT_ARGUMENT_BLOCKED: frozenset({"argument_scope_valid"}),
    DecisionReason.INTENT_PROVENANCE_REQUIRED: frozenset(
        {"intent_provenance_required", "intent_provenance_resolved"}),
    DecisionReason.COERCION_BLOCKED: frozenset({"coercion_detected"}),
    DecisionReason.BLACKMAIL_BLOCKED: frozenset({"blackmail_pattern_detected"}),
    DecisionReason.COUNTERFACTUAL_FAILED: frozenset({"counterfactual_passed"}),
    DecisionReason.EVIDENCE_CONTRADICTED: frozenset({"evidence_contradictions"}),
    DecisionReason.UNTRUSTED_CONTROLS_SENSITIVE_ARGUMENT: frozenset(
        {"argument_tainted", "untrusted_controlled_arguments"}),
    DecisionReason.TAINTED_ARGUMENT_ESCALATE: frozenset({"argument_tainted"}),
    DecisionReason.TAINTED_ARGUMENT_VERIFY: frozenset({"argument_tainted"}),
}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Enum):
        return value.value
    return value


def _reasons(report: DecisionReport) -> tuple[str, ...]:
    return tuple(r.value for r in report.reasons)


def _changes_for(obs: PolicyObservation, levers: Iterable[Lever]) -> tuple[Change, ...]:
    out: list[Change] = []
    for lever in levers:
        for field, value in lever.assignments:
            before = getattr(obs, field)
            if before != value:
                out.append(Change(lever=lever.name, kind=lever.kind, field=field,
                                  before=before, after=value,
                                  description=lever.description))
    return tuple(out)


def _apply_all(obs: PolicyObservation, levers: Iterable[Lever]) -> PolicyObservation:
    """One ``replace`` for the whole combination: levers are field-disjoint
    by construction, so merging their assignments is order-independent."""
    merged: dict[str, Any] = {}
    for lever in levers:
        merged.update(lever.assignments)
    return dataclasses.replace(obs, **merged)


def _disjoint(levers: Sequence[Lever]) -> bool:
    seen: set[str] = set()
    for lever in levers:
        if seen & lever.fields:
            return False
        seen |= lever.fields
    return True


def _path_sort_key(path: Counterfactual) -> tuple[int, int, int, tuple[str, ...]]:
    """Fewest deployment facts, then fewest proposal changes, then fewest
    changed fields, then lever names: the cheapest path for the reader first."""
    n_deploy = sum(1 for c in path.changes if c.kind is LeverKind.DEPLOYMENT_FACT)
    n_proposal = sum(1 for c in path.changes if c.kind is LeverKind.PROPOSAL)
    return (n_deploy, n_proposal, len(path.changes), path.levers)


class _Search:
    """Depth-bounded, budget-bounded enumeration over lever combinations.

    Decisions are memoised by the set of lever names, so a combination the
    model-signal or agent-only sub-search already decided is not decided
    again in the full search, and ``evaluations`` counts distinct engine
    calls. ``required_fields`` is the hard-guard pruning set: when non-empty,
    a combination touching none of those fields is skipped.
    """

    def __init__(self, engine: RemoraDecisionEngine, obs: PolicyObservation,
                 target: DecisionAction, max_evaluations: int,
                 required_fields: frozenset[str] = frozenset()) -> None:
        self.engine = engine
        self.obs = obs
        self.target = target
        self.max_evaluations = max_evaluations
        self.required_fields = required_fields
        self.evaluations = 0
        self.exhausted = True
        self.pruned = False
        self._memo: dict[tuple[str, ...], DecisionReport] = {}

    def decide(self, levers: Sequence[Lever]) -> DecisionReport | None:
        """Decide the observation with *levers* applied; None when the budget
        is spent."""
        # Combinations are drawn in catalogue order from every sub-space, so
        # the name tuple is canonical without sorting.
        key = tuple(lv.name for lv in levers)
        cached = self._memo.get(key)
        if cached is not None:
            return cached
        if self.evaluations >= self.max_evaluations:
            self.exhausted = False
            return None
        self.evaluations += 1
        report = self.engine.decide(_apply_all(self.obs, levers))
        self._memo[key] = report
        return report

    def _touches_required(self, combo: Sequence[Lever]) -> bool:
        if not self.required_fields:
            return True
        return any(lv.fields & self.required_fields for lv in combo)

    def minimal(self, levers: Sequence[Lever], max_depth: int) -> tuple[Counterfactual, ...]:
        """All target-reaching combinations of the smallest size, or ()."""
        for depth in range(1, min(max_depth, len(levers)) + 1):
            hits: list[Counterfactual] = []
            for combo in itertools.combinations(levers, depth):
                if not _disjoint(combo):
                    continue
                if not self._touches_required(combo):
                    self.pruned = True
                    continue
                report = self.decide(combo)
                if report is None:
                    return tuple(sorted(hits, key=_path_sort_key))
                if report.action is self.target:
                    hits.append(Counterfactual(
                        changes=_changes_for(self.obs, combo),
                        action=report.action, reasons=_reasons(report)))
            if hits:
                return tuple(sorted(hits, key=_path_sort_key))
        return ()

    def singles(self, levers: Sequence[Lever], current: DecisionAction) -> tuple[LeverEffect, ...]:
        """Each lever on its own. Never pruned: the point is to show inertness."""
        out: list[LeverEffect] = []
        for lever in levers:
            report = self.decide((lever,))
            if report is None:
                break
            out.append(LeverEffect(
                lever=lever.name, kind=lever.kind, action=report.action,
                reasons=_reasons(report), moves=report.action is not current))
        return tuple(out)


def what_if(
    obs: PolicyObservation,
    engine: RemoraDecisionEngine | None = None,
    *,
    target: DecisionAction = DecisionAction.ACCEPT,
    max_depth: int = 4,
    max_evaluations: int = 20_000,
    levers: Sequence[Lever] = LEVERS,
    prune: bool = True,
) -> WhatIfReport:
    """Report what would have to change for *obs* to reach *target*.

    Parameters
    ----------
    obs:
        The observation as it was decided. It is not modified.
    engine:
        The engine to ask; defaults to a fresh ``RemoraDecisionEngine()``.
        Pass the deployment's configured engine (execution profile, opt-in
        accept paths) to analyse the policy that actually governs traffic.
    target:
        The verdict to reach. ACCEPT asks what autonomy would take; VERIFY
        asks what would put an ABSTAINed call in front of a person.
    max_depth:
        Maximum number of levers combined in one change set.
    max_evaluations:
        Maximum distinct engine calls across the whole analysis.
    levers:
        The lever catalogue; defaults to :data:`LEVERS`.
    prune:
        Skip combinations a firing hard guard makes hopeless (target ACCEPT
        only). The answer is identical either way; only the evaluation count
        differs.
    """
    if max_depth < 1:
        raise ValueError("max_depth must be at least 1")
    if max_evaluations < 1:
        raise ValueError("max_evaluations must be at least 1")
    engine = engine or RemoraDecisionEngine()
    current = engine.decide(obs)
    floor = hard_guard_floor(_normalize_observation(obs))
    hard_guard = floor[1].value if floor is not None else None
    applicable = tuple(lv for lv in levers if lv.applies_to(obs))
    names = tuple(lv.name for lv in applicable)

    if current.action is target:
        return WhatIfReport(
            target=target, current_action=current.action,
            current_reasons=_reasons(current), hard_guard=hard_guard,
            model_signals_alone=None, without_deployment=None, minimal_paths=(),
            single_lever_effects=(), evaluations=0, max_depth=max_depth,
            max_evaluations=max_evaluations, exhausted=True, pruned=False,
            levers_considered=names,
        )

    required: frozenset[str] = frozenset()
    if prune and floor is not None and target is DecisionAction.ACCEPT:
        required = _GUARD_FIELDS.get(floor[1], frozenset())
    search = _Search(engine, obs, target, max_evaluations, required_fields=required)

    # Sub-spaces first, small to large. The model-signal sub-space is tiny,
    # searched first and to its full depth, so a None there is a statement
    # about the catalogue, not the budget. Single-lever effects come next and
    # are never pruned, so inert levers are shown as inert.
    model_levers = [lv for lv in applicable if lv.kind is LeverKind.MODEL_SIGNAL]
    model_hits = search.minimal(model_levers, max_depth=len(model_levers))
    singles = search.singles(applicable, current.action)
    agent_levers = [lv for lv in applicable if lv.kind in AGENT_KINDS]
    agent_hits = search.minimal(agent_levers, max_depth=max_depth)
    minimal = search.minimal(applicable, max_depth=max_depth)
    return WhatIfReport(
        target=target, current_action=current.action,
        current_reasons=_reasons(current), hard_guard=hard_guard,
        model_signals_alone=model_hits[0] if model_hits else None,
        without_deployment=agent_hits[0] if agent_hits else None,
        minimal_paths=minimal, single_lever_effects=singles,
        evaluations=search.evaluations, max_depth=max_depth,
        max_evaluations=max_evaluations, exhausted=search.exhausted,
        pruned=search.pruned, levers_considered=names,
    )


__all__ = [
    "AGENT_KINDS",
    "LEVERS",
    "UNLEVERED_ENGINE_FIELDS",
    "Change",
    "Counterfactual",
    "Lever",
    "LeverEffect",
    "LeverKind",
    "WhatIfReport",
    "what_if",
]
