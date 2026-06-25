# Author: Stian Skogbrott
# License: Apache-2.0
#!/usr/bin/env python3
"""
Grid-search calibration over Genome hyperparameters.

Runs a set of named Genome variants against the full 75-item dataset and
ranks them by overall accuracy. Uses the existing oracle cache so live API
calls are only needed for the first run.

Usage:
    GROQ_API_KEY=gsk_... python -m experiments.calibration
"""
from __future__ import annotations
import json
import math
import time
from pathlib import Path

from remora.benchmarks.loaders import BenchmarkItem
from remora.benchmarks.extended import load_all_extended
from remora.correlation import CorrelationMatrix
from remora.engine import Remora
from remora.genome import Genome, RouterMode
from remora.persistence import CachedOracle, Store
from remora.scoring import score_one

ORACLE_MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
]


def build_eval_prompt(item: BenchmarkItem) -> str:
    ctx = f"\nContext:\n{item.context}\n" if item.context else ""
    return (
        f"{ctx}Answer the question below. Return ONLY valid JSON.\n"
        'Format: {"claim": "<specific statement>", "answer": true|false|null, "confidence": 0.0-1.0}\n\n'
        f"Question: {item.question}\n\nJSON:"
    )


def run_variant(
    label: str,
    genome: Genome,
    items: list[BenchmarkItem],
    oracles: list,
) -> dict:
    correlation = CorrelationMatrix(window_size=500)
    engine = Remora(oracles=oracles, genome=genome, correlation=correlation)
    results = []
    for item in items:
        state = engine.run(item.question, context=item.context)
        report = engine.report(state)
        score = score_one(item, report)
        results.append({
            "item_id": item.item_id,
            "benchmark": item.benchmark,
            "correct": score.correct,
            "predicted": score.predicted,
            "expected": score.expected,
            "oracle_calls": report["oracle_calls"],
            "routed": any("router_gate" in d for d in report.get("decisions", [])),
        })

    by_bm: dict[str, list] = {}
    for r in results:
        by_bm.setdefault(r["benchmark"], []).append(r)

    def acc(rs): return sum(1 for r in rs if r["correct"]) / len(rs) if rs else 0.0
    def ci(rs):
        n = len(rs); k = sum(1 for r in rs if r["correct"])
        if n == 0: return (0.0, 0.0)
        p = k / n; z = 1.96; denom = 1 + z**2/n
        c = (p + z**2/(2*n)) / denom
        s = z * math.sqrt(p*(1-p)/n + z**2/(4*n**2)) / denom
        return round(max(0.0, c-s), 3), round(min(1.0, c+s), 3)

    overall_acc = acc(results)
    lo, hi = ci(results)
    n_routed = sum(1 for r in results if r.get("routed"))
    total_calls = sum(r["oracle_calls"] for r in results)

    per_bm = {bm: round(acc(rs), 4) for bm, rs in by_bm.items()}
    return {
        "label": label,
        "genome_summary": genome.summary(),
        "overall": round(overall_acc, 4),
        "correct": sum(1 for r in results if r["correct"]),
        "n": len(results),
        "ci_95": [lo, hi],
        "per_benchmark": per_bm,
        "n_routed": n_routed,
        "route_rate": round(n_routed / len(results), 3),
        "mean_oracle_calls": round(total_calls / len(results), 2),
    }


# ── Calibration grid ──────────────────────────────────────────────────────────
BASE = dict(max_iterations=4, max_subquestions=1, converged_threshold=0.72,
            entropy_abort_ratio=1.3, decomposition_strategy="simple",
            early_exit_on_convergence=True)

def G(**overrides) -> Genome:
    """Build a Genome by merging BASE with overrides."""
    return Genome(**{**BASE, **overrides})


