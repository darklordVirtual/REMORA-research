# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tied score blocks, unfitted router default, and stale guardrail thresholds."""
from __future__ import annotations

from remora.selective.conformal import UNATTAINABLE_THRESHOLD
from remora.selective.guardrail import PhaseAwareGuardrail
from remora.selective.risk_coverage import (
    SelectiveAction,
    SelectiveRouter,
    threshold_for_target_risk,
)


def test_tied_block_evaluated_as_a_whole():
    # threshold .9 admits both items (risk .5), so target 0 is unattainable.
    assert threshold_for_target_risk([0.9, 0.9], [True, False], 0.0) >= UNATTAINABLE_THRESHOLD


def test_tied_block_clean_still_attainable():
    assert threshold_for_target_risk([0.9, 0.9, 0.5], [True, True, False], 0.0) == 0.9


def test_unfitted_router_never_accepts():
    d = SelectiveRouter().route(0.99)
    assert d.action is not SelectiveAction.ACCEPT
    assert SelectiveRouter().route(0.5).action is SelectiveAction.ABSTAIN


def test_phase_guardrail_refit_with_too_few_items_resets_threshold():
    g = PhaseAwareGuardrail(target_risk=0.2)
    scores = [0.5 + 0.02 * i for i in range(20)]
    g.fit(scores, [True] * 20, ["ordered"] * 20)
    assert g.route(0.95, "ordered").action is SelectiveAction.ACCEPT
    g.fit([0.9, 0.95], [True, True], ["ordered"] * 2)
    assert g.route(0.99, "ordered").action is not SelectiveAction.ACCEPT
