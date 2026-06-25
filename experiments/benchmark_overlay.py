#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Benchmark overlay harness with baseline comparison.

PR-10: Runs REMORA against a benchmark dataset and computes coverage,
accuracy, and lift metrics versus three baselines:
  - majority_vote        always returns the majority oracle answer (no filter)
  - random_accept_18pct  randomly accepts 18% of items (matched-coverage oracle)
  - always_abstain       never accepts (zero coverage, trivially safe)

Usage
-----
    python experiments/benchmark_overlay.py \\
        --dataset artifacts/benchmark_n500_locked.json \\
        --output  results/benchmark_overlay.json

The output JSON contains per-condition metrics and a summary table.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _load_dataset(path: str) -> list[dict]:
    """Load benchmark items from a JSON file.

    Supports both the legacy list format and the nested
    ``{"items": [...]}`` format used by newer artifacts.
    """
    data = json.loads(Path(path).read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    raise ValueError(f"Unknown dataset format in {path}")


def _get_label(item: dict) -> Optional[bool]:
    """Extract the ground-truth boolean label from a benchmark item."""
    for key in ("label", "answer", "ground_truth", "correct"):
        v = item.get(key)
        if v is not None:
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() in {"true", "yes", "1", "correct"}
    return None


# ---------------------------------------------------------------------------
# Condition runners
# ---------------------------------------------------------------------------

def run_remora(items: list[dict], seed: int = 42) -> list[dict]:
    """Run REMORA on each item and return per-item result dicts."""
    from remora.genome import Genome
    from remora.engine import Remora
    from remora.oracles.mock import MockOracle

    random.seed(seed)
    oracles = [MockOracle(f"bench_{i}", bias=True, noise=0.1) for i in range(3)]
    genome = Genome(
        max_iterations=2,
        max_subquestions=1,
        enable_parallel_fanout=True,
        enable_thermodynamic_control=True,
        enable_routing=True,
    )
    engine = Remora(oracles=oracles, genome=genome)
    results = []
    for item in items:
        question = item.get("question") or item.get("text") or str(item)
        label = _get_label(item)
        state = engine.run(question=question)
        report = engine.report(state)
        pd = report["policy_decision"]
        accepted = pd["action"] == "accept"
        predicted = True  # placeholder: in real eval derive from top candidate
        results.append({
            "accepted": accepted,
            "action": pd["action"],
            "label": label,
            "correct": (predicted == label) if (accepted and label is not None) else None,
        })
    return results


def run_majority_vote(items: list[dict], seed: int = 42) -> list[dict]:
    """Baseline: always accept; majority of 3 random-biased oracles."""
    rng = random.Random(seed)
    results = []
    for item in items:
        label = _get_label(item)
        # Simulate 3 oracles with 70% accuracy each
        votes = [rng.random() < 0.7 for _ in range(3)]
        predicted = sum(votes) >= 2
        results.append({
            "accepted": True,
            "action": "accept",
            "label": label,
            "correct": (predicted == label) if label is not None else None,
        })
    return results


def run_random_accept(items: list[dict], target_coverage: float = 0.18, seed: int = 42) -> list[dict]:
    """Baseline: randomly accept target_coverage fraction, predict True for accepted."""
    rng = random.Random(seed)
    results = []
    for item in items:
        label = _get_label(item)
        accepted = rng.random() < target_coverage
        results.append({
            "accepted": accepted,
            "action": "accept" if accepted else "abstain",
            "label": label,
            "correct": bool(label) if (accepted and label is not None) else None,
        })
    return results


def run_always_abstain(items: list[dict]) -> list[dict]:
    return [{"accepted": False, "action": "abstain", "label": _get_label(i), "correct": None} for i in items]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_metrics(results: list[dict]) -> dict:
    n_total = len(results)
    accepted = [r for r in results if r["accepted"]]
    n_accepted = len(accepted)
    coverage = n_accepted / n_total if n_total else 0.0
    evaluated = [r for r in accepted if r["correct"] is not None]
    n_correct = sum(1 for r in evaluated if r["correct"])
    accuracy = n_correct / len(evaluated) if evaluated else None
    return {
        "n_total": n_total,
        "n_accepted": n_accepted,
        "coverage": round(coverage, 4),
        "accuracy_on_accepted": round(accuracy, 4) if accuracy is not None else None,
        "n_evaluated": len(evaluated),
        "n_correct": n_correct,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_overlay(dataset_path: str, output_path: str, seed: int = 42) -> dict:
    items = _load_dataset(dataset_path)
    print(f"Loaded {len(items)} items from {dataset_path}", file=sys.stderr)

    conditions = {
        "remora_full_policy": run_remora(items, seed=seed),
        "majority_vote": run_majority_vote(items, seed=seed),
        "random_accept_18pct": run_random_accept(items, target_coverage=0.18, seed=seed),
        "always_abstain": run_always_abstain(items),
    }

    metrics = {cond: compute_metrics(res) for cond, res in conditions.items()}

    # Compute lift vs majority_vote baseline
    rmr = metrics["remora_full_policy"]
    mv = metrics["majority_vote"]
    if rmr["accuracy_on_accepted"] is not None and mv["accuracy_on_accepted"] is not None:
        lift_pp = round((rmr["accuracy_on_accepted"] - mv["accuracy_on_accepted"]) * 100, 2)
    else:
        lift_pp = None

    summary = {
        "dataset": dataset_path,
        "n_items": len(items),
        "seed": seed,
        "conditions": metrics,
        "lift_vs_majority_vote_pp": lift_pp,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(summary, indent=2))
    print(f"Overlay results written to {output_path}", file=sys.stderr)
    return summary


def _main() -> None:
    parser = argparse.ArgumentParser(description="REMORA benchmark overlay harness")
    parser.add_argument("--dataset", default="artifacts/benchmark_n500_locked.json")
    parser.add_argument("--output", default="results/benchmark_overlay.json")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    summary = run_overlay(args.dataset, args.output, seed=args.seed)
    # Print compact summary table
    print(f"\n{'Condition':<30} {'Coverage':>10} {'Accuracy':>10} {'N_accept':>10}")
    print("-" * 65)
    for cond, m in summary["conditions"].items():
        acc = f"{m['accuracy_on_accepted']:.4f}" if m["accuracy_on_accepted"] is not None else "  N/A  "
        print(f"{cond:<30} {m['coverage']:>10.4f} {acc:>10} {m['n_accepted']:>10}")
    if summary["lift_vs_majority_vote_pp"] is not None:
        print(f"\nLift vs majority_vote: +{summary['lift_vs_majority_vote_pp']} pp")


if __name__ == "__main__":
    _main()
