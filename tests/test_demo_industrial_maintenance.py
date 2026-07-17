# Author: Stian Skogbrott
# License: Apache-2.0
"""The industrial-maintenance demo must drive the real engine with canonical
outcomes.

Pins the demo's five-step autonomy boundary to actual RemoraDecisionEngine
behavior: reads ACCEPT, tainted work-order proposals VERIFY, contradicting
evidence ABSTAINs, and undelegated OT actuation hard-ESCALATEs — so the demo
can never drift into narrating outcomes the engine does not produce.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from remora.policy import RemoraDecisionEngine
from remora.policy.report import DecisionAction, DecisionReason

ROOT = Path(__file__).resolve().parents[1]


def _load_demo():
    spec = importlib.util.spec_from_file_location(
        "demo_industrial_maintenance",
        ROOT / "scripts" / "demo_industrial_maintenance.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_industrial_maintenance"] = module
    spec.loader.exec_module(module)
    return module


demo = _load_demo()

EXPECTED = {
    "read_vibration_telemetry": (DecisionAction.ACCEPT, None),
    "read_equipment_history": (DecisionAction.ACCEPT, None),
    "propose_workorder_change": (
        DecisionAction.VERIFY, DecisionReason.TAINTED_ARGUMENT_VERIFY,
    ),
    "propose_with_contradicting_evidence": (
        DecisionAction.ABSTAIN, DecisionReason.EVIDENCE_CONTRADICTED,
    ),
    "direct_ot_actuation": (
        DecisionAction.ESCALATE, DecisionReason.FORBIDDEN_TOOL_BLOCKED,
    ),
}


def test_demo_uses_real_engine() -> None:
    src = (ROOT / "scripts" / "demo_industrial_maintenance.py").read_text(
        encoding="utf-8"
    )
    assert "RemoraDecisionEngine" in src
    assert "PolicyObservation" in src


def test_every_step_produces_the_narrated_outcome() -> None:
    engine = RemoraDecisionEngine()
    actions = {a.label: a for a in demo.build_actions()}
    assert set(actions) == set(EXPECTED)
    for label, (expected_action, expected_reason) in EXPECTED.items():
        report = engine.decide(actions[label].observation)
        assert report.action == expected_action, label
        if expected_reason is not None:
            assert expected_reason in report.reasons, label


def test_actuation_block_is_confidence_independent() -> None:
    """High trust and strong evidence must not unlock undelegated actuation."""
    engine = RemoraDecisionEngine()
    actuation = {a.label: a for a in demo.build_actions()}["direct_ot_actuation"]
    assert actuation.observation.trust_score >= 0.9
    report = engine.decide(actuation.observation)
    assert report.action == DecisionAction.ESCALATE
    assert report.human_review_required


def test_demo_main_runs_and_exits_zero(capsys) -> None:
    assert demo.main() == 0
    out = capsys.readouterr().out
    assert "ESCALATE" in out
    assert "forbidden_tool_blocked" in out
