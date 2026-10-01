# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Cascade stages: calibration, judge and sample counts must not be bypassed."""
from __future__ import annotations

import json

import pytest

from remora.calibration.platt_scaler import PlattScaler
from remora.cascade.result import CascadeVerdict
from remora.cascade.stages import (
    ConsensusGate,
    CritiqueRevisionGate,
    SelfConsistencyGate,
    _StageContext,
)
from remora.core import Oracle
from remora.oracles.mock import MockOracle


class _Engine:
    def __init__(self, trust):
        self._t = trust

    def run(self, question, context=None):
        t = self._t
        return type("S", (), {
            "last_thermo": type("T", (), {"trust_score": t, "phase": "ordered"})(),
            "oracle_log": [], "candidate_support": {}, "candidates": {},
        })()

    def report(self, state):
        return {}


class _SeqOracle(Oracle):
    def __init__(self, payloads):
        self._p = payloads
        self._i = 0

    @property
    def name(self):
        return "seq"

    def _call(self, prompt):
        p = self._p[min(self._i, len(self._p) - 1)]
        self._i += 1
        return json.dumps(p), 0.0, 1.0


def test_unfitted_scaler_does_not_calibrate():
    gate = ConsensusGate(_Engine(0.619), accept_threshold=0.65, platt_scaler=PlattScaler())
    res = gate.run(_StageContext(question="q"))
    assert res.metadata["calibrated_trust"] == pytest.approx(0.619)
    assert res.verdict is not CascadeVerdict.ACCEPT


def test_critique_gate_does_not_skip_on_raw_trust_when_calibration_lowered_it():
    scaler = PlattScaler()
    scaler.fit([0.8] * 6, [False] * 6)
    consensus = ConsensusGate(_Engine(0.8), accept_threshold=0.65, abstain_threshold=0.0, platt_scaler=scaler)
    ctx = _StageContext(question="q")
    s2 = consensus.run(ctx)
    assert s2.verdict is CascadeVerdict.VERIFY
    gate = CritiqueRevisionGate(
        MockOracle("rev"), MockOracle("judge"), skip_high_trust_threshold=0.65
    )
    res = gate.run(ctx)
    assert not (res.metadata.get("skipped") and res.verdict is CascadeVerdict.ACCEPT)


def test_self_consistency_unparsed_samples_count_against_agreement():
    payloads = [{"answer": "Paris"}] + [{"junk": 1}] * 6
    gate = SelfConsistencyGate(_SeqOracle(payloads), sc_samples=7, sc_threshold=0.72)
    res = gate.run(_StageContext(question="q"))
    assert res.verdict is not CascadeVerdict.ACCEPT
    assert res.metadata["agreement"] == pytest.approx(1 / 7)
