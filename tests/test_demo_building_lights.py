"""The building-light demo must drive the real engine with canonical outcomes.

Hostile-review finding P1-9: a prior version of the demo hard-coded
ALLOW/BLOCK outcomes with invented confidence percentages and imported
nothing from remora/. These tests pin the replacement to the real
RemoraDecisionEngine and to REMORA's canonical outcome vocabulary, and bind
the README transcript to the script's actual behavior.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_demo():
    spec = importlib.util.spec_from_file_location(
        "demo_building_lights", ROOT / "scripts" / "demo_building_lights.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_building_lights"] = module
    spec.loader.exec_module(module)
    return module


demo = _load_demo()


def test_demo_uses_real_engine() -> None:
    src = (ROOT / "scripts" / "demo_building_lights.py").read_text(encoding="utf-8")
    assert "RemoraDecisionEngine" in src
    assert "PolicyObservation" in src
    for off_canon in ('action="ALLOW"', 'action="BLOCK"', "confidence=0.92"):
        assert off_canon not in src


def test_occupied_floor_accepts_via_evidence() -> None:
    from remora.policy import RemoraDecisionEngine

    engine = RemoraDecisionEngine()
    occupied = next(c for c in demo.FLOORS if c.occupied)
    report = engine.decide(demo.observation_for(occupied))
    assert report.action.value == "accept"
    assert any(r.value == "evidence_supported" for r in report.reasons)


def test_empty_floor_abstains_deny_by_default() -> None:
    from remora.policy import RemoraDecisionEngine

    engine = RemoraDecisionEngine()
    empty = next(c for c in demo.FLOORS if not c.occupied)
    report = engine.decide(demo.observation_for(empty))
    assert report.action.value == "abstain"
    assert any(r.value == "disordered_no_evidence" for r in report.reasons)


def test_readme_transcript_matches_engine_outcomes() -> None:
    """README's demo table must show the outcomes the engine actually returns."""
    from remora.policy import RemoraDecisionEngine

    engine = RemoraDecisionEngine()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    demo_section = readme.split("## Building Automation Demo", 1)[1].split("\n## ", 1)[0]
    for context in demo.FLOORS:
        expected = engine.decide(demo.observation_for(context)).action.value.upper()
        assert expected in demo_section
    # Off-canon vocabulary must not reappear in the transcript
    for off_canon in ("ALLOW ", " BLOCK ", "92%", "96%"):
        assert off_canon not in demo_section
