# Author: Stian Skogbrott
# License: Apache-2.0
"""Regression: the AROMER loop must work for minimal observations.

Two live-path crashes were found via examples/aromer_quickstart.py:

1. ``AromerOrchestrator.decide()`` crashed in ``_phase_from_H(None)`` for any
   observation without thermodynamic state (final_H=None).
2. ``record_ground_truth()`` crashed in the ThermodynamicAdapter for episodes
   recorded without dissensus (final_D=None) — breaking the loop-closing call.

A governance system whose learning loop crashes on minimal input silently
stops learning; these tests pin the conservative behaviour.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from remora.aromer import AromerOrchestrator
from remora.aromer.experience.episode import GroundTruth
from remora.aromer.orchestrator import _phase_from_H
from remora.policy import PolicyObservation


@pytest.fixture()
def aromer(tmp_path: Path) -> AromerOrchestrator:
    return AromerOrchestrator(
        store_path=str(tmp_path / "episodes.jsonl"),
        run_meta_judge=False,
        world_model_shadow_mode=True,
    )


class TestPhaseFromH:
    def test_none_is_conservative_critical(self):
        assert _phase_from_H(None) == "critical"

    def test_known_bands_unchanged(self):
        assert _phase_from_H(0.2) == "ordered"
        assert _phase_from_H(0.6) == "critical"
        assert _phase_from_H(0.9) == "disordered"


class TestMinimalObservationLoop:
    def test_decide_without_thermo_state(self, aromer):
        obs = PolicyObservation(
            question="read weekly usage report",
            domain="reporting", risk_tier="low", action_type="read",
            target_environment="staging", phase="ordered", trust_score=0.88,
        )
        report, episode_id = aromer.decide(obs)
        assert report.action.value in ("accept", "verify", "abstain", "escalate")
        assert episode_id

    def test_full_loop_without_thermo_state(self, aromer):
        obs = PolicyObservation(
            question="update retry limit for ingestion worker",
            domain="infrastructure", risk_tier="medium", action_type="write",
            target_environment="staging", phase="ordered", trust_score=0.84,
        )
        _, episode_id = aromer.decide(obs)
        # The loop-closing call must not crash on final_D=None.
        aromer.record_ground_truth(episode_id, GroundTruth.BENIGN)
        cycle = aromer.adapt()
        assert cycle["store_size"] >= 1
        # No harmful episodes in store → rate is 0.0 or None, never positive.
        assert not cycle["experience"]["false_accept_rate"]

    def test_thermo_signal_still_recorded_when_present(self, aromer):
        obs = PolicyObservation(
            question="DROP TABLE customer_orders",
            domain="database", risk_tier="critical",
            action_type="destructive_write", target_environment="prod",
            trust_score=0.41, final_H=0.7, final_D=0.4,
        )
        _, episode_id = aromer.decide(obs)
        aromer.record_ground_truth(episode_id, GroundTruth.HARMFUL)
        cycle = aromer.adapt()
        # Thermodynamic adapter received the episode (λ proposal computed).
        assert "adaptation" in cycle

    def test_quickstart_example_runs(self):
        # The onboarding example is part of the contract — it must execute.
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "examples/aromer_quickstart.py"],
            capture_output=True, text=True, timeout=120,
            cwd=Path(__file__).resolve().parents[1],
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert "Done." in result.stdout
