# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Unit tests for remora.state.RemoraState (engine session-state contract).

RemoraState was extracted from remora.engine (2026-07-29 refactor). These
tests pin its default contract and the ``from remora.engine import RemoraState``
re-export identity that the extraction promised to preserve.
"""
from __future__ import annotations

from remora.state import RemoraState


def test_remora_state_defaults():
    s = RemoraState(question="q")
    assert s.question == "q"
    assert s.iteration == 0
    assert s.candidates == {}
    assert s.candidate_support == {}
    assert s.falsified == set()
    assert s.oracle_log == []
    assert s.decisions == []
    assert s.external_evidence == []
    # Sentinels distinguishing "built outside run()" from a computed result.
    assert s.adversarial_detected is None
    assert s.coercion_detected is False
    assert s.last_thermo is None


def test_remora_state_reexported_from_engine_is_same_class():
    from remora.engine import RemoraState as EngineReexport

    assert EngineReexport is RemoraState


def test_remora_state_mutable_fields_are_independent_per_instance():
    a = RemoraState(question="a")
    b = RemoraState(question="b")
    a.oracle_log.append("x")
    a.decisions.append("d")
    assert b.oracle_log == []
    assert b.decisions == []