VARIANTS: list[tuple[str, Genome]] = [
    # Reference points from ablation
    ("C_baseline",      G(negation_ratio=0.25, enable_routing=False)),
    ("D2_balanced",     G(negation_ratio=0.25, enable_routing=True,
                          router_mode=RouterMode.BALANCED)),
    ("D3_hybrid_80",    G(negation_ratio=0.25, enable_routing=True,
                          router_mode=RouterMode.HYBRID, router_confidence_min=0.80)),
    # Negation disabled + router variants
    ("E1_noneg_b",      G(negation_ratio=0.0, enable_routing=True,
                          router_mode=RouterMode.BALANCED)),
    ("E2_noneg_h80",    G(negation_ratio=0.0, enable_routing=True,
                          router_mode=RouterMode.HYBRID, router_confidence_min=0.80)),
    ("E3_noneg_h85",    G(negation_ratio=0.0, enable_routing=True,
                          router_mode=RouterMode.HYBRID, router_confidence_min=0.85)),
    ("E4_noneg_h90",    G(negation_ratio=0.0, enable_routing=True,
                          router_mode=RouterMode.HYBRID, router_confidence_min=0.90)),
    ("E5_noneg_h70",    G(negation_ratio=0.0, enable_routing=True,
                          router_mode=RouterMode.HYBRID, router_confidence_min=0.70)),
    ("E6_noneg_strict", G(negation_ratio=0.0, enable_routing=True,
                          router_mode=RouterMode.STRICT)),
    ("E7_noneg_full",   G(negation_ratio=0.0, enable_routing=False)),
    # Convergence threshold tuning
    ("E8_conv80_h85",   G(negation_ratio=0.0, converged_threshold=0.80,
                          enable_routing=True, router_mode=RouterMode.HYBRID,
                          router_confidence_min=0.85)),
    ("E9_conv85_h85",   G(negation_ratio=0.0, converged_threshold=0.85,
                          enable_routing=True, router_mode=RouterMode.HYBRID,
                          router_confidence_min=0.85)),
    # Fewer iterations
    ("E10_iter2_h85",   G(negation_ratio=0.0, max_iterations=2,
                          enable_routing=True, router_mode=RouterMode.HYBRID,
                          router_confidence_min=0.85)),
    ("E11_iter3_h85",   G(negation_ratio=0.0, max_iterations=3,
                          enable_routing=True, router_mode=RouterMode.HYBRID,
                          router_confidence_min=0.85)),
    # Low negation ratio (attenuated, not disabled)
    ("E12_neg10_h85",   G(negation_ratio=0.10, enable_routing=True,
                          router_mode=RouterMode.HYBRID, router_confidence_min=0.85)),
]


def main() -> None:
    print("\nLoading dataset...")
    items = load_all_extended()
    print(f"  {len(items)} items across {len(set(i.benchmark for i in items))} benchmarks")

    store = Store(".remora_cache_mixed.json")
    from remora.oracles.factory import build_mixed_swarm
    raw_oracles = build_mixed_swarm()
    oracles = [CachedOracle(o, store) for o in raw_oracles]

    print(f"\nRunning {len(VARIANTS)} calibration variants...\n")
    results = []
    for label, genome in VARIANTS:
        t0 = time.perf_counter()
        r = run_variant(label, genome, items, oracles)
        elapsed = time.perf_counter() - t0
        bm_str = "  ".join(f"{bm.replace('_ext','')}={v:.0%}"
                           for bm, v in sorted(r["per_benchmark"].items()))
        routed_note = f"  routed={r['n_routed']}/{r['n']}" if r["n_routed"] else ""
        print(f"  {label:22s}  {r['correct']}/{r['n']} = {r['overall']:.1%}"
              f"  CI [{r['ci_95'][0]:.1%},{r['ci_95'][1]:.1%}]"
              f"  [{bm_str}]"
              f"{routed_note}  ({elapsed:.0f}s)")
        results.append(r)

    # Sort by overall accuracy descending
    results.sort(key=lambda x: (-x["overall"], x["mean_oracle_calls"]))

    w = 70
    print("\n" + "="*w)
    print("CALIBRATION RANKING (best overall accuracy)")
    print("="*w)
    for i, r in enumerate(results, 1):
        marker = " <-- BEST" if i == 1 else (" <-- ties best" if r["overall"] == results[0]["overall"] else "")
        summary = r['genome_summary'][:45].encode("ascii", errors="replace").decode("ascii")
        print(f"  #{i:2d}  {r['label']:22s}  {r['correct']}/{r['n']} = {r['overall']:.1%}"
              f"  {summary}{marker}")

    Path("calibration_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nSaved: calibration_results.json")
    print("="*w)


if __name__ == "__main__":
    main()
