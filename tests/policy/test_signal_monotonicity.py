# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Signal monotonicity of the decision engine (P-MONO, RMR-AUD-001/003).

Adding a risk or failure signal to an observation must never make the
decision more executable. On the execution path an ABSTAIN has no approval
route, an ESCALATE has one (a higher authority can approve it), and a VERIFY
has one an ordinary reviewer can use, so the order is
``ABSTAIN < ESCALATE < VERIFY < ACCEPT``. The R3 audit (2026-10-18) reproduced
three ways to climb it on master ``b64e3cc1``:

1. a VERIFY gate early in ``_CONDITIONAL_GATES`` hid a later ESCALATE gate;
2. an ESCALATE hard guard hid a non-approvable ABSTAIN guard
   (``schema_valid=False`` turned a cross-tenant refusal into a review item);
3. a risk signal on a call the rest of the policy abstains on for lack of
   evidence (DEFAULT_SAFE_ABSTAIN) opens a review route: a tainted argument
   gives VERIFY, ``schema_valid=False`` gives ESCALATE. That is the engine
   half of RMR-AUD-001. It is still open (strict xfail below): the hard
   guards and the conditional gates are the designed route to a person for
   calls with no trust signal, so closing it is an owner decision on what
   DEFAULT_SAFE_ABSTAIN means. The exploit in RMR-AUD-001 also needs the
   ``/execute`` request to differ from the assessed one, which the
   review-path binding closes.

Searched validation over a declared generated domain: no counterexample found
is not a proof.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from remora.governance.review_queue import Approval, ReviewQueue, _approval_survives
from remora.policy.composition import (
    GRANT_ONLY_REASONS,
    NON_APPROVABLE_REASONS,
    executability,
)
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason, DecisionReport

A, V, AB, E = (DecisionAction.ACCEPT, DecisionAction.VERIFY,
               DecisionAction.ABSTAIN, DecisionAction.ESCALATE)
_ENGINES = (
    RemoraDecisionEngine(),
    RemoraDecisionEngine(low_consequence_accept=True, semantic_authority_floor=True),
    RemoraDecisionEngine(execution_profile=True, low_consequence_accept=True),
)


def _decide(obs: PolicyObservation, engine: RemoraDecisionEngine = _ENGINES[0]):
    return engine.decide(obs)


# ── the audit's counterexamples ────────────────────────────────────────


def test_distribution_shift_does_not_hide_rollback_unavailable():
    base = PolicyObservation(question="drop prod db", risk_tier="critical",
                             action_type="destructive_write", target_environment="prod",
                             rollback_available=False)
    shifted = replace(base, distribution_shift_detected=True)
    assert _decide(base).action is E
    assert _decide(shifted).action is E
    assert DecisionReason.ROLLBACK_UNAVAILABLE in _decide(shifted).reasons


def test_high_risk_without_evidence_does_not_hide_environment_mismatch():
    base = PolicyObservation(question="write", risk_tier="high", action_type="write",
                             evidence_action=None)
    mismatched = replace(base, environment_mismatch_detected=True)
    assert _decide(mismatched).action is E
    assert DecisionReason.ENV_MISMATCH_ESCALATE in _decide(mismatched).reasons


@pytest.mark.parametrize("engine", _ENGINES)
@pytest.mark.parametrize("trusted", [False, True])
def test_taint_never_masks_a_goal_mismatch_escalation(engine, trusted):
    """Review path: an ``untrusted_context`` sets ``argument_tainted``, whose
    floor is VERIFY. A mutating call whose tool does not match the goal is
    ESCALATE, and adding taint must not bring it down to VERIFY (an ordinary
    approver could then redeem it). On a read the mismatch is ABSTAIN and
    stays ABSTAIN."""
    extra = dict(phase="ordered", trust_score=0.92) if trusted else {}
    write = PolicyObservation(question="pay the invoice", risk_tier="medium",
                              action_type="write", proposed_tool_name="send_money",
                              tool_matches_goal=False, rollback_available=True, **extra)
    read = replace(write, action_type="read", proposed_tool_name="get_balance")
    for base in (write, read):
        before = engine.decide(base)
        assert before.action in (E, AB)
        for taint in (dict(argument_tainted=True),
                      dict(argument_tainted=True, untrusted_controlled_arguments=("query",))):
            after = engine.decide(replace(base, **taint))
            assert executability(after.action) <= executability(before.action)
            assert after.action is not V
            assert DecisionReason.TOOL_DOES_NOT_MATCH_GOAL in after.reasons


