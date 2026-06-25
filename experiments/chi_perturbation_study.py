"""Per-item χ perturbation study — Claim 5 empirical validation.

Validates REMORA's thermodynamic susceptibility χ as a genuine fragility signal
by running two statistically independent oracle panels for every benchmark item
and measuring how much the order parameter η shifts between panels.

Protocol
--------
Round 1 η  ←  committed artifact results/thermodynamic_eval_results.json
              (original oracle calls, already cached)
Round 2 η  ←  fresh oracle calls made by this script, stored in a
              separate cache (.chi_perturbation_cache.json)

Per-item fragility  =  |η_round2 − η_round1|

Hypothesis (to be confirmed or refuted)
-----------------------------------------
  ordered    items  → low fragility  (η is stable across independent panels)
  critical   items  → moderate fragility
  disordered items  → high fragility  (η varies between panels)

If mean_fragility(ordered) < mean_fragility(disordered) and Spearman ρ(χ,
fragility) > 0, the thermodynamic phase classification captures genuine
consensus stability, not just one-shot agreement patterns.

Usage
-----
    GROQ_API_KEY=gsk_... python experiments/chi_perturbation_study.py
    python experiments/chi_perturbation_study.py --max-items 60
    python experiments/chi_perturbation_study.py --output results/chi_perturbation_study_results.json
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from remora.canonical import phi
from remora.correlation import CorrelationMatrix
from remora.genome import Genome
from remora.oracles.groq import GroqOracle
from remora.persistence import CachedOracle, Store
from remora.thermodynamics import predict_trust_before_iteration

from experiments.ablation_v2 import ORACLE_MODELS, build_eval_prompt
from experiments.thermodynamic_eval import (
    load_benchmark_module,
    hydrate_meta,
    mean_rho,
    parse_confidence,
)

ROUND1_RESULTS = ROOT / "results" / "thermodynamic_eval_results.json"


def spearman_rho(xs: list[float], ys: list[float]) -> float:
    """Compute Spearman rank correlation between xs and ys."""
    n = len(xs)
    if n < 3:
        return float("nan")

    def rank(seq):
        indexed = sorted(enumerate(seq), key=lambda t: t[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and indexed[j + 1][1] == indexed[j][1]:
                j += 1
            avg = (i + j + 2) / 2.0
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg
            i = j + 1
        return ranks

    rx = rank(xs)
    ry = rank(ys)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    den = math.sqrt(
        sum((rx[i] - mean_rx) ** 2 for i in range(n))
        * sum((ry[i] - mean_ry) ** 2 for i in range(n))
    )
    return num / den if den > 1e-12 else 0.0


def summarize_records(records: list[dict], expected_items: int) -> dict:
    by_phase: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_phase[record["phase"]].append(record)

    phase_summary = {}
    for phase in ("ordered", "critical", "disordered"):
        group = by_phase.get(phase, [])
        if not group:
            continue
        frags = [r["fragility"] for r in group]
        chis = [r["chi_round1"] for r in group]
        phase_summary[phase] = {
            "n": len(group),
            "mean_fragility": round(sum(frags) / len(frags), 4),
            "mean_chi": round(sum(chis) / len(chis), 4),
            "phase_stable_rate": round(
                sum(1 for r in group if r["phase_stable"]) / len(group), 4
            ),
        }

    all_chis = [r["chi_round1"] for r in records]
    all_frags = [r["fragility"] for r in records]
    rho_chi_frag = round(spearman_rho(all_chis, all_frags), 4) if len(records) >= 3 else float("nan")

    ord_frag = phase_summary.get("ordered", {}).get("mean_fragility", float("inf"))
    dis_frag = phase_summary.get("disordered", {}).get("mean_fragility", 0.0)
    fragility_ordered = bool(phase_summary) and ord_frag < dis_frag

    return {
        "n_items": len(records),
        "expected_items": expected_items,
        "spearman_rho_chi_fragility": rho_chi_frag,
        "fragility_hypothesis_holds": fragility_ordered,
        "phase_fragility_ordered_lt_disordered": fragility_ordered,
        "phase_summary": phase_summary,
        "overall_mean_fragility": round(sum(all_frags) / len(all_frags), 4) if all_frags else 0.0,
    }


def write_results(
    output_path: str,
    benchmark_module_name: str,
    round1_path: str,
    cache_path: str,
    expected_items: int,
    records: list[dict],
    *,
    partial: bool,
) -> dict:
    results = {
        "meta": {
            "experiment": "chi_perturbation_study",
            "round1_source": round1_path,
            "round2_cache": cache_path,
            "benchmark_module": benchmark_module_name,
            "n_items": len(records),
            "expected_items": expected_items,
            "is_partial": partial,
        },
        "summary": summarize_records(records, expected_items),
        "items": records,
    }

    out = pathlib.Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def select_phase_balanced_subset(items, meta, round1_map: dict[str, dict], per_phase_limit: int):
    selected_items = []
    selected_meta = []
    phase_counts = {"ordered": 0, "critical": 0, "disordered": 0}

    for item, item_meta in zip(items, meta):
        phase = round1_map[item.item_id]["phase"]
        if phase_counts.get(phase, 0) >= per_phase_limit:
            continue
        selected_items.append(item)
        selected_meta.append(item_meta)
        phase_counts[phase] = phase_counts.get(phase, 0) + 1

    return selected_items, selected_meta, phase_counts


def run(
    benchmark_module_name: str = "remora.benchmarks.extended_v2",
    round1_path: str = str(ROUND1_RESULTS),
    cache_path: str = ".chi_perturbation_cache.json",
    output_path: str = "results/chi_perturbation_study_results.json",
    max_items: int | None = None,
    checkpoint_every: int = 5,
    per_phase_limit: int | None = None,
) -> dict:
    benchmark_module = load_benchmark_module(benchmark_module_name)
    items = benchmark_module.load_all_extended_v2()
    if max_items is not None:
        items = items[:max_items]
    meta = hydrate_meta(items, benchmark_module)
    n = len(items)

    # ── load round-1 reference η and phase per item_id ─────────────────────
    round1 = json.loads(pathlib.Path(round1_path).read_text(encoding="utf-8"))
    round1_map = {it["item_id"]: it for it in round1["items"]}
    round1_ids = set(round1_map)

    # restrict to items that appear in round 1 (safe for subset runs)
    items = [it for it in items if it.item_id in round1_ids]
    meta = [m for m in meta if m["item_id"] in round1_ids]
    if per_phase_limit is not None:
        items, meta, phase_counts = select_phase_balanced_subset(items, meta, round1_map, per_phase_limit)
        print(f"\nPhase-balanced sample: {phase_counts}", flush=True)
    elif max_items is not None:
        items = items[:max_items]
        meta = meta[:max_items]
    n = len(items)
    print(f"\nItems to evaluate: {n}", flush=True)

    # ── set up fresh oracle calls ───────────────────────────────────────────
    store = Store(cache_path)
    oracles = [CachedOracle(GroqOracle(model), store) for model in ORACLE_MODELS]
    correlation = CorrelationMatrix(window_size=500)
    genome = Genome(enable_thermodynamic_control=True)

    records = []

    for idx, (item, item_meta) in enumerate(zip(items, meta), 1):
        prompt = build_eval_prompt(item)
        responses = [oracle.ask(prompt) for oracle in oracles]
        verdicts = [(r.provider, phi(r.extracted)) for r in responses]
        confidences = [parse_confidence(r.extracted.get("confidence", 0.5)) for r in responses]
        rho_bar = mean_rho(correlation, [p for p, _ in verdicts])

        thermo2 = predict_trust_before_iteration(
            pre_sweep_verdicts=[(p, v.fingerprint()) for p, v in verdicts],
            pre_sweep_confidences=confidences,
            rho_bar=rho_bar,
            lambda_coupling=genome.negation_weight,
        )
        correlation.observe(verdicts)

        ref = round1_map[item.item_id]
        eta1 = ref["order_parameter"]
        chi1 = ref["susceptibility"]
        phase = ref["phase"]
        eta2 = round(thermo2.order_parameter, 4)
        fragility = round(abs(eta2 - eta1), 4)

        records.append(
            {
                "item_id": item.item_id,
                "phase": phase,
                "eta_round1": eta1,
                "chi_round1": chi1,
                "eta_round2": eta2,
                "fragility": fragility,
                "phase_stable": phase == thermo2.phase,
                "phase_round2": thermo2.phase,
            }
        )
        if checkpoint_every > 0 and (idx % checkpoint_every == 0 or idx == n):
            write_results(
                output_path,
                benchmark_module_name,
                round1_path,
                cache_path,
                n,
                records,
                partial=idx != n,
            )
        if idx % 5 == 0 or idx == n:
            print(
                f"  [{idx:3d}/{n}] item={item.item_id[:30]:30s}  "
                f"η₁={eta1:.3f} η₂={eta2:.3f} frag={fragility:.3f} phase={phase}",
                flush=True,
            )

    return write_results(
        output_path,
        benchmark_module_name,
        round1_path,
        cache_path,
        n,
        records,
        partial=False,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark-module",
        default="remora.benchmarks.extended_v2",
        help="Benchmark module path.",
    )
    parser.add_argument(
        "--round1", default=str(ROUND1_RESULTS),
        help="Round-1 thermodynamic eval results JSON.",
    )
    parser.add_argument(
        "--cache", default=".chi_perturbation_cache.json",
        help="Cache file for round-2 oracle calls (use a fresh file for independence).",
    )
    parser.add_argument(
        "--output", default="results/chi_perturbation_study_results.json",
        help="Output path.",
    )
    parser.add_argument(
        "--max-items", type=int, default=None,
        help="Limit number of items for fast smoke tests.",
    )
    parser.add_argument(
        "--checkpoint-every", type=int, default=5,
        help="Write partial output after every N items.",
    )
    parser.add_argument(
        "--per-phase-limit", type=int, default=None,
        help="Select up to N items from each phase based on round-1 labels.",
    )
    args = parser.parse_args(argv)

    results = run(
        benchmark_module_name=args.benchmark_module,
        round1_path=args.round1,
        cache_path=args.cache,
        output_path=args.output,
        max_items=args.max_items,
        checkpoint_every=args.checkpoint_every,
        per_phase_limit=args.per_phase_limit,
    )

    s = results["summary"]
    ps = s["phase_summary"]
    print("\n── χ perturbation study summary ──────────────────────────────────────────")
    print(f"  N evaluated:                    {s['n_items']}")
    print(f"  Spearman ρ(χ, fragility):       {s['spearman_rho_chi_fragility']:+.4f}")
    print(f"  Overall mean fragility:         {s['overall_mean_fragility']:.4f}")
    print()
    for phase in ("ordered", "critical", "disordered"):
        if phase not in ps:
            continue
        p = ps[phase]
        print(
            f"  {phase:11s}: n={p['n']:3d}  mean_frag={p['mean_fragility']:.4f}  "
            f"mean_χ={p['mean_chi']:.4f}  phase_stable={p['phase_stable_rate']:.1%}"
        )
    print()
    hyp = "CONFIRMED" if s["fragility_hypothesis_holds"] else "NOT CONFIRMED"
    print(f"  Fragility hypothesis (ordered < disordered): {hyp}")
    print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
