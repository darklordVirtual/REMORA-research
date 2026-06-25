# Author: Stian Skogbrott
# License: Apache-2.0
#!/usr/bin/env python3
"""
Extended ablation study — REMORA v3.0 evaluation on the 125-item benchmark v2.

Conditions evaluated
--------------------
    A   Single oracle (llama-3.3-70b-versatile)
    B   Unweighted majority (3 oracles, 1 sweep)
    C   Full REMORA (diversity weighting + Lyapunov, no routing)
    D1  REMORA + Router STRICT (unanimity required)
    D2  REMORA + Router BALANCED (majority sufficient)
    D3  REMORA + Router HYBRID  (majority + confidence >= 0.80)

Per-source breakdown
--------------------
    truthfulqa       — external benchmark (Lin et al., 2022); generalisation proxy
    remora_curated   — original 75-item validated set
    adversarial_curated — popular belief contradicts ground truth

Metrics reported
----------------
    accuracy    — standard binary correctness
    ETR         — Effective Truth Rate (correct + evidence-backed + oracle-consistent)
    95 % CI     — Wilson score interval
    per_source  — breakdown by benchmark origin
    per_domain  — breakdown by knowledge domain
    adversarial — subset accuracy on adversarial items only

Usage
-----
    GROQ_API_KEY=gsk_... python -m experiments.ablation_v2
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import time
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from remora.benchmarks.loaders import BenchmarkItem
from remora.canonical import phi
from remora.correlation import CorrelationMatrix
from remora.engine import Remora
from remora.genome import Genome, RouterMode
from remora.oracles.groq import GroqOracle
from remora.persistence import CachedOracle, Store
from remora.scoring import score_one, _polarity_match, effective_truth_rate

ORACLE_MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
]
STRONG_SINGLE = "llama-3.3-70b-versatile"


def load_benchmark(module_name: str) -> tuple[list[BenchmarkItem], dict[str, dict], str]:
    module = importlib.import_module(module_name)
    loader = getattr(module, "load_all_extended_v2", None)
    if loader is None:
        for attr in dir(module):
            if attr.startswith("load_all_"):
                candidate = getattr(module, attr)
                if callable(candidate):
                    loader = candidate
                    break
    if loader is None:
        raise ValueError(f"No load_all_* benchmark loader found in {module_name}")

    items = loader()
    item_meta = {it["item_id"]: it for it in getattr(module, "_ITEMS", [])}
    return items, item_meta, loader.__name__


def build_eval_prompt(item: BenchmarkItem) -> str:
    ctx = f"\nContext:\n{item.context}\n" if item.context else ""
    return (
        f"{ctx}Answer the question below. Return ONLY valid JSON.\n"
        'Format: {"claim": "<specific statement>", "answer": true|false|null, "confidence": 0.0-1.0}\n\n'
        f"Question: {item.question}\n\nJSON:"
    )


def wilson_ci(n_correct: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0: return 0.0, 0.0
    p = n_correct / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    spread = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return round(max(0.0, center - spread), 4), round(min(1.0, center + spread), 4)


def accuracy(results: list[dict]) -> float:
    return sum(1 for r in results if r["correct"]) / len(results) if results else 0.0


def per_source(results: list[dict]) -> dict:
    by: dict[str, list] = defaultdict(list)
    for r in results:
        by[r["benchmark"]].append(r)
    return {
        bm: {
            "n": len(rs),
            "correct": sum(1 for r in rs if r["correct"]),
            "accuracy": round(accuracy(rs), 4),
        }
        for bm, rs in by.items()
    }


def per_domain(results: list[dict]) -> dict:
    by: dict[str, list] = defaultdict(list)
    for r in results:
        by[r.get("domain", "unknown")].append(r)
    return {
        d: {
            "n": len(rs),
            "correct": sum(1 for r in rs if r["correct"]),
            "accuracy": round(accuracy(rs), 4),
        }
        for d, rs in by.items()
    }


def adversarial_accuracy(results: list[dict]) -> dict:
    adv = [r for r in results if r.get("is_adversarial")]
    if not adv:
        return {"n": 0, "accuracy": None}
    n_c = sum(1 for r in adv if r["correct"])
    return {"n": len(adv), "correct": n_c, "accuracy": round(n_c / len(adv), 4)}


# ── Condition runners ─────────────────────────────────────────────────────────

def run_single_oracle(
    items: list[BenchmarkItem],
    meta: list[dict],
    oracle,
) -> list[dict]:
    results = []
    for item, m in zip(items, meta):
        resp = oracle.ask(build_eval_prompt(item))
        verdict = phi(resp.extracted)
        results.append({
            **m,
            "correct": _polarity_match(verdict.polarity, item.ground_truth),
            "predicted": verdict.polarity,
            "expected": item.ground_truth,
            "oracle_calls": 1,
        })
    return results


def run_majority(
    items: list[BenchmarkItem],
    meta: list[dict],
    oracles: list,
) -> list[dict]:
    results = []
    correlation = CorrelationMatrix(window_size=500)
    for item, m in zip(items, meta):
        prompt = build_eval_prompt(item)
        verdicts = [(o.name, phi(o.ask(prompt).extracted)) for o in oracles]
        correlation.observe(verdicts)
        votes: dict = defaultdict(float)
        for _, v in verdicts:
            votes[v.polarity] += 1
        winner = max(votes, key=votes.__getitem__)
        results.append({
            **m,
            "correct": _polarity_match(winner, item.ground_truth),
            "predicted": winner,
            "expected": item.ground_truth,
            "oracle_calls": len(oracles),
        })
    return results


def run_remora(
    items: list[BenchmarkItem],
    meta: list[dict],
    oracles: list,
    genome: Genome,
) -> tuple[list[dict], list[dict]]:
    """Returns (results, reports) — reports used for ETR."""
    correlation = CorrelationMatrix(window_size=500)
    engine = Remora(oracles=oracles, genome=genome, correlation=correlation)
    results, reports = [], []
    for item, m in zip(items, meta):
        state = engine.run(item.question, context=item.context)
        report = engine.report(state)
        score = score_one(item, report)
        results.append({
            **m,
            "correct": score.correct,
            "predicted": score.predicted,
            "expected": score.expected,
            "oracle_calls": report["oracle_calls"],
            "iterations": report["iterations"],
            "routed": any("router_gate" in d for d in report.get("decisions", [])),
            "final_V": report.get("final_V") or 0.0,
        })
        reports.append(report)
    return results, reports


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Run REMORA ablation on a benchmark module")
    parser.add_argument(
        "--benchmark-module",
        default="remora.benchmarks.extended_v2",
        help="Import path for the benchmark module exposing load_all_* and _ITEMS",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "results" / "ablation_v2_results.json"),
        help="Path to the JSON results file",
    )
    args = parser.parse_args()

    print(f"\nLoading benchmark module {args.benchmark_module}...")
    all_items, meta_map, loader_name = load_benchmark(args.benchmark_module)
    print(f"  Total items: {len(all_items)}")

    # Build metadata list (source, domain, is_adversarial) from the benchmark module.
    # The BenchmarkItem only has item_id, question, ground_truth, benchmark, context.
    meta = [
        {
            "item_id": it.item_id,
            "benchmark": it.benchmark,
            "domain": meta_map.get(it.item_id, {}).get("domain", "unknown"),
            "is_adversarial": meta_map.get(it.item_id, {}).get("is_adversarial", False),
            "difficulty": meta_map.get(it.item_id, {}).get("difficulty", "medium"),
        }
        for it in all_items
    ]

    per_bm = defaultdict(int)
    for m in meta: per_bm[m["benchmark"]] += 1
    for bm, n in sorted(per_bm.items()): print(f"  {bm:25s}: {n}")

    # Reuse existing cache — 75-item responses already stored, only new items cost API calls
    store = Store(".remora_cache.json")
    raw_oracles = [GroqOracle(m) for m in ORACLE_MODELS]
    cached = [CachedOracle(o, store) for o in raw_oracles]
    single = CachedOracle(GroqOracle(STRONG_SINGLE), store)

    base_genome = dict(
        max_iterations=4, max_subquestions=1, converged_threshold=0.72,
        entropy_abort_ratio=1.3, negation_ratio=0.25,
        decomposition_strategy="simple", early_exit_on_convergence=True,
    )

    conditions = {
        "A_single":     (None, None),
        "B_majority":   (None, None),
        "C_remora":     (Genome(**base_genome, enable_routing=False), None),
        "D1_strict":    (Genome(**base_genome, enable_routing=True,
                                router_mode=RouterMode.STRICT), None),
        "D2_balanced":  (Genome(**base_genome, enable_routing=True,
                                router_mode=RouterMode.BALANCED), None),
        "D3_hybrid":    (Genome(**base_genome, enable_routing=True,
                                router_mode=RouterMode.HYBRID,
                                router_confidence_min=0.80), None),
    }

    results_all: dict[str, list[dict]] = {}
    reports_all: dict[str, list[dict]] = {}

    for cond, (genome, _) in conditions.items():
        t0 = time.perf_counter()
        if cond == "A_single":
            res = run_single_oracle(all_items, meta, single)
            rep = [{}] * len(all_items)
        elif cond == "B_majority":
            res = run_majority(all_items, meta, cached)
            rep = [{}] * len(all_items)
        else:
            res, rep = run_remora(all_items, meta, cached, genome)
        elapsed = time.perf_counter() - t0

        n = len(res)
        n_c = sum(1 for r in res if r["correct"])
        lo, hi = wilson_ci(n_c, n)
        n_routed = sum(1 for r in res if r.get("routed"))
        route_note = f"  routed={n_routed}/{n}" if n_routed else ""
        print(f"\n[{cond:14s}]  {n_c}/{n} = {n_c/n:.1%}  CI [{lo:.1%},{hi:.1%}]  ({elapsed:.0f}s){route_note}", flush=True)

        results_all[cond] = res
        reports_all[cond] = rep

    # ── ETR analysis ──────────────────────────────────────────────────────────
    print("\n── Effective Truth Rate ──────────────────────────────────────────────────")
    from remora.scoring import ScoreResult

    def to_score_results(items, res_list) -> list[ScoreResult]:
        out = []
        for it, r in zip(items, res_list):
            out.append(ScoreResult(
                item_id=it.item_id, benchmark=it.benchmark,
                correct=r["correct"],
                confidence=r.get("final_V", 0.0),
                predicted=r["predicted"], expected=r["expected"],
                method="polarity",
            ))
        return out

    etr_results = {}
    for cond in ("C_remora", "D2_balanced", "D3_hybrid"):
        srs = to_score_results(all_items, results_all[cond])
        etr = effective_truth_rate(all_items, reports_all[cond], score_results=srs)
        etr_results[cond] = etr
        print(f"  {cond:14s}:  accuracy={etr['accuracy']:.1%}  ETR={etr['etr_rate']:.1%}"
              f"  (evidence_gap={etr['n_evidence_gap']}  consensus_gap={etr['n_consensus_gap']})")

    # ── Per-source breakdown ──────────────────────────────────────────────────
    print("\n── Per-source accuracy ───────────────────────────────────────────────────")
    for cond in ("A_single", "B_majority", "D2_balanced"):
        ps = per_source(results_all[cond])
        print(f"  {cond:14s}:  ", end="")
        for src, s in sorted(ps.items()):
            print(f"{src[:8]}={s['accuracy']:.0%}({s['correct']}/{s['n']})  ", end="")
        print()

    # ── Adversarial breakdown ─────────────────────────────────────────────────
    print("\n── Adversarial subset ────────────────────────────────────────────────────")
    for cond in ("A_single", "B_majority", "D2_balanced", "D3_hybrid"):
        adv = adversarial_accuracy(results_all[cond])
        if adv["n"] > 0:
            print(f"  {cond:14s}:  {adv['correct']}/{adv['n']} = {adv['accuracy']:.0%}")

    # ── Save ──────────────────────────────────────────────────────────────────
    out = {
        "meta": {
            "benchmark_module": args.benchmark_module,
            "benchmark_loader": loader_name,
            "n_items": len(all_items),
            "per_benchmark": dict(per_bm),
            "oracles": ORACLE_MODELS,
            "single_oracle": STRONG_SINGLE,
        },
        "conditions": {
            cond: {
                "n": len(res),
                "correct": sum(1 for r in res if r["correct"]),
                "accuracy": round(accuracy(res), 4),
                "ci_95": list(wilson_ci(sum(1 for r in res if r["correct"]), len(res))),
                "per_source": per_source(res),
                "per_domain": per_domain(res),
                "adversarial": adversarial_accuracy(res),
                "etr": {k: v for k, v in etr_results.get(cond, {}).items() if k != "details"},
                # Per-item details for calibration curves and fine-grained analysis
                "items": [
                    {
                        "item_id": r["item_id"],
                        "benchmark": r["benchmark"],
                        "domain": r.get("domain", "?"),
                        "correct": r["correct"],
                        "predicted": r["predicted"],
                        "expected": r["expected"],
                        "is_adversarial": r.get("is_adversarial", False),
                        "difficulty": r.get("difficulty", "medium"),
                        "oracle_calls": r.get("oracle_calls", 0),
                        "routed": r.get("routed", False),
                        "final_V": r.get("final_V", 0.0),
                    }
                    for r in res
                ],
            }
            for cond, res in results_all.items()
        },
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
