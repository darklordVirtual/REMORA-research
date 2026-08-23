# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Whether a fully-grounded read can be accepted without a person.

This deployment enables REMORA_GROUNDED_READ_ACCEPT, which is only meaningful
once tool contracts, a state index and an intent source are all declared. It
does NOT make the deployment autonomous: the path requires a non-production
target, because no read-only guarantee covers the disclosure blast radius of
production data, and this gateway reads production.

So these tests pin two things at once — that the machinery is wired, and that
production still refuses. The second is the one that would be tempting to
lose.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.policy.decision_engine import _is_grounded_read  # noqa: E402


class Obs:
    """A fully-grounded read, as the gateway produces one."""

    def __init__(self, **over):
        self.risk_tier = "low"
        self.action_type = "read"
        self.target_environment = "staging"
        self.tool_matches_goal = True
        self.expected_effect_matches = True
        self.arguments_satisfiable = True
        self.argument_values_grounded = True
        self.argument_values_anchored = True
        self.argument_values_supported = True
        self.intent_authority_present = True
        self.schema_valid = True
        self.rollback_available = True
        self.taint_detected = False
        self.coercion_detected = False
        self.adversarial_detected = False
        self.evidence_contradicted = False
        self.mutation = False
        for k, v in over.items():
            setattr(self, k, v)

    def __getattr__(self, name):
        # Any signal the engine looks for and this fixture does not name is
        # absent, not True. Unknown is never grounded.
        return None


def test_a_fully_grounded_non_production_read_is_accepted():
    assert _is_grounded_read(Obs()) is True


@pytest.mark.parametrize("env", ["prod", "production", "live"])
def test_production_is_refused_however_well_grounded(env):
    """The one that matters.

    Everything else about the call is confirmed; the target is production.
    No read-only guarantee covers what disclosing production data costs, so
    this must stay unreachable — it is the active decision in the deployed
    gateway, not a gap in it.
    """
    assert _is_grounded_read(Obs(target_environment=env)) is False


def test_the_four_grounding_signals_are_the_ones_pinned_here():
    """If the engine grows a fifth, this test must be updated deliberately."""
    from remora.policy.decision_engine import _GROUNDING_SIGNALS
    assert set(_GROUNDING_SIGNALS) == {
        "tool_matches_goal", "expected_effect_matches",
        "argument_values_supported", "argument_values_grounded",
    }


def test_a_higher_risk_tier_is_refused():
    assert _is_grounded_read(Obs(risk_tier="medium")) is False


def test_a_mutating_call_is_refused():
    assert _is_grounded_read(Obs(action_type="write", mutation=True)) is False


@pytest.mark.parametrize("signal", [
    "tool_matches_goal", "expected_effect_matches",
    "argument_values_supported", "argument_values_grounded",
])
def test_every_grounding_signal_must_be_positively_true(signal):
    assert _is_grounded_read(Obs(**{signal: None})) is False, \
        f"{signal}=None must not ground: unknown is not confirmed"
    assert _is_grounded_read(Obs(**{signal: False})) is False


def test_no_resolved_authority_is_refused():
    """Made under a work order the deployment recognises, or not at all."""
    assert _is_grounded_read(Obs(intent_authority_present=None)) is False
    assert _is_grounded_read(Obs(intent_authority_present=False)) is False


@pytest.mark.parametrize("concern", [
    "argument_tainted", "coercion_detected", "adversarial_detected",
    "evidence_contradictions", "blackmail_pattern_detected", "tool_forbidden",
])
def test_any_recorded_safety_concern_refuses(concern):
    assert _is_grounded_read(Obs(**{concern: True})) is False