_REFUSALS = {
    "cross-tenant argument": dict(argument_scope_valid=False),
    "unresolved intent provenance": dict(intent_provenance_required=True,
                                         intent_provenance_resolved=False),
    "call outside the work order's scope": dict(intent_scope_status="out_of_scope"),
    "no scoped work order": dict(intent_scope_status="unbound"),
}
_ESCALATING_FLAGS = {
    "schema_valid=False": dict(schema_valid=False),
    "tool_forbidden": dict(tool_forbidden=True),
    "coercion": dict(coercion_detected=True),
    "argument_tainted": dict(argument_tainted=True),
    "tainted sensitive argument": dict(argument_tainted=True,
                                       untrusted_controlled_arguments=("recipient",)),
}


@pytest.mark.parametrize("refusal", sorted(_REFUSALS))
@pytest.mark.parametrize("flag", sorted(_ESCALATING_FLAGS))
def test_a_non_approvable_refusal_survives_an_escalating_flag(refusal, flag):
    base = PolicyObservation(question="read", risk_tier="low", action_type="read",
                             **_REFUSALS[refusal])
    flagged = replace(base, **_ESCALATING_FLAGS[flag])
    assert _decide(base).action is AB
    report = _decide(flagged)
    assert report.action is AB
    assert not report.human_review_required


def test_an_adversarial_flag_on_an_otherwise_accepted_call_escalates():
    accepted = PolicyObservation(question="read service metrics", risk_tier="low",
                                 action_type="read", phase="ordered", trust_score=0.92)
    assert _decide(accepted).action is A
    report = _decide(replace(accepted, adversarial_detected=True))
    assert report.action is E
    assert report.reasons == (DecisionReason.ADMISSION_FIREWALL_BLOCKED,)


# ── the property ───────────────────────────────────────────────────────

_base = st.builds(
    PolicyObservation,
    question=st.just("q"),
    risk_tier=st.sampled_from(["low", "medium", "high", "critical", None]),
    action_type=st.sampled_from(["read", "write", "delete", "transfer", None]),
    target_environment=st.sampled_from(["prod", "staging", "sandbox", None]),
    trust_score=st.sampled_from([None, 0.1, 0.5, 0.92]),
    phase=st.sampled_from([None, "ordered", "critical", "disordered"]),
    proposed_tool_name=st.sampled_from([None, "send_money", "get_balance", "read_telemetry"]),
    schema_valid=st.sampled_from([None, True]),
    rollback_available=st.sampled_from([None, True]),
    # False in the base too, so a base that already ESCALATEs on a goal or
    # effect mismatch also gets taint and other signals added to it.
    tool_matches_goal=st.sampled_from([None, True, False]),
    expected_effect_matches=st.sampled_from([None, True, False]),
    evidence_action=st.sampled_from([None, "answer", "evidence_accept"]),
    valid_oracle_count=st.sampled_from([0, 3]),
)

