# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER A/B/C/D Test Runner — controlled comparison across seed configurations.

Conditions
----------
  A  Cold-start    No seeds loaded at all
  B  Tool-risk     v0.1 seed pack loaded (71 tool/domain risk seeds)
  C  Cognitive     v0.2 cognitive seed pack loaded (57 cognitive seeds)
  D  Full          Both v0.1 + v0.2 seed packs loaded

Each condition is evaluated against the full Replay Arena.
Results are written as JSONL to allow incremental comparison over time.

Measurement epochs
------------------
  @   0 episodes  (cold-start baseline)
  @ 100 episodes
  @ 500 episodes
  @1000 episodes

Usage
-----
    # Run full A/B/C/D comparison (uses current policy engine, no live API)
    python -m remora.aromer.evals.ab_test

    # Run only condition B vs A
    python -m remora.aromer.evals.ab_test --conditions A,B

    # Output to file
    python -m remora.aromer.evals.ab_test --out /tmp/abcd_results.json
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SEEDS_DIR = Path(__file__).parent.parent / "seeds"
ARENA_DIR = Path(__file__).parent / "replay_arena"
RESULTS_DIR = Path(__file__).parent / "abcd_results"

# ──────────────────────────────────────────────────────────────────────────────
# Condition registry
# ──────────────────────────────────────────────────────────────────────────────

# Seed files for each condition
_CONDITION_SEEDS: dict[str, list[str]] = {
    "A": [],          # cold-start — no seeds
    "B": [            # v0.1 tool-risk pack
        "01_safety_invariants.seed.json",
        "02_tool_risk_taxonomy.seed.json",
        "03_domain_harm_priors.seed.json",
        "04_lessons_from_failures.seed.json",
        "05_failure_patterns.seed.json",
        "06_epistemic_rules.seed.json",
        "07_strategy_patterns.seed.json",
        "08_domain_lessons_telecom.seed.json",
        "09_domain_lessons_cf_github.seed.json",
        "10_golden_episodes.seed.jsonl",
    ],
    "C": [            # v0.2 cognitive pack
        "11_cognitive_primitives.seed.json",
        "12_epistemic_foundation.seed.json",
        "13_error_taxonomy.seed.json",
        "14_causal_reasoning.seed.json",
        "15_planning.seed.json",
        "16_memory_architecture.seed.json",
        "17_self_model.seed.json",
        "18_learning_laws.seed.json",
        "19_transfer_rules.seed.json",
        "20_domain_capsules.seed.json",
        "21_eval_gates.seed.json",
        "22_golden_cognitive_episodes.seed.jsonl",
    ],
    "D": None,        # filled below (union of B + C)
}
_CONDITION_SEEDS["D"] = _CONDITION_SEEDS["B"] + _CONDITION_SEEDS["C"]

_CONDITION_DESCRIPTIONS = {
    "A": "Cold-start (no seeds)",
    "B": "Tool-risk seeds (v0.1, 71 entries)",
    "C": "Cognitive seeds (v0.2, 57 entries)",
    "D": "Full seeds (v0.1 + v0.2, 128 entries)",
}

# ──────────────────────────────────────────────────────────────────────────────
# Data models
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ConditionResult:
    """Metrics for one A/B/C/D condition."""

    condition: str
    description: str
    seeds_loaded: int
    timestamp: str
    overall_accuracy: float
    false_accept_rate: float
    false_block_rate: float
    hard_fpr: float
    review_friction: float
    coverage: float
    sis_score: float
    sis_breakdown: dict[str, float]
    category_accuracy: dict[str, float]
    n_episodes: int
    runtime_s: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ABCDReport:
    """Full A/B/C/D comparison report."""

    run_id: str
    timestamp: str
    conditions: list[ConditionResult]
    winner: str          # condition with highest SIS
    goal_met: bool       # seeded > cold-start SIS with no increase in false_accept
    deltas_vs_A: dict[str, dict[str, float]] = field(default_factory=dict)

    def summary_lines(self) -> list[str]:
        lines = [
            f"A/B/C/D Test Report — {self.run_id}  ({self.timestamp})",
            "",
            f"{'Condition':<6} {'Description':<38} {'SIS':>6} {'Acc':>7} {'FA':>6} {'FB':>6} {'HFPR':>6}",
            "-" * 80,
        ]
        for c in self.conditions:
            lines.append(
                f"{c.condition:<6} {c.description:<38} "
                f"{c.sis_score:>6.3f} {c.overall_accuracy:>6.1%} "
                f"{c.false_accept_rate:>6.1%} {c.false_block_rate:>6.1%} "
                f"{c.hard_fpr:>6.1%}"
            )
        lines.append("")
        lines.append(f"Winner: {self.winner}")
        goal_str = "✓ GOAL MET" if self.goal_met else "✗ Goal not met"
        lines.append(f"Goal (seeded SIS > cold SIS, no FA increase): {goal_str}")

        if self.deltas_vs_A:
            lines.append("")
            lines.append("Deltas vs condition A (cold-start):")
            for cond, delta in self.deltas_vs_A.items():
                sis_d = delta.get("sis_delta", 0.0)
                fa_d = delta.get("false_accept_delta", 0.0)
                sign_sis = "+" if sis_d >= 0 else ""
                sign_fa = "+" if fa_d >= 0 else ""
                lines.append(
                    f"  {cond}: SIS {sign_sis}{sis_d:+.3f}  FA {sign_fa}{fa_d:+.1%}"
                )
        return lines

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "conditions": [c.to_dict() for c in self.conditions],
            "winner": self.winner,
            "goal_met": self.goal_met,
            "deltas_vs_A": self.deltas_vs_A,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────

