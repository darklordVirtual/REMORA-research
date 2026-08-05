# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""FT-01: the lifecycle schema becomes a runtime authority, not just YAML.

``remora.governance.lifecycle`` loads ``schemas/execution_lifecycle_v1.yaml``
(single source of truth — no transition table is duplicated in code) and
exposes a tracker that refuses illegal transitions. The property suite is a
searched validation over the declared event domain: sequences of declared
events, applied through the tracker, can never reach an undeclared state,
never leave a terminal state, and can reach UNKNOWN only through
DISPATCHING. No counterexample found in the generated domain — not a proof.
"""
from __future__ import annotations

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from remora.governance.lifecycle import (
    IllegalTransition,
    LifecycleModel,
    LifecycleTracker,
)

MODEL = LifecycleModel.load()


# ── Model coherence ─────────────────────────────────────────────────────────

def test_model_matches_schema_states() -> None:
    assert "PROPOSED" in MODEL.states
    assert "UNKNOWN" in MODEL.terminal_states
    assert MODEL.terminal_states <= MODEL.states


def test_every_transition_endpoint_is_declared() -> None:
    for (src, event), dst in MODEL.transitions.items():
        assert src in MODEL.states, (src, event)
        assert dst in MODEL.states, (src, event, dst)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    sources = {src for (src, _event) in MODEL.transitions}
    assert not (sources & MODEL.terminal_states)


def test_every_nonterminal_state_is_reachable_and_can_terminate() -> None:
    # Reachability from PROPOSED.
    reachable = {"PROPOSED"}
    changed = True
    while changed:
        changed = False
        for (src, _e), dst in MODEL.transitions.items():
            if src in reachable and dst not in reachable:
                reachable.add(dst)
                changed = True
    assert reachable == MODEL.states, MODEL.states - reachable


def test_unknown_is_reachable_only_from_dispatching() -> None:
    sources = {src for (src, _e), dst in MODEL.transitions.items()
               if dst == "UNKNOWN"}
    assert sources == {"DISPATCHING"}


# ── Tracker behavior ────────────────────────────────────────────────────────

def test_tracker_walks_the_review_path() -> None:
    t = LifecycleTracker()
    assert t.state == "PROPOSED"
    t.apply("engine_decision")
    t.apply("verify_or_escalate")
    t.apply("human_approval")
    t.apply("regate_binding_or_freshness_refusal")
    assert t.state == "REFUSED"
    assert t.is_terminal


def test_tracker_refuses_illegal_transition() -> None:
    t = LifecycleTracker()
    with pytest.raises(IllegalTransition):
        t.apply("human_approval")  # PROPOSED cannot be approved


def test_tracker_refuses_events_after_terminal() -> None:
    t = LifecycleTracker()
    t.apply("engine_decision")
    t.apply("abstain_or_hard_refusal")
    assert t.is_terminal
    with pytest.raises(IllegalTransition):
        t.apply("engine_decision")


def test_tracker_records_the_event_trail() -> None:
    t = LifecycleTracker()
    t.apply("engine_decision")
    t.apply("direct_accept_token")
    assert t.trail == (
        ("PROPOSED", "engine_decision", "ASSESSED"),
        ("ASSESSED", "direct_accept_token", "AUTHORIZED"),
    )


# ── Property: no event sequence escapes the declared model ─────────────────

EVENTS = sorted({event for (_s, event) in MODEL.transitions})


class LifecycleMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.tracker = LifecycleTracker()

    @rule(event=st.sampled_from(EVENTS))
    def apply_any_declared_event(self, event: str) -> None:
        before = self.tracker.state
        try:
            self.tracker.apply(event)
        except IllegalTransition:
            assert self.tracker.state == before  # refusal must not move state
        else:
            assert self.tracker.transitions_key(before, event) is not None

    @invariant()
    def state_is_declared(self) -> None:
        assert self.tracker.state in MODEL.states

    @invariant()
    def terminal_is_absorbing(self) -> None:
        if self.tracker.is_terminal:
            for event in EVENTS:
                assert (self.tracker.state, event) not in MODEL.transitions


TestLifecycleProperties = LifecycleMachine.TestCase
TestLifecycleProperties.settings = settings(max_examples=200)