#: Hard-guard signals: client-controlled downgrade fields and hard failures.
#: The floor exists to restrict, so none of them may open an approval route.
_FLOOR_SIGNALS = {
    "adversarial": dict(adversarial_detected=True),
    "malformed": dict(schema_valid=False),
    "forbidden": dict(tool_forbidden=True),
    "cross_tenant": dict(argument_scope_valid=False),
    "intent_unresolved": dict(intent_provenance_required=True, intent_provenance_resolved=False),
    "intent_out_of_scope": dict(intent_scope_status="out_of_scope"),
    "intent_unbound": dict(intent_scope_status="unbound"),
    "coercion": dict(coercion_detected=True),
    "blackmail": dict(blackmail_pattern_detected=True),
    "counterfactual_failed": dict(counterfactual_passed=False),
    "contradiction": dict(evidence_contradictions=1),
    "contradiction_cycle": dict(evidence_contradictions=1, contradiction_cycles=1),
    "tainted": dict(argument_tainted=True),
    "tainted_sensitive": dict(argument_tainted=True, untrusted_controlled_arguments=("recipient",)),
}
#: Conditional-gate signals: risk the gates route to review.
_GATE_SIGNALS = {
    "no_rollback": dict(rollback_available=False),
    "uncertain_transition": dict(state_transition_uncertain=True),
    "env_mismatch": dict(environment_mismatch_detected=True),
    "distribution_shift": dict(distribution_shift_detected=True),
    "goal_mismatch": dict(tool_matches_goal=False),
    "effect_contradicted": dict(expected_effect_matches=False),
}
_SIGNALS = {**_FLOOR_SIGNALS, **_GATE_SIGNALS}

#: ABSTAIN reasons that mean "no basis to run autonomously", not "refused".
#: A risk signal on such a call still opens a review route; that is open.
_EPISTEMIC_ABSTAIN = frozenset({
    DecisionReason.DEFAULT_SAFE_ABSTAIN,
    DecisionReason.DISORDERED_NO_EVIDENCE,
    DecisionReason.LOW_TRUST,
})


def _apply(obs: PolicyObservation, names, table) -> PolicyObservation:
    for name in names:
        obs = replace(obs, **table[name])
    return obs


def _rank(report) -> int:
    """The report's place in the meet (``composition.rank`` on its reasons)."""
    if report.action is AB and set(report.reasons) & NON_APPROVABLE_REASONS:
        return -1
    return executability(report.action)


def _epistemic(report) -> bool:
    return report.action is AB and bool(set(report.reasons) & _EPISTEMIC_ABSTAIN)


@settings(max_examples=3000, deadline=None)
@given(_base,
       st.lists(st.sampled_from(sorted(_GATE_SIGNALS)), max_size=2, unique=True),
       st.lists(st.sampled_from(sorted(_FLOOR_SIGNALS)), min_size=1, max_size=3, unique=True),
       st.sampled_from(range(len(_ENGINES))))
def test_adding_a_risk_signal_never_raises_executability(base, gate_signals, floor_signals, which):
    """No signal lifts a decision in the meet's order, and none lifts a refusal
    no review can lift. A call that abstains for lack of evidence is exempt
    (open, see the strict xfail below)."""
    engine = _ENGINES[which]
    gated = _apply(base, gate_signals, _GATE_SIGNALS)
    flagged = _apply(gated, floor_signals, _FLOOR_SIGNALS)
    for before, after, added in ((engine.decide(base), engine.decide(gated), gate_signals),
                                 (engine.decide(gated), engine.decide(flagged), floor_signals)):
        if _epistemic(before):
            continue
        assert _rank(after) <= _rank(before), (
            added, before.action, before.reasons, after.action, after.reasons)


@pytest.mark.xfail(strict=True, reason=(
    "Open (RMR-AUD-001 engine half / RMR-AUD-003 residual): a risk signal on "
    "a call the rest of the policy abstains on for lack of evidence opens a "
    "review route. Hard guards and conditional gates are the designed route "
    "to a person for calls with no trust signal. Closed in the opt-in "
    "strict_monotone profile; the default keeps the published decisions."))
@pytest.mark.parametrize("signal", ["tainted", "malformed", "distribution_shift"])
def test_a_risk_signal_still_opens_a_route_over_an_epistemic_abstain(signal):
    base = PolicyObservation(question="read telemetry", risk_tier="low", action_type="read",
                             proposed_tool_name="read_telemetry", target_environment="staging")
    assert _decide(base).reasons == (DecisionReason.DEFAULT_SAFE_ABSTAIN,)
    assert _decide(replace(base, **_SIGNALS[signal])).action is AB