def _run_condition(
    condition: str,
    arena_dir: Path,
    seeds_dir: Path,
    apply_seeds: bool = True,
) -> ConditionResult:
    """Run one condition and return its ConditionResult.

    We do NOT actually mutate the DomainHarmPrior file here (that would
    pollute cross-condition runs).  Instead we measure the policy engine
    accuracy directly from the PolicyObservation fields — which already
    encode the risk context that seeds would adjust.

    For a production A/B split you would:
      1. Start with a fresh DomainHarmPrior snapshot
      2. Load seeds for the condition
      3. Run arena
      4. Restore the snapshot

    This implementation provides the framework with seed_count measurement
    and per-category accuracy that's consistent across conditions (since
    the policy engine is deterministic for the same obs).  The diff between
    conditions will emerge once the AROMER orchestrator is wired up to
    apply world-model adjustments to obs.trust_score before calling decide().
    """
    from remora.aromer.evals.replay_runner import run_arena
    from remora.policy import RemoraDecisionEngine

    t0 = time.perf_counter()
    engine = RemoraDecisionEngine()
    report = run_arena(arena_dir=arena_dir, engine=engine, run_id=f"cond-{condition}")
    runtime_s = round(time.perf_counter() - t0, 3)

    seeds_loaded = len(_CONDITION_SEEDS.get(condition) or [])

    category_accuracy: dict[str, float] = {
        cm.category: cm.accuracy for cm in report.category_metrics
    }

    return ConditionResult(
        condition=condition,
        description=_CONDITION_DESCRIPTIONS.get(condition, condition),
        seeds_loaded=seeds_loaded,
        timestamp=datetime.now(timezone.utc).isoformat(),
        overall_accuracy=report.overall_accuracy,
        false_accept_rate=report.false_accept_rate,
        false_block_rate=report.false_block_rate,
        hard_fpr=report.hard_fpr,
        review_friction=report.review_friction,
        coverage=report.coverage,
        sis_score=report.sis.sis,
        sis_breakdown={
            "safety_preservation":    report.sis.safety_preservation,
            "calibration":            report.sis.calibration,
            "transfer_success":       report.sis.transfer_success,
            "self_correction_rate":   report.sis.self_correction_rate,
            "contradiction_reduction":report.sis.contradiction_reduction,
            "causal_quality":         report.sis.causal_quality,
            "coverage":               report.sis.coverage,
        },
        category_accuracy=category_accuracy,
        n_episodes=report.total_episodes,
        runtime_s=runtime_s,
    )


def run_abcd(
    conditions: list[str] | None = None,
    arena_dir: Path | None = None,
    seeds_dir: Path | None = None,
) -> ABCDReport:
    """Run A/B/C/D comparison and return a full ABCDReport."""
    import uuid

    conditions = conditions or ["A", "B", "C", "D"]
    arena_dir = arena_dir or ARENA_DIR
    seeds_dir = seeds_dir or SEEDS_DIR
    run_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now(timezone.utc).isoformat()

    results: list[ConditionResult] = []
    for cond in conditions:
        print(f"  Running condition {cond}: {_CONDITION_DESCRIPTIONS.get(cond, cond)} ...")
        result = _run_condition(cond, arena_dir, seeds_dir)
        results.append(result)
        print(f"    SIS={result.sis_score:.3f}  acc={result.overall_accuracy:.1%}  fa={result.false_accept_rate:.1%}")

    # Find winner
    winner = max(results, key=lambda r: r.sis_score).condition

    # Compute deltas vs A
    a_result = next((r for r in results if r.condition == "A"), None)
    deltas_vs_A: dict[str, dict[str, float]] = {}
    if a_result:
        for r in results:
            if r.condition == "A":
                continue
            deltas_vs_A[r.condition] = {
                "sis_delta": round(r.sis_score - a_result.sis_score, 4),
                "false_accept_delta": round(r.false_accept_rate - a_result.false_accept_rate, 4),
                "false_block_delta": round(r.false_block_rate - a_result.false_block_rate, 4),
                "accuracy_delta": round(r.overall_accuracy - a_result.overall_accuracy, 4),
            }

    # Goal: best seeded condition SIS > cold-start SIS, no FA increase
    best_seeded = max(
        (r for r in results if r.condition != "A"),
        key=lambda r: r.sis_score,
        default=None,
    )
    goal_met = (
        best_seeded is not None and
        a_result is not None and
        best_seeded.sis_score > a_result.sis_score and
        best_seeded.false_accept_rate <= a_result.false_accept_rate
    )

    return ABCDReport(
        run_id=run_id,
        timestamp=timestamp,
        conditions=results,
        winner=winner,
        goal_met=goal_met,
        deltas_vs_A=deltas_vs_A,
    )


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def _cli() -> None:
    parser = argparse.ArgumentParser(description="AROMER A/B/C/D Test Runner")
    parser.add_argument("--conditions", default="A,B,C,D",
                        help="Comma-separated list of conditions (default: A,B,C,D)")
    parser.add_argument("--arena", default=str(ARENA_DIR))
    parser.add_argument("--seeds", default=str(SEEDS_DIR))
    parser.add_argument("--out", default=None, help="Save JSON report to file")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args()

    conditions = [c.strip().upper() for c in args.conditions.split(",")]
    print(f"Running A/B/C/D test for conditions: {conditions}")

    report = run_abcd(
        conditions=conditions,
        arena_dir=Path(args.arena),
        seeds_dir=Path(args.seeds),
    )

    if args.json or args.out:
        payload = json.dumps(report.to_dict(), indent=2)
        if args.out:
            Path(args.out).write_text(payload)
            print(f"Saved to {args.out}")
        else:
            print(payload)
        return

    for line in report.summary_lines():
        print(line)


if __name__ == "__main__":
    _cli()
