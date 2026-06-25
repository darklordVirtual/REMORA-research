# Author: Stian Skogbrott
# License: Apache-2.0
#!/usr/bin/env python3
"""
Cloudflare-focused ablation study for REMORA.

Evaluates the existing Cloudflare Workers AI / Vectorize stack as both:
  A) a strong single evidence-grounded oracle baseline, and
  B) a 3-oracle Cloudflare swarm routed through REMORA.

Conditions evaluated
--------------------
    A   Single Cloudflare oracle (all-domain, dual-consensus, multilingual)
    B   Unweighted majority over Cloudflare swarm
    C   Full REMORA over Cloudflare swarm
    D1  REMORA + Router STRICT
    D2  REMORA + Router BALANCED
    D3  REMORA + Router HYBRID

The output schema intentionally mirrors experiments/ablation_v2.py so the
results can be compared directly with the current mixed-swarm benchmark.

Usage
-----
    CLOUDFLARE_WORKER_URL=https://... \
    CLOUDFLARE_ORACLE_SECRET=... \
    PYTHONPATH=/workspaces/REMORA python experiments/ablation_cloudflare.py
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from remora.benchmarks.extended_v2 import load_all_extended_v2
from remora.benchmarks.loaders import BenchmarkItem
from remora.canonical import phi
from remora.correlation import CorrelationMatrix
from remora.engine import Remora
from remora.genome import Genome, RouterMode
from remora.oracles.cloudflare_rag import CloudflareRAGOracle
from remora.oracles.factory import build_cloudflare_swarm
from remora.persistence import CachedOracle, Store
from remora.scoring import _polarity_match, effective_truth_rate, score_one, ScoreResult


def build_eval_prompt(item: BenchmarkItem) -> str:
    ctx = f"\nContext:\n{item.context}\n" if item.context else ""
    return (
        f"{ctx}Answer the question below. Return ONLY valid JSON.\n"
        'Format: {"claim": "<specific statement>", "answer": true|false|null, "confidence": 0.0-1.0}\n\n'
        f"Question: {item.question}\n\nJSON:"
    )


def wilson_ci(n_correct: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
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


def run_single_oracle(items: list[BenchmarkItem], meta: list[dict], oracle) -> list[dict]:
    results = []
    for item, m in zip(items, meta):
        resp = oracle.ask(build_eval_prompt(item))
        verdict = phi(resp.extracted)
        results.append(
            {
                **m,
                "correct": _polarity_match(verdict.polarity, item.ground_truth),
                "predicted": verdict.polarity,
                "expected": item.ground_truth,
                "oracle_calls": 1,
            }
        )
    return results


def run_majority(items: list[BenchmarkItem], meta: list[dict], oracles: list) -> list[dict]:
    results = []
    correlation = CorrelationMatrix(window_size=500)
    for item, m in zip(items, meta):
        prompt = build_eval_prompt(item)
        verdicts = [(o.name, phi(o.ask(prompt).extracted)) for o in oracles]
        correlation.observe(verdicts)
        votes: dict = defaultdict(float)
        for _, verdict in verdicts:
            votes[verdict.polarity] += 1
        winner = max(votes, key=votes.__getitem__)
        results.append(
            {
                **m,
                "correct": _polarity_match(winner, item.ground_truth),
                "predicted": winner,
                "expected": item.ground_truth,
                "oracle_calls": len(oracles),
            }
        )
    return results


def run_remora(items: list[BenchmarkItem], meta: list[dict], oracles: list, genome: Genome) -> tuple[list[dict], list[dict]]:
    correlation = CorrelationMatrix(window_size=500)
    engine = Remora(oracles=oracles, genome=genome, correlation=correlation)
    results, reports = [], []
    for item, m in zip(items, meta):
        state = engine.run(item.question, context=item.context)
        report = engine.report(state)
        score = score_one(item, report)
        results.append(
            {
                **m,
                "correct": score.correct,
                "predicted": score.predicted,
                "expected": score.expected,
                "oracle_calls": report["oracle_calls"],
                "iterations": report["iterations"],
                "routed": any("router_gate" in d for d in report.get("decisions", [])),
                "final_V": report.get("final_V") or 0.0,
            }
        )
        reports.append(report)
    return results, reports


def make_genome(**overrides) -> Genome:
    params = {
        "max_iterations": 4,
        "max_subquestions": 1,
        "converged_threshold": 0.72,
        "entropy_abort_ratio": 1.3,
        "negation_ratio": 0.25,
        "decomposition_strategy": "simple",
        "early_exit_on_convergence": True,
    }
    params.update(overrides)
    return Genome(**params)


def apply_subset(
    all_items: list[BenchmarkItem],
    meta: list[dict],
    per_benchmark_limit: int | None,
    max_items: int | None,
) -> tuple[list[BenchmarkItem], list[dict]]:
    if per_benchmark_limit is None and max_items is None:
        return all_items, meta

    selected_items: list[BenchmarkItem] = []
    selected_meta: list[dict] = []

    if per_benchmark_limit is not None:
        seen_per_benchmark: dict[str, int] = defaultdict(int)
        for item, item_meta in zip(all_items, meta):
            benchmark = item_meta["benchmark"]
            if seen_per_benchmark[benchmark] >= per_benchmark_limit:
                continue
            selected_items.append(item)
            selected_meta.append(item_meta)
            seen_per_benchmark[benchmark] += 1
    else:
        selected_items = list(all_items)
        selected_meta = list(meta)

    if max_items is not None:
        selected_items = selected_items[:max_items]
        selected_meta = selected_meta[:max_items]

    return selected_items, selected_meta


def parse_conditions(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def write_output(
    output_path: Path,
    per_bm: dict[str, int],
    strong_single,
    cached_swarm: list,
    results_all: dict[str, list[dict]],
    etr_results: dict[str, dict],
    worker_url: str,
    secret_present: bool,
) -> None:
    out = {
        "meta": {
            "n_items": sum(per_bm.values()),
            "per_benchmark": dict(per_bm),
            "single_oracle": strong_single.name,
            "oracles": [o.name for o in cached_swarm],
            "backend": "cloudflare",
            "worker_url": worker_url,
            "authenticated": secret_present,
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
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Cloudflare-specific REMORA ablation")
    parser.add_argument("--per-benchmark-limit", type=int, default=None,
                        help="Limit items per benchmark source for a faster stratified smoke run")
    parser.add_argument("--max-items", type=int, default=None,
                        help="Hard cap on total number of benchmark items after filtering")
    parser.add_argument("--conditions", type=str, default=None,
                        help="Comma-separated subset of conditions to run (e.g. A_single,D2_balanced)")
    parser.add_argument("--resume-from", type=str, default=None,
                        help="Existing results JSON to resume from; completed conditions are skipped")
    parser.add_argument("--require-secret", action="store_true",
                        help="Fail fast unless CLOUDFLARE_ORACLE_SECRET is present")
    parser.add_argument("--output", type=str,
                        default=str(ROOT / "results" / "ablation_cloudflare_results.json"),
                        help="Path to output JSON results")
    args = parser.parse_args()

    selected_conditions = parse_conditions(args.conditions)
    allowed_conditions = {
        "A_single",
        "B_majority",
        "C_remora",
        "D1_strict",
        "D2_balanced",
        "D3_hybrid",
    }
    if selected_conditions:
        unknown = [cond for cond in selected_conditions if cond not in allowed_conditions]
        if unknown:
            raise SystemExit(f"Unknown condition(s): {', '.join(unknown)}")

    print("\nLoading extended benchmark v2 for Cloudflare ablation...")
    all_items = load_all_extended_v2()
    print(f"  Total items: {len(all_items)}")

    from remora.benchmarks import extended_v2 as ev2_mod

    meta_map = {it["item_id"]: it for it in ev2_mod._ITEMS}
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

    all_items, meta = apply_subset(
        all_items,
        meta,
        per_benchmark_limit=args.per_benchmark_limit,
        max_items=args.max_items,
    )

    if args.per_benchmark_limit is not None or args.max_items is not None:
        print(f"  Filtered subset size: {len(all_items)}")

    per_bm = defaultdict(int)
    for m in meta:
        per_bm[m["benchmark"]] += 1
    for bm, n in sorted(per_bm.items()):
        print(f"  {bm:25s}: {n}")

    worker_url = os.environ.get("CLOUDFLARE_WORKER_URL", CloudflareRAGOracle()._worker_url)
    secret = os.environ.get("CLOUDFLARE_ORACLE_SECRET")
    if args.require_secret and not secret:
        raise SystemExit("CLOUDFLARE_ORACLE_SECRET is required for this run")

    print(f"\nUsing Cloudflare worker: {worker_url}")
    print(f"Authenticated secret present: {'yes' if secret else 'no'}")

    store = Store(".remora_cache_cloudflare.json")
    raw_swarm = build_cloudflare_swarm(worker_url=worker_url, secret=secret)
    cached_swarm = [CachedOracle(oracle, store) for oracle in raw_swarm]
    strong_single = CachedOracle(
        CloudflareRAGOracle(
            worker_url=worker_url,
            domain=None,
            secret=secret,
            complexity="high",
            rerank=True,
            dual_consensus=True,
            multilingual=True,
        ),
        store,
    )

    conditions = {
        "A_single": (None, None),
        "B_majority": (None, None),
        "C_remora": (make_genome(enable_routing=False), None),
        "D1_strict": (make_genome(enable_routing=True, router_mode=RouterMode.STRICT), None),
        "D2_balanced": (make_genome(enable_routing=True, router_mode=RouterMode.BALANCED), None),
        "D3_hybrid": (
            make_genome(
                enable_routing=True,
                router_mode=RouterMode.HYBRID,
                router_confidence_min=0.80,
            ),
            None,
        ),
    }

    condition_order = list(conditions)
    if selected_conditions:
        condition_order = [cond for cond in condition_order if cond in selected_conditions]

    results_all: dict[str, list[dict]] = {}
    reports_all: dict[str, list[dict]] = {}
    etr_results: dict[str, dict] = {}

    out_path = Path(args.output)
    resume_path = Path(args.resume_from) if args.resume_from else out_path
    if resume_path.exists():
        try:
            existing = json.loads(resume_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Failed to parse resume file {resume_path}: {exc}") from exc
        existing_conditions = existing.get("conditions", {})
        for cond in condition_order:
            cond_data = existing_conditions.get(cond)
            if not cond_data:
                continue
            items_data = cond_data.get("items")
            if not items_data:
                continue
            results_all[cond] = items_data
            reports_all[cond] = [{}] * len(items_data)
            if cond_data.get("etr"):
                etr_results[cond] = cond_data["etr"]
        if results_all:
            print(f"\nResuming from {resume_path}; existing conditions: {', '.join(sorted(results_all))}")

    for cond in condition_order:
        if cond in results_all:
            print(f"\n[{cond:14s}]  skipped (already present in resume file)", flush=True)
            continue

        genome, _ = conditions[cond]
        t0 = time.perf_counter()
        if cond == "A_single":
            res = run_single_oracle(all_items, meta, strong_single)
            rep = [{}] * len(all_items)
        elif cond == "B_majority":
            res = run_majority(all_items, meta, cached_swarm)
            rep = [{}] * len(all_items)
        else:
            res, rep = run_remora(all_items, meta, cached_swarm, genome)
        elapsed = time.perf_counter() - t0

        n = len(res)
        n_c = sum(1 for r in res if r["correct"])
        lo, hi = wilson_ci(n_c, n)
        n_routed = sum(1 for r in res if r.get("routed"))
        route_note = f"  routed={n_routed}/{n}" if n_routed else ""
        print(f"\n[{cond:14s}]  {n_c}/{n} = {n_c/n:.1%}  CI [{lo:.1%},{hi:.1%}]  ({elapsed:.0f}s){route_note}", flush=True)

        results_all[cond] = res
        reports_all[cond] = rep

        if cond in ("C_remora", "D2_balanced", "D3_hybrid"):
            srs = [
                ScoreResult(
                    item_id=it.item_id,
                    benchmark=it.benchmark,
                    correct=r["correct"],
                    confidence=r.get("final_V", 0.0),
                    predicted=r["predicted"],
                    expected=r["expected"],
                    method="polarity",
                )
                for it, r in zip(all_items, results_all[cond])
            ]
            etr_results[cond] = effective_truth_rate(all_items, reports_all[cond], score_results=srs)

        write_output(
            output_path=out_path,
            per_bm=per_bm,
            strong_single=strong_single,
            cached_swarm=cached_swarm,
            results_all=results_all,
            etr_results=etr_results,
            worker_url=worker_url,
            secret_present=bool(secret),
        )

    print("\n── Effective Truth Rate (Cloudflare) ─────────────────────────────────────")
    etr_results = {}
    for cond in ("C_remora", "D2_balanced", "D3_hybrid"):
        if cond not in results_all:
            continue
        srs = [
            ScoreResult(
                item_id=it.item_id,
                benchmark=it.benchmark,
                correct=r["correct"],
                confidence=r.get("final_V", 0.0),
                predicted=r["predicted"],
                expected=r["expected"],
                method="polarity",
            )
            for it, r in zip(all_items, results_all[cond])
        ]
        etr = effective_truth_rate(all_items, reports_all[cond], score_results=srs)
        etr_results[cond] = etr
        print(
            f"  {cond:14s}:  accuracy={etr['accuracy']:.1%}  ETR={etr['etr_rate']:.1%}"
            f"  (evidence_gap={etr['n_evidence_gap']}  consensus_gap={etr['n_consensus_gap']})"
        )

    print("\n── Per-source accuracy (Cloudflare) ──────────────────────────────────────")
    for cond in ("A_single", "B_majority", "D2_balanced"):
        if cond not in results_all:
            continue
        ps = per_source(results_all[cond])
        print(f"  {cond:14s}:  ", end="")
        for src, stats in sorted(ps.items()):
            print(f"{src[:16]}={stats['accuracy']:.0%}({stats['correct']}/{stats['n']})  ", end="")
        print()

    print("\n── Adversarial subset (Cloudflare) ───────────────────────────────────────")
    for cond in ("A_single", "B_majority", "D2_balanced", "D3_hybrid"):
        if cond not in results_all:
            continue
        adv = adversarial_accuracy(results_all[cond])
        if adv["n"] > 0:
            print(f"  {cond:14s}:  {adv['correct']}/{adv['n']} = {adv['accuracy']:.0%}")

    write_output(
        output_path=out_path,
        per_bm=per_bm,
        strong_single=strong_single,
        cached_swarm=cached_swarm,
        results_all=results_all,
        etr_results=etr_results,
        worker_url=worker_url,
        secret_present=bool(secret),
    )
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