@pytest.mark.xfail(strict=True, reason=(
    "Open, present on master before RMR-AUD-003: raising a production write's "
    "risk tier from medium to high lowers the decision from ESCALATE (trap "
    "gate) to VERIFY (the explicit matrix, which "
    "test_production_write_matrix_is_explicit_and_conservative pins). Closed "
    "in the opt-in strict_monotone profile; the default keeps the matrix."))
def test_raising_the_risk_tier_never_lowers_a_production_write():
    medium = PolicyObservation(question="q", risk_tier="medium", action_type="production_write",
                               target_environment="prod", schema_valid=True)
    high = replace(medium, risk_tier="high")
    assert executability(_decide(high).action) <= executability(_decide(medium).action)



# ── the strict profile closes both (RemoraDecisionEngine(strict_monotone=True)) ──

_STRICT = (
    RemoraDecisionEngine(strict_monotone=True),
    RemoraDecisionEngine(strict_monotone=True, execution_profile=True,
                         low_consequence_accept=True),
)
_APPROVABILITY = {AB: 0, E: 1, V: 2, A: 3}


@pytest.mark.parametrize("signal", ["tainted", "malformed", "distribution_shift"])
def test_strict_a_risk_signal_never_opens_a_route_over_an_epistemic_abstain(signal):
    base = PolicyObservation(question="read telemetry", risk_tier="low", action_type="read",
                             proposed_tool_name="read_telemetry", target_environment="staging")
    strict = _STRICT[0]
    assert strict.decide(base).reasons == (DecisionReason.DEFAULT_SAFE_ABSTAIN,)
    flagged = strict.decide(replace(base, **_SIGNALS[signal]))
    assert flagged.action is AB
    assert DecisionReason.RISK_SIGNAL_NO_ROUTE in flagged.reasons  # why it stayed shut
    assert _decide(replace(base, **_SIGNALS[signal])).action is not AB  # the default differs


def test_strict_raising_the_risk_tier_never_lowers_a_production_write():
    medium = PolicyObservation(question="q", risk_tier="medium", action_type="production_write",
                               target_environment="prod", schema_valid=True)
    for strict in _STRICT:
        for tier in ("high", "critical"):
            high = strict.decide(replace(medium, risk_tier=tier))
            assert executability(high.action) <= executability(strict.decide(medium).action)


@settings(max_examples=1500, deadline=None)
@given(_base,
       st.lists(st.sampled_from(sorted(_GATE_SIGNALS)), max_size=2, unique=True),
       st.lists(st.sampled_from(sorted(_FLOOR_SIGNALS)), min_size=1, max_size=3, unique=True),
       st.sampled_from(range(len(_STRICT))))
def test_strict_adding_a_risk_signal_never_raises_approvability(base, gate_signals,
                                                                 floor_signals, which):
    """The default property above exempts an epistemic ABSTAIN; the strict
    profile does not: no signal makes any call more approvable."""
    engine = _STRICT[which]
    gated = _apply(base, gate_signals, _GATE_SIGNALS)
    flagged = _apply(gated, floor_signals, _FLOOR_SIGNALS)
    for before, after, added in ((engine.decide(base), engine.decide(gated), gate_signals),
                                 (engine.decide(gated), engine.decide(flagged), floor_signals)):
        assert _APPROVABILITY[after.action] <= _APPROVABILITY[before.action], (
            added, before.action, before.reasons, after.action, after.reasons)


def test_the_default_profile_is_unchanged_by_the_strict_option():
    """Strict is opt-in: the default engine decides as before (golden tables,
    Rego parity and sealed replays rely on it)."""
    from remora.policy.decision_engine import RemoraDecisionEngine as Engine

    assert Engine().strict_monotone is False

