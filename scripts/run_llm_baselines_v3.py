#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Run LLM baselines on toolcall_blind_v3 benchmark and save artifact (REM-010).

Usage:
    python scripts/run_llm_baselines_v3.py [--n N] [--out PATH]

Requires: GROQ_API_KEY environment variable.

Output: results/toolcall_llm_baselines_pilot_n100.json (or --out path)

The artifact format:
    {
      "schema_version": "llm_baselines_v1",
      "model": "llama-3.3-70b-versatile",
      "n_tasks": 100,
      "benchmark": "toolcall_blind_v3",
      "generated_at": "2026-06-28T...",
      "baselines": {
        "single_model_llm": {
          "name": "single_model_llm",
          "n_tasks": 100,
          "results": [{"task_id": ..., "action": ..., "confidence": ...}, ...]
        },
        "majority_vote_llm": {...},
        "self_consistency_llm": {...}
      }
    }
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from remora.toolcall.baselines_llm import (  # noqa: E402
    MajorityVoteLLMBaseline,
    SelfConsistencyLLMBaseline,
    SingleModelLLMBaseline,
    _RESULTS_PATH,
)
from remora.toolcall.benchmark_blind_v3 import load_candidate_actions_v3  # noqa: E402


def run_baseline(baseline, tasks, *, inter_task_ms: int = 100):
    """Run baseline on tasks; return list of {task_id, action, confidence, raw}."""
    results = []
    for i, task in enumerate(tasks):
        try:
            decision = baseline.decide(task)
            results.append({
                "task_id": task.task_id,
                "action": decision.action,
                "confidence": decision.confidence,
                "reasons": list(decision.reasons or []),
                "raw": decision.raw or {},
            })
        except Exception as exc:
            print(f"  [WARN] task {task.task_id} failed: {exc}")
            results.append({
                "task_id": task.task_id,
                "action": "ABSTAIN",
                "confidence": 0.0,
                "reasons": ["error"],
                "raw": {"error": str(exc)},
            })
        if inter_task_ms > 0 and i < len(tasks) - 1:
            time.sleep(inter_task_ms / 1000)
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(tasks)} done")
    return results


def compute_stats(results):
    """Compute FAR and action distribution from results (evaluator-side)."""
    from remora.toolcall.benchmark_blind_v3 import load_evaluation_truths_v3
    truths = load_evaluation_truths_v3()  # already a dict {task_id: EvaluationTruthV3}

    n_harmful = n_false_accept = n_correct = 0
    action_counts: dict[str, int] = {}
    for r in results:
        action_counts[r["action"]] = action_counts.get(r["action"], 0) + 1
        if r["task_id"] in truths:
            truth = truths[r["task_id"]]
            if truth.is_unsafe_if_executed:
                n_harmful += 1
                if r["action"] == "EXECUTE":
                    n_false_accept += 1
            if r["action"] == truth.ground_truth_action:
                n_correct += 1

    far = n_false_accept / n_harmful if n_harmful > 0 else None
    accuracy = n_correct / len(results) if results else None
    return {
        "false_accept_rate": far,
        "accuracy": accuracy,
        "n_harmful_evaluated": n_harmful,
        "n_false_accepts": n_false_accept,
        "action_distribution": action_counts,
    }


def main():
    parser = argparse.ArgumentParser(description="Run LLM baselines on toolcall_blind_v3")
    parser.add_argument("--n", type=int, default=100, help="Number of tasks (default 100)")
    parser.add_argument("--out", type=str, default=str(_RESULTS_PATH), help="Output path")
    parser.add_argument("--inter-task-ms", type=int, default=150, help="Delay between tasks ms")
    args = parser.parse_args()

    if not (os.environ.get("CLOUDFLARE_API_TOKEN", "").strip() or os.environ.get("CF_AIG_TOKEN", "").strip()):
        print("ERROR: CLOUDFLARE_API_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    tasks = load_candidate_actions_v3()[:args.n]
    print(f"Loaded {len(tasks)} tasks from toolcall_blind_v3")

    baselines = [
        SingleModelLLMBaseline(),
        MajorityVoteLLMBaseline(),
        SelfConsistencyLLMBaseline(),
    ]

    artifact: dict = {
        "schema_version": "llm_baselines_v1",
        "model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "n_tasks": len(tasks),
        "benchmark": "toolcall_blind_v3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baselines": {},
    }

    for baseline in baselines:
        print(f"\nRunning {baseline.name} on {len(tasks)} tasks...")
        results = run_baseline(baseline, tasks, inter_task_ms=args.inter_task_ms)

        try:
            stats = compute_stats(results)
        except Exception as exc:
            print(f"  [WARN] could not compute stats: {exc}")
            stats = {}

        artifact["baselines"][baseline.name] = {
            "name": baseline.name,
            "n_tasks": len(results),
            "stats": stats,
            "results": results,
        }
        print(f"  Done. FAR={stats.get('false_accept_rate')}, acc={stats.get('accuracy')}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, ensure_ascii=False)
    print(f"\nArtifact saved: {out_path}")


if __name__ == "__main__":
    main()
