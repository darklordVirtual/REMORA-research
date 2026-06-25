#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Expanded ablation matrix for REMORA.

This script adds stronger controls beyond the default v2 ablation:
- Majority + confidence threshold (simple router competitor)
- REMORA without Lyapunov abort effect
- REMORA without rho diversity weighting (uniform weights)
- REMORA without negation mode
- REMORA with router (D2)
- Optional RAG-only and REMORA+RAG variants
"""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path

from remora.benchmarks.extended_v2 import load_all_extended_v2
from remora.canonical import phi
from remora.correlation import CorrelationMatrix
from remora.engine import Remora
from remora.genome import Genome, RouterMode
from remora.oracles.cloudflare_rag import CloudflareRAGOracle, DEFAULT_WORKER_URL
from remora.oracles.factory import build_swarm
from remora.persistence import CachedOracle, Store
from remora.scoring import score_one, _polarity_match

ROOT = Path(__file__).resolve().parent.parent


class UniformCorrelationMatrix(CorrelationMatrix):
    """Correlation matrix variant that always returns uniform oracle weights."""

    def diversity_weights(self, providers):
        n = len(providers)
        if n == 0:
            return {}
        return {p: 1.0 / n for p in providers}


def wilson_ci(n_correct: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = n_correct / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    spread = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, center - spread), min(1.0, center + spread)


def build_eval_prompt(item) -> str:
    ctx = f"\nContext:\n{item.context}\n" if item.context else ""
    return (
        f"{ctx}Answer the question below. Return ONLY valid JSON.\n"
        'Format: {"claim": "<specific statement>", "answer": true|false|null, "confidence": 0.0-1.0}\n\n'
        f"Question: {item.question}\n\nJSON:"
    )


def extract_meta(items):
    from remora.benchmarks import extended_v2 as ev2_mod

    meta_map = {it["item_id"]: it for it in ev2_mod._ITEMS}
    return [
        {
            "item_id": it.item_id,
            "benchmark": it.benchmark,
            "domain": meta_map.get(it.item_id, {}).get("domain", "unknown"),
            "is_adversarial": meta_map.get(it.item_id, {}).get("is_adversarial", False),
            "difficulty": meta_map.get(it.item_id, {}).get("difficulty", "medium"),
        }
        for it in items
    ]


def run_single(items, meta, oracle):
    rows = []
    for item, m in zip(items, meta):
        v = phi(oracle.ask(build_eval_prompt(item)).extracted)
        rows.append(
            {
                **m,
                "correct": _polarity_match(v.polarity, item.ground_truth),
                "predicted": v.polarity,
                "expected": item.ground_truth,
                "oracle_calls": 1,
                "routed": False,
            }
        )
    return rows


def run_majority(items, meta, oracles):
    rows = []
    corr = CorrelationMatrix(window_size=500)
    for item, m in zip(items, meta):
        prompt = build_eval_prompt(item)
        verdicts = [(o.name, phi(o.ask(prompt).extracted)) for o in oracles]
        corr.observe(verdicts)
        votes = defaultdict(int)
        for _, v in verdicts:
            votes[v.polarity] += 1
        winner = max(votes, key=votes.__getitem__)
        rows.append(
            {
                **m,
                "correct": _polarity_match(winner, item.ground_truth),
                "predicted": winner,
                "expected": item.ground_truth,
                "oracle_calls": len(oracles),
                "routed": False,
            }
        )
    return rows


def run_majority_conf(items, meta, oracles, strong_oracle, confidence_min=0.80):
    """Simple router competitor: majority if confident, else fallback to strong single oracle."""
    rows = []
    for item, m in zip(items, meta):
        prompt = build_eval_prompt(item)
        responses = [o.ask(prompt) for o in oracles]
        verdicts = [phi(r.extracted) for r in responses]

        votes = defaultdict(int)
        confs = []
        for resp, verdict in zip(responses, verdicts):
            votes[verdict.polarity] += 1
            raw = (resp.extracted or {}).get("confidence", 0.5)
            try:
                confs.append(float(raw))
            except (TypeError, ValueError):
                confs.append(0.5)

        n = len(verdicts)
        winner = max(votes, key=votes.__getitem__)
        majority_ok = votes[winner] > n / 2
        conf_ok = (sum(confs) / len(confs)) >= confidence_min if confs else False

        calls = len(oracles)
        routed = False
        if majority_ok and conf_ok:
            pred = winner
        else:
            routed = True
            sv = phi(strong_oracle.ask(prompt).extracted)
            pred = sv.polarity
            calls += 1

        rows.append(
            {
                **m,
                "correct": _polarity_match(pred, item.ground_truth),
                "predicted": pred,
                "expected": item.ground_truth,
                "oracle_calls": calls,
                "routed": routed,
            }
        )
    return rows


def run_remora(items, meta, oracles, genome, correlation=None):
    corr = correlation or CorrelationMatrix(window_size=500)
    engine = Remora(oracles=oracles, genome=genome, correlation=corr)
    rows, reports = [], []
    for item, m in zip(items, meta):
        state = engine.run(item.question, context=item.context)
        report = engine.report(state)
        s = score_one(item, report)
        rows.append(
            {
                **m,
                "correct": s.correct,
                "predicted": s.predicted,
                "expected": s.expected,
                "oracle_calls": report["oracle_calls"],
                "iterations": report["iterations"],
                "routed": any("router_gate" in d for d in report.get("decisions", [])),
                "final_V": report.get("final_V") or 0.0,
            }
        )
        reports.append(report)
    return rows, reports


def summarize(rows):
    n = len(rows)
    c = sum(1 for r in rows if r["correct"])
    lo, hi = wilson_ci(c, n)
    by_b = defaultdict(list)
    for r in rows:
        by_b[r["benchmark"]].append(r)
    return {
        "n": n,
        "correct": c,
        "accuracy": round(c / n, 4) if n else 0.0,
        "ci_95": [round(lo, 4), round(hi, 4)],
        "routed": sum(1 for r in rows if r.get("routed")),
        "per_source": {
            k: {
                "n": len(v),
                "correct": sum(1 for x in v if x["correct"]),
                "accuracy": round(sum(1 for x in v if x["correct"]) / len(v), 4),
            }
            for k, v in by_b.items()
        },
    }


def main():
    ap = argparse.ArgumentParser(description="Expanded REMORA ablation matrix")
    ap.add_argument("--backend", default="auto", help="auto|groq|gemini|ollama|mock")
    ap.add_argument("--max-items", type=int, default=0, help="limit items for quick smoke runs")
    ap.add_argument("--cache", default=".remora_cache.json", help="cache file")
    ap.add_argument("--include-rag", action="store_true", help="include optional RAG conditions")
    ap.add_argument("--router-confidence", type=float, default=0.80)
    args = ap.parse_args()

    items = load_all_extended_v2()
    if args.max_items and args.max_items > 0:
        items = items[: args.max_items]
    meta = extract_meta(items)

    raw_oracles = build_swarm(args.backend)
    if len(raw_oracles) < 2:
        raise SystemExit("Need at least two oracles for ablation matrix")

    store = Store(args.cache)
    oracles = [CachedOracle(o, store) for o in raw_oracles]
    strong = oracles[1] if len(oracles) >= 2 else oracles[0]

    base = dict(
        max_iterations=4,
        max_subquestions=1,
        converged_threshold=0.72,
        entropy_abort_ratio=1.3,
        negation_ratio=0.25,
        decomposition_strategy="simple",
        early_exit_on_convergence=True,
    )

    conditions = []
    conditions.append(("A_single", lambda: (run_single(items, meta, strong), None)))
    conditions.append(("B_majority", lambda: (run_majority(items, meta, oracles), None)))
    conditions.append(
        (
            "B_conf_router",
            lambda: (
                run_majority_conf(items, meta, oracles, strong, confidence_min=args.router_confidence),
                None,
            ),
        )
    )

    conditions.append(
        (
            "C_remora_full",
            lambda: run_remora(items, meta, oracles, Genome(**base, enable_routing=False)),
        )
    )
    def genome_no_lyapunov():
        g = dict(base)
        g["entropy_abort_ratio"] = 999.0
        g["early_exit_on_convergence"] = False
        return Genome(**g, enable_routing=False)
    conditions.append(
        (
            "C_no_lyapunov",
            lambda: run_remora(
                items,
                meta,
                oracles,
                genome_no_lyapunov(),
            ),
        )
    )
    conditions.append(
        (
            "C_no_rho",
            lambda: run_remora(
                items,
                meta,
                oracles,
                Genome(**base, enable_routing=False),
                correlation=UniformCorrelationMatrix(window_size=500),
            ),
        )
    )
    def genome_no_negation():
        g = dict(base)
        g["negation_ratio"] = 0.0
        return Genome(**g, enable_routing=False)
    conditions.append(
        (
            "C_no_negation",
            lambda: run_remora(items, meta, oracles, genome_no_negation()),
        )
    )
    conditions.append(
        (
            "D2_router",
            lambda: run_remora(
                items,
                meta,
                oracles,
                Genome(**base, enable_routing=True, router_mode=RouterMode.BALANCED),
            ),
        )
    )

    if args.include_rag:
        rag = CachedOracle(
            CloudflareRAGOracle(worker_url=DEFAULT_WORKER_URL, domain=None, top_k=5),
            store,
        )
        with_rag = oracles + [rag]
        conditions.append(
            (
                "D2_plus_rag",
                lambda: run_remora(
                    items,
                    meta,
                    with_rag,
                    Genome(**base, enable_routing=True, router_mode=RouterMode.BALANCED),
                ),
            )
        )
        conditions.append(("RAG_only", lambda: (run_single(items, meta, rag), None)))

    out = {
        "meta": {
            "n_items": len(items),
            "backend": args.backend,
            "oracles": [o.name for o in raw_oracles],
            "include_rag": args.include_rag,
            "router_confidence": args.router_confidence,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "conditions": {},
    }

    for name, fn in conditions:
        t0 = time.perf_counter()
        rows, reports = fn()
        elapsed = time.perf_counter() - t0
        s = summarize(rows)
        s["elapsed_s"] = round(elapsed, 2)
        out["conditions"][name] = {
            **s,
            "items": rows,
        }
        print(f"[{name:14s}] {s['correct']}/{s['n']} = {s['accuracy']:.1%}  ({elapsed:.1f}s)")

    out_path = ROOT / "results" / "ablation_matrix_results.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
