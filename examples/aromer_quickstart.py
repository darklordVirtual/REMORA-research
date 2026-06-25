# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER quickstart — the full learning loop in ~60 seconds, fully offline.

Demonstrates the closed loop:

    decide → record ground truth → adapt → inspect what was learned

No API keys, no network: MetaJudge is disabled and the episodic store is
written to a temp directory. See docs/quickstart_aromer.md for the live-worker
path (AII, /intelligence, replay publishing).

Run:
    python examples/aromer_quickstart.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.aromer import AromerOrchestrator
from remora.aromer.experience.episode import GroundTruth
from remora.policy import PolicyObservation


def main() -> int:
    store = Path(tempfile.mkdtemp(prefix="aromer-quickstart-")) / "episodes.jsonl"
    aromer = AromerOrchestrator(
        store_path=str(store),
        run_meta_judge=False,        # offline — no Workers AI calls
        world_model_shadow_mode=True,  # always start in shadow mode
    )

    print("=== 1. Govern three agent actions ===\n")
    scenarios = [
        # (observation, what actually happened)
        (PolicyObservation(
            question="read weekly usage report",
            domain="reporting", risk_tier="low", action_type="read",
            target_environment="staging", phase="ordered", trust_score=0.88,
        ), GroundTruth.BENIGN),
        (PolicyObservation(
            question="DROP TABLE customer_orders",
            domain="database", risk_tier="critical", action_type="destructive_write",
            target_environment="prod", trust_score=0.41, final_H=0.7, final_D=0.4,
        ), GroundTruth.HARMFUL),
        (PolicyObservation(
            question="update retry limit for ingestion worker",
            domain="infrastructure", risk_tier="medium", action_type="write",
            target_environment="staging", phase="ordered", trust_score=0.84,
        ), GroundTruth.BENIGN),
    ]

    episode_ids = []
    for obs, _truth in scenarios:
        report, episode_id = aromer.decide(obs)
        episode_ids.append(episode_id)
        print(f"  {obs.question[:45]:<46} -> {report.action.value.upper():9}"
              f" ({', '.join(r.value for r in report.reasons[:2])})")

    print("\n=== 2. Close the loop: record what actually happened ===\n")
    for (obs, truth), episode_id in zip(scenarios, episode_ids):
        aromer.record_ground_truth(episode_id, truth)
        print(f"  {obs.question[:45]:<46} -> ground_truth={truth.value}")

    print("\n=== 3. Run a learning cycle ===\n")
    cycle = aromer.adapt()
    exp = cycle.get("experience", {})
    print(f"  cycle:                  {cycle.get('cycle')}")
    print(f"  episodes in store:      {cycle.get('store_size')}")
    print(f"  false_accept_rate:      {exp.get('false_accept_rate')}")
    print(f"  review_friction:        {exp.get('review_friction')}")
    print(f"  correct_intercept_rate: {exp.get('correct_intercept_rate')}")
    adaptation = cycle.get("adaptation", {})
    print(f"  lambda_coupling:        {adaptation.get('lambda_coupling')}")

    print("\n=== 4. What the world model learned (shadow mode) ===\n")
    summary = aromer.summary()
    for key, value in summary.items():
        if not isinstance(value, (dict, list)):
            print(f"  {key}: {value}")

    print("\nDone. Next steps: docs/quickstart_aromer.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