# ── Multi-dimensional reference decision model (R1 differential testing) ───

_MEET_RANK = {
    "forbidden": -1,
    "epistemic_unrouted": 0,
    "declassifier_grant": 0,
    "senior_authority": 0,
    "ordinary_reviewer": 1,
    "none": 2,
}


@dataclass(frozen=True)
class DecisionSemantics:
    """Explicit six-dimension reference projection of a policy decision.

    Separates:
    1. ``authorized_now``: whether execution is authorized immediately;
    2. ``hard_prohibition``: whether an unwaivable prohibition fired;
    3. ``epistemic_gap``: whether facts/evidence are missing;
    4. ``verification_obligations``: concrete arguments/facts to resolve;
    5. ``required_authority``: authority needed to proceed;
    6. ``invalidation_triggers``: conditions that void a prior approval.
    """

    authorized_now: bool
    hard_prohibition: bool
    epistemic_gap: bool
    verification_obligations: tuple[str, ...]
    required_authority: str
    invalidation_triggers: frozenset[str]


def project_semantics(report: DecisionReport) -> DecisionSemantics:
    reasons = set(report.reasons)
    hard_prohibition = (
        report.action is AB and bool(reasons & NON_APPROVABLE_REASONS)
    )
    obligations = (
        tuple(report.resolution_plan.target_arguments)
        if report.resolution_plan is not None else ()
    )
    epistemic_gap = (
        bool(obligations)
        or (report.action is AB and bool(
            reasons & (_EPISTEMIC_ABSTAIN | {DecisionReason.NO_RESOLVER_AVAILABLE})
        ))
    )
    if hard_prohibition:
        authority = "forbidden"
    elif reasons & GRANT_ONLY_REASONS:
        authority = "declassifier_grant"
    elif report.action is A:
        authority = "none"
    elif report.action is AB:
        authority = "epistemic_unrouted"
    elif report.action is E:
        authority = "senior_authority"
    else:
        authority = "ordinary_reviewer"

    triggers = frozenset({
        "payload_or_envelope_change",
        "context_or_actor_change",
        "risk_tier_change",
        "approval_policy_change",
        "fresh_abstain",
        "grant_only_reason",
        "any_new_reason",
    })
    return DecisionSemantics(
        authorized_now=(report.action is A and not (reasons & GRANT_ONLY_REASONS)),
        hard_prohibition=hard_prohibition,
        epistemic_gap=epistemic_gap,
        verification_obligations=obligations,
        required_authority=authority,
        invalidation_triggers=triggers,
    )


def ref_approval_survives(
    approved_action: DecisionAction,
    approved_reasons: tuple[str, ...],
    fresh_report: DecisionReport,
) -> bool:
    """Reference specification for when a human approval survives re-evaluation."""
    sem = project_semantics(fresh_report)
    if sem.hard_prohibition or fresh_report.action is AB:
        return False
    if sem.required_authority == "declassifier_grant":
        return False
    fresh_reasons = {r.value for r in fresh_report.reasons}
    if approved_action is V:
        if fresh_report.action is A:
            return True
        if fresh_report.action is V:
            return fresh_reasons <= set(approved_reasons)
        return False
    if approved_action is E:
        if fresh_report.action in (A, V, E):
            return fresh_reasons <= set(approved_reasons)
    return False


@settings(max_examples=500, deadline=None)
@given(
    _base,
    st.sampled_from(["cross_tenant", "intent_unresolved"]),
    st.sampled_from([None, 0.5, 0.99]),
    st.sampled_from([None, "ordered", "critical"]),
    st.sampled_from(range(len(_ENGINES))),
)
def test_ref_model_hard_prohibition_never_lifted_by_confidence_or_review(
    base: PolicyObservation,
    prohibition: str,
    trust: float | None,
    phase: str | None,
    which: int,
) -> None:
    """Property 1: A hard prohibition cannot be lifted by model confidence or review."""
    engine = _ENGINES[which]
    obs = replace(base, trust_score=trust, phase=phase, **_FLOOR_SIGNALS[prohibition])
    report = engine.decide(obs)
    sem = project_semantics(report)
    assert not sem.authorized_now
    assert sem.hard_prohibition
    assert sem.required_authority == "forbidden"
    queue = ReviewQueue(engine=engine)
    with pytest.raises(ValueError, match="only VERIFY and ESCALATE"):
        queue.enqueue(obs, report.action, reasons=[r.value for r in report.reasons])


