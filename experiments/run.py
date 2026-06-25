# Author: Stian Skogbrott
# License: Apache-2.0
#!/usr/bin/env python3
"""
REMORA command-line runner.

Examples:
  python experiments/run.py                          # mock oracles, built-in questions
  python experiments/run.py --backend groq           # Groq (GROQ_API_KEY required)
  python experiments/run.py --backend ollama         # local Ollama models
  python experiments/run.py --q "Is the Sun a star?"
  python experiments/run.py --benchmark scifact --n 5
  python experiments/run.py --benchmark all --n 3 --backend groq
"""
from __future__ import annotations
import argparse
import json
import sys
import time

from remora.benchmarks import BenchmarkName, load_combined
from remora.oracles.factory import build_swarm, build_mock_swarm
from remora.genome import Genome
from remora.engine import Remora
from remora.persistence import CachedOracle, Store
from remora.scoring import score_batch


def make_oracles(backend: str, cache: bool):
    if backend == "mock":
        oracles = build_mock_swarm(3)
    else:
        oracles = build_swarm(backend)
    if cache:
        store = Store(".remora_cache.json")
        oracles = [CachedOracle(o, store) for o in oracles]
    return oracles


def run_single(question: str, backend: str, cache: bool, verbose: bool) -> None:
    print(f"\nQuestion: {question}")
    print(f"Backend:  {backend}")
    print("─" * 60)
    oracles = make_oracles(backend, cache)
    print(f"Oracles:  {[o.name for o in oracles]}\n")
    genome = Genome(enable_routing=True, enable_causal_stress_test=True, causal_stress_threshold=0.75)
    remora = Remora(oracles=oracles, genome=genome)
    t0 = time.perf_counter()
    state = remora.run(question)
    elapsed = time.perf_counter() - t0
    report = remora.report(state)
    print(f"Iterations:     {report['iterations']}")
    print(f"Oracle calls:   {report['oracle_calls']}")
    print(f"Open candidates:{report['open_candidates']}")
    print(f"Falsified:      {report['falsified_count']}")
    print(f"Converging:     {report['is_converging']}")
    print(f"Time:           {elapsed:.2f}s")
    if report["top_claims"]:
        print("\nTop candidates:")
        for claim, support in report["top_claims"]:
            print(f"  [{support:.3f}] {claim}")
    if report["decisions"]:
        print("\nDecisions:")
        for d in report["decisions"]: print(f"  {d}")
    if verbose:
        traj = report.get("trajectory", [])
        if traj:
            print("\nLyapunov trajectory:")
            for snap in traj:
                print(f"  t={snap['t']:2d}  V={snap['V']:.4f}  H={snap['H']:.4f}  D={snap['D']:.4f}")


def run_benchmark(bm_name: str, n: int, backend: str, cache: bool, verbose: bool, out: str) -> None:
    include = list(BenchmarkName) if bm_name == "all" else [BenchmarkName(bm_name)]
    items = load_combined(n_per_benchmark=n, include=include)
    print(f"\nBenchmark: {bm_name}  ({len(items)} items)")
    print(f"Backend:   {backend}")
    print("─" * 60)
    oracles = make_oracles(backend, cache)
    print(f"Oracles: {[o.name for o in oracles]}\n")
    genome = Genome(enable_routing=True, enable_causal_stress_test=True, causal_stress_threshold=0.75)
    remora = Remora(oracles=oracles, genome=genome)
    reports = []
    for i, item in enumerate(items):
        sys.stdout.write(f"\r[{i+1}/{len(items)}] {item.benchmark}: {item.question[:50]}...")
        sys.stdout.flush()
        state = remora.run(item.question, context=item.context)
        reports.append(remora.report(state))
    print()
    scoring = score_batch(items, reports)
    print(f"\nOverall accuracy: {scoring['overall']['accuracy']:.1%}")
    print(f"  ({scoring['overall']['correct']}/{scoring['overall']['n']} correct)")
    print("\nPer benchmark:")
    for bm, stats in scoring["per_benchmark"].items():
        print(f"  {bm:12s}: {stats['accuracy']:.1%} ({stats['correct']}/{stats['n']})")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"scoring": scoring, "reports": reports}, f, ensure_ascii=False, indent=2)
        print(f"\nResults saved: {out}")
    if verbose:
        print("\nDetails:")
        for d in scoring["details"]:
            status = "✓" if d["correct"] else "✗"
            print(f"  {status} [{d['benchmark']}] {d['item_id']:8s} pred={d['predicted']} exp={d['expected']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="REMORA — run with free AI oracles")
    parser.add_argument("--backend", default="mock",
        choices=["mock", "groq", "hf", "ollama", "gemini", "auto", "mixed"],
        help="Oracle backend (default: mock)")
    parser.add_argument("--q", "--question", default=None, help="Run a single question")
    parser.add_argument("--benchmark", default=None,
        choices=["hotpotqa", "scifact", "fever", "dce", "all"], help="Run a standard benchmark")
    parser.add_argument("--n", type=int, default=3, help="Items per benchmark (default: 3)")
    parser.add_argument("--no-cache", action="store_true", help="Disable disk cache")
    parser.add_argument("--out", default=None, help="Save results as JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show Lyapunov trajectory")
    args = parser.parse_args()
    cache = not args.no_cache
    if args.q:
        run_single(args.q, args.backend, cache, args.verbose)
    elif args.benchmark:
        run_benchmark(args.benchmark, args.n, args.backend, cache, args.verbose, args.out or "")
    else:
        for q in ["Is Earth's atmosphere primarily composed of oxygen?",
                  "Is the Sun a star?",
                  "Does vaccination cause autism?"]:
            run_single(q, args.backend, cache, args.verbose)
            print()


if __name__ == "__main__":
    main()
