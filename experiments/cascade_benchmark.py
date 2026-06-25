#!/usr/bin/env python3
"""Cascade pipeline benchmark on the canonical N=302 dataset.

Compares the 4-stage cascade against the majority-vote baseline.
Mock mode uses deterministic oracles (no API keys needed).

Usage:
    python experiments/cascade_benchmark.py --mode mock --n 50
    python experiments/cascade_benchmark.py --mode live --n 302
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from remora.cascade.engine import CascadeEngine
from remora.genome import Genome, RouterMode
from remora.oracles.mock import MockOracle


def _load_benchmark() -> list[dict]:
    path = REPO_ROOT / "results" / "end_to_end_n500_v3.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items") or data.get("results") or []
    return list(items)[:302]


def _mock_engine(fast_threshold: float = 0.90) -> CascadeEngine:
    rng = random.Random(42)

    class _BiasedMock(MockOracle):
        def _call(self, prompt: str) -> tuple[str, float, float]:
            conf = rng.uniform(0.55, 0.98)
            answer = rng.choice(["Yes", "No", "Uncertain"])
            verdict = rng.choice(["supported", "challenged"])
            payload = {
                "answer": answer,
                "confidence": round(conf, 3),
                "verdict": verdict,
                "critique": "Mock evaluation.",
                "claim": f"The answer is {answer}.",
            }
            return json.dumps(payload), 0.0, 1.0

    oracles = [_BiasedMock("mock_a"), _BiasedMock("mock_b"), _BiasedMock("mock_c")]
    judge = _BiasedMock("mock_judge")
    genome = Genome(
        enable_routing=True,
        enable_thermodynamic_control=True,
        router_mode=RouterMode.BALANCED,
        max_iterations=2,
    )
    return CascadeEngine(
        consensus_oracles=oracles,
        judge_oracle=judge,
        fast_oracle=oracles[0],
        genome=genome,
        fast_threshold=fast_threshold,
        max_stages=4,
        budget_oracle_calls=15,
    )


def _live_engine(fast_threshold: float = 0.90) -> CascadeEngine:
    from remora.oracles.groq import GroqOracle
    from remora.oracles.openrouter import OpenRouterOracle

    fast = GroqOracle("llama-3.1-8b-instant")
    oracles = [
        GroqOracle("llama-3.1-8b-instant"),
        GroqOracle("llama-3.3-70b-versatile"),
        OpenRouterOracle("google/gemma-4-27b-it:free"),
    ]
    judge = OpenRouterOracle("mistralai/mistral-7b-instruct:free")
    genome = Genome(
        enable_routing=True,
        enable_thermodynamic_control=True,
        router_mode=RouterMode.BALANCED,
        max_iterations=2,
    )
    return CascadeEngine(
        consensus_oracles=oracles,
        judge_oracle=judge,
        fast_oracle=fast,
        genome=genome,
        fast_threshold=fast_threshold,
        max_stages=4,
        budget_oracle_calls=20,
    )


def run_benchmark(mode: str, n_items: int, fast_threshold: float, output: str) -> None:
    items = _load_benchmark()
    if not items:
        questions = [f"Sample question {i}?" for i in range(n_items)]
        ground_truths = [None] * n_items
    else:
        items = items[:n_items]
        questions = [it.get("question", it.get("q", "")) for it in items]
        ground_truths = [it.get("answer", it.get("ground_truth")) for it in items]

    engine = _mock_engine(fast_threshold) if mode == "mock" else _live_engine(fast_threshold)

    results = []
    stage_counts: dict[int, int] = {}
    verdict_counts: dict[str, int] = {}
    total_calls = 0
    correct = 0
    n_with_gt = 0

    print(f"Running cascade benchmark: mode={mode}, n={len(questions)}, fast_threshold={fast_threshold}")
    t0 = time.perf_counter()

    for i, (question, gt) in enumerate(zip(questions, ground_truths)):
        if not question:
            continue
        result = engine.run(question)
        stage_counts[result.stopped_at_stage] = stage_counts.get(result.stopped_at_stage, 0) + 1
        verdict_counts[result.final_verdict.value] = verdict_counts.get(result.final_verdict.value, 0) + 1
        total_calls += result.total_oracle_calls

        if gt is not None and result.is_accepted and result.answer:
            n_with_gt += 1
            ans_lower = str(result.answer).lower()
            gt_str = str(gt).lower()
            if gt_str in ans_lower or ans_lower in gt_str:
                correct += 1

        results.append({
            "question": question[:80],
            "verdict": result.final_verdict.value,
            "confidence": round(result.final_confidence, 4),
            "stopped_at_stage": result.stopped_at_stage,
            "oracle_calls": result.total_oracle_calls,
            "answer": result.answer,
            "critique": result.critique,
        })

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(questions)}] accept={verdict_counts.get('accept', 0)} "
                  f"abstain={verdict_counts.get('abstain', 0)} calls_so_far={total_calls}")

    elapsed = time.perf_counter() - t0
    n = len(results)
    accept_count = verdict_counts.get("accept", 0)
    abstain_count = verdict_counts.get("abstain", 0) + verdict_counts.get("escalate", 0)

    summary = {
        "mode": mode,
        "n_questions": n,
        "fast_threshold": fast_threshold,
        "accept_rate": round(accept_count / n, 4) if n else 0,
        "abstain_rate": round(abstain_count / n, 4) if n else 0,
        "avg_oracle_calls": round(total_calls / n, 2) if n else 0,
        "stage_distribution": {f"stage_{k}": v for k, v in stage_counts.items()},
        "verdict_distribution": verdict_counts,
        "accuracy_on_accepted": round(correct / n_with_gt, 4) if n_with_gt > 0 else None,
        "elapsed_seconds": round(elapsed, 2),
        "results": results,
    }

    out_path = Path(output)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n=== Cascade Benchmark Results ===")
    print(f"  N: {n}")
    print(f"  Accept rate:      {summary['accept_rate']:.1%}")
    print(f"  Abstain rate:     {summary['abstain_rate']:.1%}")
    print(f"  Avg oracle calls: {summary['avg_oracle_calls']}")
    print(f"  Stage dist:       {stage_counts}")
    if n_with_gt > 0:
        print(f"  Accuracy (accepted): {summary['accuracy_on_accepted']:.1%} over {n_with_gt} items")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Output: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cascade pipeline benchmark")
    parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--fast-threshold", type=float, default=0.90)
    parser.add_argument("--output", default="results/cascade_benchmark_results.json")
    args = parser.parse_args()
    run_benchmark(args.mode, args.n, args.fast_threshold, args.output)