@settings(max_examples=500, deadline=None)
@given(
    _base,
    st.lists(st.sampled_from(sorted(_SIGNALS)), min_size=1, max_size=3, unique=True),
    st.sampled_from(range(len(_ENGINES))),
)
def test_ref_model_risk_signal_never_creates_execution_authority(
    base: PolicyObservation,
    added_signals: list[str],
    which: int,
) -> None:
    """Property 2: A new risk signal never creates autonomous execution authority,
    and on non-epistemic base calls never raises the meet rank."""
    engine = _ENGINES[which]
    before_report = engine.decide(base)
    after_report = engine.decide(_apply(base, added_signals, _SIGNALS))
    before_sem = project_semantics(before_report)
    after_sem = project_semantics(after_report)
    if not before_sem.authorized_now:
        assert not after_sem.authorized_now
    if before_sem.hard_prohibition:
        assert after_sem.hard_prohibition
        assert after_sem.required_authority == "forbidden"
    if not _epistemic(before_report):
        assert (
            _MEET_RANK[after_sem.required_authority]
            <= _MEET_RANK[before_sem.required_authority]
        )


def test_ref_model_verification_satisfies_only_documented_obligations() -> None:
    """Property 4: Resolving a verification obligation removes only that obligation
    and re-evaluates all remaining gates rather than automatically granting ACCEPT."""
    engine = RemoraDecisionEngine(low_consequence_accept=True, semantic_authority_floor=True)
    unresolved = PolicyObservation(
        question="read customer record",
        risk_tier="low",
        action_type="read",
        target_environment="staging",
        proposed_tool_name="get_customer",
        schema_valid=True,
        tool_matches_goal=True,
        expected_effect_matches=True,
        missing_required_arguments=("customer_id", "region_id"),
        argument_resolver_tools=("lookup_customer",),
        arguments_satisfiable=True,
    )
    r1 = engine.decide(unresolved)
    s1 = project_semantics(r1)
    assert r1.action is V
    assert s1.verification_obligations == ("customer_id", "region_id")
    assert not s1.authorized_now

    # Resolving only customer_id leaves region_id obligated -> still VERIFY
    partial = replace(unresolved, missing_required_arguments=("region_id",))
    r2 = engine.decide(partial)
    s2 = project_semantics(r2)
    assert r2.action is V
    assert s2.verification_obligations == ("region_id",)

    # Resolving all obligations when another gate fires (e.g. tainted argument or write)
    # re-evaluates all gates and never auto-accepts
    resolved_but_tainted = replace(
        unresolved, missing_required_arguments=(), argument_tainted=True
    )
    r3 = engine.decide(resolved_but_tainted)
    s3 = project_semantics(r3)
    assert r3.action is V
    assert s3.verification_obligations == ()
    assert not s3.authorized_now

    # Resolving all obligations on a clean low-consequence read with semantic fit -> ACCEPT
    resolved_clean = replace(unresolved, missing_required_arguments=())
    r4 = engine.decide(resolved_clean)
    s4 = project_semantics(r4)
    assert r4.action is A
    assert s4.authorized_now


