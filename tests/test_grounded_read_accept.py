# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The deterministic ACCEPT path, and everything it must refuse.

The policy-only execution kernel has no oracle and no trust score, so the
probabilistic ACCEPT could not fire there: every call fell to VERIFY/ABSTAIN
no matter how well-founded. ``GROUNDED_READ_ACCEPT`` is the alternative — not
"we estimate this is safe" but "every question answerable from declared data
has been answered, positively".

Two properties carry the whole path and are tested hardest:

1. **Every clause is load-bearing.** Remove any single grounding signal and
   ACCEPT must disappear. A rule where one condition is decorative is a rule
   nobody can reason about.
2. **It can only convert a fall-through.** It is placed after every hard guard
   and blocking gate, so it must never turn a refusal into an ACCEPT. Asserted
   over a grid, the same way ``test_low_consequence_accept.py`` does.
"""
from __future__ import annotations

import dataclasses

import pytest

from remora.policy import PolicyObservation
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.report import DecisionAction, DecisionReason


def _grounded(**overrides) -> PolicyObservation:
    """A read that satisfies every clause. Overrides break one at a time."""
    base = dict(
        question="read_work_order(WO-1201)",
        risk_tier="low",
        action_type="read",
        target_environment="staging",
        domain="maintenance",
        intent_authority_present=True,
        tool_matches_goal=True,
        expected_effect_matches=True,
        argument_values_supported=True,
        argument_values_grounded=True,
        proposed_tool_name="read_work_order",
    )
    base.update(overrides)
    return PolicyObservation(**base)


def _engine() -> RemoraDecisionEngine:
    return RemoraDecisionEngine(grounded_read_accept=True)


# ── The path itself ────────────────────────────────────────────────────────

def test_a_fully_grounded_read_accepts() -> None:
    report = _engine().decide(_grounded())
    assert report.action is DecisionAction.ACCEPT
    assert DecisionReason.GROUNDED_READ_ACCEPT in report.reasons


def test_the_decision_says_which_signals_carried_it() -> None:
    """An ACCEPT nobody can explain is not usable as evidence.

    The generic ACCEPT wording names evidence and trust state; this path
    consults neither, so reusing it would be a false statement about why the
    action was permitted.
    """
    report = _engine().decide(_grounded())
    assert "grounded declaration" in report.coverage_policy
    assert "no evidence/trust signal used" in report.coverage_policy


def test_it_is_off_by_default() -> None:
    """An unconfigured deployment keeps the behaviour it had.

    Enabling this without declared contracts, a state index and an intent
    source grounds nothing — so the default must not be on.
    """
    report = RemoraDecisionEngine().decide(_grounded())
    assert report.action is not DecisionAction.ACCEPT


def test_the_explain_trace_records_the_rule() -> None:
    trace = _engine().explain(_grounded())
    step = next(s for s in trace.rule_evaluations
                if s.rule == "grounded_read_accept")
    assert step.triggered is True
    assert step.outcome == "ACCEPT"
    assert "intent_authority_present=True" in step.condition
    assert trace.decision_path == "grounded_read_accept → ACCEPT"


# ── Property 1: every clause is load-bearing ───────────────────────────────

@pytest.mark.parametrize("field", [
    "tool_matches_goal",
    "expected_effect_matches",
    "argument_values_supported",
    "argument_values_grounded",
    "intent_authority_present",
])
@pytest.mark.parametrize("value", [None, False])
def test_removing_any_single_grounding_signal_removes_the_accept(
    field: str, value: bool | None
) -> None:
    """None and False both disqualify. Unknown is not grounded.

    ``None`` is the case that would decay silently: a deployment that stops
    declaring contracts would start sending None for every signal, and a rule
    that treated None as satisfied would keep accepting on nothing.
    """
    report = _engine().decide(_grounded(**{field: value}))
    assert report.action is not DecisionAction.ACCEPT, (
        f"{field}={value!r} still reached ACCEPT"
    )
    assert DecisionReason.GROUNDED_READ_ACCEPT not in report.reasons


@pytest.mark.parametrize("tier", ["medium", "high", "critical", None])
def test_only_a_low_risk_tier_qualifies(tier: str | None) -> None:
    report = _engine().decide(_grounded(risk_tier=tier))
    assert report.action is not DecisionAction.ACCEPT


@pytest.mark.parametrize("env", ["prod", "production", "live", "PROD", " Live "])
def test_production_never_qualifies_under_any_alias(env: str) -> None:
    """Blast radius in production includes disclosure of live data, which no
    read-only guarantee covers. All three canonical aliases must be caught —
    ``live`` was reachable while only prod/production were excluded."""
    report = _engine().decide(_grounded(target_environment=env))
    assert report.action is not DecisionAction.ACCEPT, f"{env!r} reached ACCEPT"


@pytest.mark.parametrize("action_type", [
    "write", "production_write", "destructive_write", "delete",
    "config_change", "unknown", None,
])
def test_only_a_positively_declared_read_qualifies(action_type) -> None:
    report = _engine().decide(_grounded(action_type=action_type))
    assert report.action is not DecisionAction.ACCEPT


def test_a_missing_required_argument_disqualifies() -> None:
    report = _engine().decide(
        _grounded(missing_required_arguments=("wo_id",)))
    assert report.action is not DecisionAction.ACCEPT


def test_an_unvalidated_required_argument_disqualifies() -> None:
    report = _engine().decide(
        _grounded(unvalidated_required_arguments=("wo_id",)))
    assert report.action is not DecisionAction.ACCEPT


def test_every_declared_grounding_signal_is_actually_checked() -> None:
    """Guards the list itself against becoming decorative.

    ``_GROUNDING_SIGNALS`` exists so the check cannot quietly stop covering a
    signal. This asserts each named signal genuinely gates the path, so adding
    a name without wiring it would fail here.
    """
    from remora.policy.decision_engine import _GROUNDING_SIGNALS

    for signal in _GROUNDING_SIGNALS:
        report = _engine().decide(_grounded(**{signal: None}))
        assert report.action is not DecisionAction.ACCEPT, (
            f"{signal} is listed as a grounding signal but does not gate the path"
        )


# ── Property 2: it can only convert a fall-through ─────────────────────────

_BLOCKING_SIGNALS = [
    {"argument_tainted": True},
    {"tool_forbidden": True},
    {"adversarial_detected": True},
    {"coercion_detected": True},
    {"blackmail_pattern_detected": True},
    {"distribution_shift_detected": True},
    {"schema_valid": False},
    {"counterfactual_passed": False},
    {"arguments_satisfiable": False},
    {"evidence_contradictions": 2},
]


@pytest.mark.parametrize("signal", _BLOCKING_SIGNALS,
                         ids=lambda s: "+".join(s))
def test_a_blocking_signal_is_never_converted_into_an_accept(signal) -> None:
    """The placement guarantee, asserted rather than trusted.

    The path sits after every hard guard so it can only convert a decision
    that would otherwise fall through to ABSTAIN. If a future refactor moved
    it earlier, an otherwise-perfectly-grounded read carrying a taint or an
    injection would start executing without a human.
    """
    report = _engine().decide(_grounded(**signal))
    assert report.action is not DecisionAction.ACCEPT, (
        f"{signal} was converted into an ACCEPT"
    )
    assert DecisionReason.GROUNDED_READ_ACCEPT not in report.reasons


def test_enabling_the_path_never_makes_any_decision_more_permissive() -> None:
    """Across a grid: turning the flag on may only move ABSTAIN → ACCEPT.

    Any other movement — a VERIFY or ESCALATE becoming ACCEPT, or a decision
    becoming less strict in some other way — would mean the flag is not the
    additive fall-through converter it is documented to be.
    """
    off, on = RemoraDecisionEngine(), _engine()
    grid = []
    for tier in ("low", "medium", "high", "critical"):
        for action in ("read", "query", "write", "production_write", "unknown"):
            for env in ("staging", "dev", "prod"):
                for authority in (True, False, None):
                    for grounded in (True, False, None):
                        grid.append(_grounded(
                            risk_tier=tier, action_type=action,
                            target_environment=env,
                            intent_authority_present=authority,
                            argument_values_grounded=grounded,
                        ))
    for obs in grid:
        before = off.decide(obs).action
        after = on.decide(obs).action
        if before == after:
            continue
        # Two movements are the documented conversion. ABSTAIN -> ACCEPT is
        # the original fall-through. VERIFY -> ACCEPT is allowed only when
        # that VERIFY was itself the authority-resolved fall-through
        # conversion (authority_resolved_review) — the same fall-through,
        # which now routes to a person instead of ABSTAIN when a work order
        # resolved. A VERIFY produced by any gate or guard must never move.
        if (before, after) == (DecisionAction.VERIFY, DecisionAction.ACCEPT):
            before_reasons = [r.value for r in off.decide(obs).reasons]
            assert before_reasons == ["authority_resolved_review"], (
                f"a gated VERIFY moved to ACCEPT: {before_reasons}"
            )
            continue
        assert (before, after) == (DecisionAction.ABSTAIN, DecisionAction.ACCEPT), (
            f"enabling the path moved {before} → {after} for "
            f"risk={obs.risk_tier!r} action={obs.action_type!r} "
            f"env={obs.target_environment!r} authority={obs.intent_authority_present!r}"
        )


def test_it_is_strictly_stronger_than_the_low_consequence_path() -> None:
    """Whatever grounded-read accepts, low-consequence would accept too.

    The reverse must not hold: low-consequence accepts reads that are the
    wrong call for the task, which is the measured cost this path exists to
    remove. If grounded-read ever accepted something low-consequence refuses,
    the two rules have diverged and the "strictly stronger" claim is false.
    """
    from remora.policy.decision_engine import _is_grounded_read, _is_low_consequence

    wrong_call_for_the_task = _grounded(tool_matches_goal=False)
    assert _is_low_consequence(wrong_call_for_the_task) is True
    assert _is_grounded_read(wrong_call_for_the_task) is False

    assert _is_grounded_read(_grounded()) is True
    assert _is_low_consequence(_grounded()) is True


# ── The observation field it depends on ────────────────────────────────────

def test_intent_authority_defaults_to_unknown_not_authorized() -> None:
    """A caller that never sets it must not get the benefit of it."""
    obs = PolicyObservation(question="q")
    assert obs.intent_authority_present is None
    assert _engine().decide(dataclasses.replace(
        _grounded(), intent_authority_present=obs.intent_authority_present,
    )).action is not DecisionAction.ACCEPT
