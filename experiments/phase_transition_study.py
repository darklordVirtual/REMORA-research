# Author: Stian Skogbrott
# License: Apache-2.0
#!/usr/bin/env python3
"""Experiment 3 — empirical phase-transition study for REMORA.

This script is the benchmark-layer vehicle for the v4 research program. It
replays oracle pre-sweeps over a benchmark, estimates thermodynamic observables
before full iteration, and summarizes whether consensus quality changes sharply
across difficulty / temperature bands.

The design goal is empirical first:
- estimate effective temperature T from pre-sweep observables,
- measure order parameter eta across temperature bins,
- compare majority and D2 outcomes by band,
- and identify whether a transition-like drop emerges in harder regions.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from remora.canonical import phi
from remora.correlation import CorrelationMatrix
from remora.genome import Genome
from remora.oracles.groq import GroqOracle
from remora.persistence import CachedOracle, Store
from remora.phase_controller import phase_decision
from remora.thermodynamics import load_thermodynamic_calibration, predict_trust_before_iteration

from experiments.ablation_v2 import ORACLE_MODELS, build_eval_prompt, load_benchmark


def load_meta(items, meta_map):
    return [
        {
            "item_id": item.item_id,
            "benchmark": item.benchmark,
            "domain": meta_map.get(item.item_id, {}).get("domain", "unknown"),
            "difficulty": meta_map.get(item.item_id, {}).get("difficulty", "medium"),
            "is_adversarial": meta_map.get(item.item_id, {}).get("is_adversarial", False),
        }
        for item in items
    ]


def parse_confidence(raw) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.5


def mean_rho(correlation: CorrelationMatrix, providers: list[str]) -> float:
    if len(providers) < 2:
        return 0.0
    values = []
    for i in range(len(providers)):
        for j in range(i + 1, len(providers)):
            values.append(correlation.rho(providers[i], providers[j]))
    return sum(values) / len(values) if values else 0.0


def quantile_cutpoints(values: list[float], n_bins: int) -> list[float]:
    if not values:
        return []
    sorted_values = sorted(values)
    cuts = []
    for idx in range(1, n_bins):
        pos = int(round((len(sorted_values) - 1) * idx / n_bins))
        cuts.append(sorted_values[pos])
    return cuts


def assign_bin(value: float, cutpoints: list[float]) -> int:
    for idx, cut in enumerate(cutpoints):
        if value <= cut:
            return idx
    return len(cutpoints)


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def accuracy(rows: list[dict], key: str) -> float | None:
    if not rows:
        return None
    return round(sum(1 for row in rows if row[key]) / len(rows), 4)


def summarize_band(rows: list[dict]) -> dict:
    return {
        "n": len(rows),
        "mean_temperature": mean([row["temperature"] for row in rows]),
        "mean_eta": mean([row["order_parameter"] for row in rows]),
        "mean_trust": mean([row["trust_score"] for row in rows]),
        "mean_hallucination_bound": mean([row["hallucination_bound"] for row in rows]),
        "majority_accuracy": accuracy(rows, "majority_correct"),
        "d2_accuracy": accuracy(rows, "d2_correct"),
        "routed_rate": accuracy(rows, "d2_routed"),
        "phase_counts": dict((phase, sum(1 for row in rows if row["phase"] == phase)) for phase in {"ordered", "critical", "disordered"}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Experiment 3 phase-transition study")
    parser.add_argument("--benchmark-module", default="remora.benchmarks.extended_v2", help="Benchmark module import path")
    parser.add_argument("--results", default=str(ROOT / "results" / "ablation_v2_results.json"), help="Canonical results JSON used for majority and D2 comparison")
    parser.add_argument("--output", default=str(ROOT / "results" / "phase_transition_study_results.json"), help="Output JSON path")
    parser.add_argument("--calibration", default=None, help="Optional thermodynamic calibration JSON")
    parser.add_argument("--n-bins", type=int, default=5, help="Number of temperature bins for the phase study")
    parser.add_argument("--max-items", type=int, default=None, help="Optional cap for smoke runs")
    args = parser.parse_args()

    items, meta_map, _ = load_benchmark(args.benchmark_module)
    if args.max_items is not None:
        items = items[: args.max_items]
    meta = load_meta(items, meta_map)
    calibration = load_thermodynamic_calibration(args.calibration)

    canonical = json.loads(Path(args.results).read_text(encoding="utf-8"))
    majority_items = {item["item_id"]: item for item in canonical["conditions"]["B_majority"]["items"]}
    d2_items = {item["item_id"]: item for item in canonical["conditions"]["D2_balanced"]["items"]}

    cache = Store(".remora_cache.json")
    oracles = [CachedOracle(GroqOracle(model), cache) for model in ORACLE_MODELS]
    correlation = CorrelationMatrix(window_size=500)
    genome = Genome(enable_thermodynamic_control=True)

    rows = []
    difficulty_groups: dict[str, list[dict]] = defaultdict(list)

    for item, item_meta in zip(items, meta):
        prompt = build_eval_prompt(item)
        responses = [oracle.ask(prompt) for oracle in oracles]
        verdicts = [(response.provider, phi(response.extracted)) for response in responses]
        confidences = [parse_confidence(response.extracted.get("confidence", 0.5)) for response in responses]
        rho_bar = mean_rho(correlation, [provider for provider, _ in verdicts])

        thermo = predict_trust_before_iteration(
            pre_sweep_verdicts=[(provider, verdict.fingerprint()) for provider, verdict in verdicts],
            pre_sweep_confidences=confidences,
            rho_bar=rho_bar,
            lambda_coupling=genome.negation_weight,
            calibration=calibration,
        )
        decision = phase_decision(
            thermo,
            genome_max_iterations=genome.max_iterations,
            trust_threshold_high=genome.trust_threshold_high,
            trust_threshold_low=genome.trust_threshold_low,
            halluc_threshold=genome.hallucination_threshold,
        )
        correlation.observe(verdicts)

        majority = majority_items[item.item_id]
        d2 = d2_items[item.item_id]
        row = {
            **item_meta,
            "phase": thermo.phase,
            "action": decision.action,
            "temperature": round(thermo.temperature, 4),
            "raw_temperature": round(thermo.raw_temperature or thermo.temperature, 4),
            "critical_temperature": round(thermo.critical_temperature, 4) if thermo.critical_temperature is not None else None,
            "temperature_ratio": round(thermo.temperature_ratio, 4) if thermo.temperature_ratio is not None else None,
            "order_parameter": round(thermo.order_parameter, 4),
            "susceptibility": round(thermo.susceptibility, 4),
            "trust_score": round(thermo.trust_score, 4),
            "hallucination_bound": round(thermo.hallucination_bound, 4),
            "majority_correct": bool(majority["correct"]),
            "d2_correct": bool(d2["correct"]),
            "d2_routed": bool(d2.get("routed", False)),
        }
        rows.append(row)
        difficulty_groups[row["difficulty"]].append(row)

    temperatures = [row["temperature"] for row in rows]
    cutpoints = quantile_cutpoints(temperatures, max(1, args.n_bins))
    temp_bands: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        band_idx = assign_bin(row["temperature"], cutpoints)
        label = f"T_bin_{band_idx + 1}"
        row["temperature_band"] = label
        temp_bands[label].append(row)

    band_summaries = {band: summarize_band(group) for band, group in sorted(temp_bands.items())}
    difficulty_summaries = {difficulty: summarize_band(group) for difficulty, group in sorted(difficulty_groups.items())}

    ordered_band_labels = [band for band, summary in band_summaries.items() if summary["phase_counts"].get("ordered", 0) >= summary["n"] / 2]
    eta_means = [summary["mean_eta"] for _, summary in sorted(band_summaries.items()) if summary["mean_eta"] is not None]
    eta_drop = round(max(eta_means) - min(eta_means), 4) if eta_means else 0.0

    summary = {
        "n_items": len(rows),
        "n_bins": args.n_bins,
        "temperature_cutpoints": [round(cut, 4) for cut in cutpoints],
        "eta_range": eta_drop,
        "ordered_like_bands": ordered_band_labels,
        "band_summaries": band_summaries,
        "difficulty_summaries": difficulty_summaries,
        "phase_counts": {
            phase: sum(1 for row in rows if row["phase"] == phase)
            for phase in ("ordered", "critical", "disordered")
        },
    }

    out = {
        "meta": {
            "oracles": ORACLE_MODELS,
            "benchmark_module": args.benchmark_module,
            "source_results": args.results,
            "calibration": args.calibration,
            "cache": ".remora_cache.json",
        },
        "summary": summary,
        "items": rows,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n── Phase transition study summary ───────────────────────────────────────")
    print(f"Items: {summary['n_items']}  bins: {summary['n_bins']}  eta range: {summary['eta_range']:.4f}")
    for band, band_summary in summary["band_summaries"].items():
        print(
            f"  {band:8s}: n={band_summary['n']:3d} "
            f"T={band_summary['mean_temperature']:.3f} "
            f"eta={band_summary['mean_eta']:.3f} "
            f"maj={band_summary['majority_accuracy']:.1%} "
            f"D2={band_summary['d2_accuracy']:.1%} "
            f"routed={band_summary['routed_rate']:.1%}"
        )
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