@settings(max_examples=500, deadline=None)
@given(
    st.sampled_from([V, E]),
    st.lists(
        st.sampled_from([
            DecisionReason.EVIDENCE_INSUFFICIENT,
            DecisionReason.TAINTED_ARGUMENT_VERIFY,
            DecisionReason.DISTRIBUTION_SHIFT,
            DecisionReason.ROLLBACK_UNAVAILABLE,
            DecisionReason.MALFORMED_CALL_BLOCKED,
        ]),
        min_size=1,
        max_size=3,
        unique=True,
    ),
    st.sampled_from([A, V, E, AB]),
    st.lists(
        st.sampled_from([
            DecisionReason.EVIDENCE_INSUFFICIENT,
            DecisionReason.TAINTED_ARGUMENT_VERIFY,
            DecisionReason.DISTRIBUTION_SHIFT,
            DecisionReason.ROLLBACK_UNAVAILABLE,
            DecisionReason.MALFORMED_CALL_BLOCKED,
            DecisionReason.FLOW_CONFIDENTIALITY_VIOLATION,
            DecisionReason.CROSS_TENANT_ARGUMENT_BLOCKED,
        ]),
        min_size=1,
        max_size=3,
        unique=True,
    ),
)
def test_ref_model_differential_approval_survival(
    approved_action: DecisionAction,
    approved_reasons_enum: list[DecisionReason],
    fresh_action: DecisionAction,
    fresh_reasons_enum: list[DecisionReason],
) -> None:
    """Property 5 (R1 differential test): ReviewQueue._approval_survives matches
    the reference specification across all combinations of actions and reasons."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    approved_reasons = tuple(sorted({r.value for r in approved_reasons_enum}))
    approval = Approval(
        item_id="item-1",
        approved_action=approved_action,
        approver="reviewer-1",
        issued_at=now,
        expires_at=now + timedelta(minutes=10),
        tool_call_hash="h" * 64,
        observation_hash="o" * 64,
        approved_reasons=approved_reasons,
    )
    fresh_report = DecisionReport(
        action=fresh_action,
        reasons=tuple(fresh_reasons_enum),
        risk_estimate=0.5,
        confidence=0.5,
        coverage_policy="test",
        evidence_required=False,
        human_review_required=fresh_action in (V, E),
        audit_root=None,
        explanation="test",
        raw_observation=PolicyObservation(question="q"),
    )
    assert _approval_survives(fresh_report, approval) == ref_approval_survives(
        approved_action, approved_reasons, fresh_report
    )


def input_oracle_from_observation(
    obs: PolicyObservation,
    engine: RemoraDecisionEngine,
) -> dict[str, object]:
    """Input-driven reference oracle (SDD v2 AR-005 / R7).

    Derives expected safety constraints directly from the input ``obs`` and
    ``engine`` flags without reading ``DecisionReport.reasons``:
    - ``input_hard_prohibition``: whether cross-tenant scope, unresolved
      required intent provenance or a call outside its work order's scope
      forbids execution and review;
    - ``input_blocks_autonomy``: whether any input floor/gate/profile signal
      forbids autonomous ACCEPT;
    - ``input_obligations``: concrete missing or unvalidated required arguments.
    """
    tier = (obs.risk_tier or "").strip().lower()
    if tier not in {"low", "medium", "high", "critical"}:
        tier = "unknown"
    action = (obs.action_type or "").strip().lower()
    env = (obs.target_environment or "").strip().lower()

    input_hard_prohibition = (
        obs.argument_scope_valid is False
        or bool(obs.intent_provenance_required and not obs.intent_provenance_resolved)
        or obs.intent_scope_status not in (None, "in_scope")
    )

    floor_checks = (
        input_hard_prohibition,
        bool(obs.adversarial_detected),
        obs.schema_valid is False,
        bool(obs.tool_forbidden),
        bool(obs.coercion_detected),
        bool(obs.blackmail_pattern_detected),
        obs.counterfactual_passed is False,
        bool(obs.evidence_contradictions and obs.evidence_contradictions > 0),
        bool(obs.argument_tainted),
        obs.flow_status is not None and obs.flow_status not in ("evaluated", "not_declared"),
        obs.flow_status == "evaluated" and (
            bool(obs.flow_confidentiality_violation) or bool(obs.flow_integrity_violation)
        ),
    )
    floor_fires = any(floor_checks)

    gate_checks = (
        floor_fires,
        obs.tool_matches_goal is False,
        obs.expected_effect_matches is False,
        bool(obs.distribution_shift_detected),
        bool(obs.environment_mismatch_detected),
        tier in ("high", "critical"),
        tier == "unknown" and (action in {"write", "delete"} or env in {"prod", "production", "live"}),
        action == "delete",
        obs.rollback_available is False and tier in ("high", "critical"),
        bool(obs.state_transition_uncertain) and tier in ("high", "critical"),
        obs.valid_oracle_count > 0 and obs.valid_oracle_count < 3,
        obs.schema_valid is None and action in {"write", "delete", "production_write", "destructive_write"},
        bool(obs.proposed_tool_name) and not action,
        action not in {"", "read", "write", "delete", "production_write", "destructive_write"},
        bool(
            engine.semantic_authority_floor
            and obs.proposed_tool_name
            and (obs.tool_matches_goal is None or obs.expected_effect_matches is None)
        ),
        bool(obs.missing_required_arguments),
        bool(obs.unvalidated_required_arguments),
        obs.argument_values_grounded is False,
    )
    gate_or_floor_blocks_accept = any(gate_checks)

    read_only = action == "read"
    ordered_high_trust = obs.phase == "ordered" and (obs.trust_score or 0.0) >= 0.72
    evidence_supported = (
        obs.evidence_action in ("answer", "evidence_accept")
        and (obs.evidence_confidence or 0.0) >= 0.70
        and (obs.phase == "ordered" or (obs.trust_score or 0.0) >= 0.72)
    )
    low_consequence_checks = (
        engine.low_consequence_accept,
        read_only,
        env not in {"prod", "production", "live"},
        not gate_or_floor_blocks_accept,
        not (engine.execution_profile and (ordered_high_trust or evidence_supported)),
        obs.phase != "critical",
        not (obs.phase == "disordered" and obs.evidence_action != "answer"),
        not (obs.trust_score is not None and obs.trust_score < 0.20 and obs.evidence_action != "answer"),
        obs.arguments_satisfiable is not False,
        obs.argument_values_supported is not False,
    )
    low_consequence_eligible = all(low_consequence_checks)
    probabilistic_eligible = (
        not engine.execution_profile
        and not gate_or_floor_blocks_accept
        and (ordered_high_trust or evidence_supported)
    )
    obligations = tuple(dict.fromkeys(
        obs.missing_required_arguments or obs.unvalidated_required_arguments or ()
    ))
    return {
        "input_hard_prohibition": input_hard_prohibition,
        "input_blocks_autonomy": not (low_consequence_eligible or probabilistic_eligible),
        "input_obligations": obligations,
    }


@settings(max_examples=800, deadline=None)
@given(
    _base,
    st.lists(st.sampled_from(sorted(_SIGNALS)), max_size=2, unique=True),
    st.sampled_from(range(len(_ENGINES))),
)
def test_input_driven_oracle_matches_engine_decision(
    base: PolicyObservation,
    signals: list[str],
    which: int,
) -> None:
    """SDD v2 AR-005 / R7: input-derived specification from PolicyObservation
    agrees with RemoraDecisionEngine.decide without reading report.reasons."""
    engine = _ENGINES[which]
    obs = _apply(base, signals, _SIGNALS)
    spec = input_oracle_from_observation(obs, engine)
    report = engine.decide(obs)
    sem = project_semantics(report)

    assert sem.hard_prohibition == spec["input_hard_prohibition"], (obs, report)
    if spec["input_hard_prohibition"]:
        assert report.action is AB
        assert sem.required_authority == "forbidden"
    if spec["input_blocks_autonomy"]:
        assert report.action is not A
        assert not sem.authorized_now
    else:
        assert report.action is A
        assert sem.authorized_now


