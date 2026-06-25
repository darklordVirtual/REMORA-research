# Author: Stian Skogbrott
# License: Apache-2.0
#!/usr/bin/env python3
"""Evaluate thermodynamic phase predictions against canonical N=302 results.

This experiment replays the cached pre-sweep for the v2 benchmark, computes the
experimental thermodynamic state before iteration, and compares the resulting
phase predictions against the canonical `B_majority` and `D2_balanced` item
outcomes stored in `results/ablation_v2_results.json`.
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
            "is_adversarial": meta_map.get(item.item_id, {}).get("is_adversarial", False),
            "difficulty": meta_map.get(item.item_id, {}).get("difficulty", "medium"),
        }
        for item in items
    ]


def mean_rho(correlation: CorrelationMatrix, providers: list[str]) -> float:
    if len(providers) < 2:
        return 0.0
    values = []
    for i in range(len(providers)):
        for j in range(i + 1, len(providers)):
            values.append(correlation.rho(providers[i], providers[j]))
    return sum(values) / len(values) if values else 0.0


def parse_confidence(raw) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.5


def round4(value: float) -> float:
    return round(value, 4)


def summarise_phase(records: list[dict]) -> dict:
    if not records:
        return {
            "n": 0,
            "majority_accuracy": None,
            "d2_accuracy": None,
            "routed_rate": None,
            "mean_trust_score": None,
            "mean_hallucination_bound": None,
            "mean_temperature": None,
            "helped_vs_majority": 0,
            "hurt_vs_majority": 0,
        }

    n = len(records)
    return {
        "n": n,
        "majority_accuracy": round4(sum(1 for record in records if record["majority_correct"]) / n),
        "d2_accuracy": round4(sum(1 for record in records if record["d2_correct"]) / n),
        "routed_rate": round4(sum(1 for record in records if record["d2_routed"]) / n),
        "mean_trust_score": round4(sum(record["trust_score"] for record in records) / n),
        "mean_hallucination_bound": round4(sum(record["hallucination_bound"] for record in records) / n),
        "mean_temperature": round4(sum(record["temperature"] for record in records) / n),
        "helped_vs_majority": sum(1 for record in records if record["d2_correct"] and not record["majority_correct"]),
        "hurt_vs_majority": sum(1 for record in records if record["majority_correct"] and not record["d2_correct"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate thermodynamic phase predictions on a benchmark/results pair")
    parser.add_argument(
        "--benchmark-module",
        type=str,
        default="remora.benchmarks.extended_v2",
        help="Benchmark module import path",
    )
    parser.add_argument(
        "--results",
        type=str,
        default=str(ROOT / "results" / "ablation_v2_results.json"),
        help="Ablation results JSON used as the comparison target",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(ROOT / "results" / "thermodynamic_eval_results.json"),
        help="Output JSON path for the thermodynamic evaluation",
    )
    parser.add_argument(
        "--calibration",
        type=str,
        default=None,
        help="Optional thermodynamic calibration JSON",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Optional hard cap for quick validation runs",
    )
    args = parser.parse_args()

    print(f"\nLoading benchmark module {args.benchmark_module} for thermodynamic evaluation...")
    items, meta_map, _ = load_benchmark(args.benchmark_module)
    if args.max_items is not None:
        items = items[:args.max_items]
    meta = load_meta(items, meta_map)
    calibration = load_thermodynamic_calibration(args.calibration)
    print(f"  Items: {len(items)}")

    canonical = json.loads(Path(args.results).read_text(encoding="utf-8"))
    majority_items = {item["item_id"]: item for item in canonical["conditions"]["B_majority"]["items"]}
    d2_items = {item["item_id"]: item for item in canonical["conditions"]["D2_balanced"]["items"]}

    store = Store(".remora_cache.json")
    cached_oracles = [CachedOracle(GroqOracle(model), store) for model in ORACLE_MODELS]
    correlation = CorrelationMatrix(window_size=500)
    genome = Genome(enable_thermodynamic_control=True)

    records = []
    phase_groups: dict[str, list[dict]] = defaultdict(list)

    for item, item_meta in zip(items, meta):
        prompt = build_eval_prompt(item)
        responses = [oracle.ask(prompt) for oracle in cached_oracles]
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

        record = {
            **item_meta,
            "phase": thermo.phase,
            "action": decision.action,
            "temperature": round4(thermo.temperature),
            "raw_temperature": round4(thermo.raw_temperature or thermo.temperature),
            "critical_temperature": round4(thermo.critical_temperature) if thermo.critical_temperature is not None else None,
            "temperature_ratio": round4(thermo.temperature_ratio) if thermo.temperature_ratio is not None else None,
            "trust_score": round4(thermo.trust_score),
            "hallucination_bound": round4(thermo.hallucination_bound),
            "order_parameter": round4(thermo.order_parameter),
            "susceptibility": round4(thermo.susceptibility),
            "majority_correct": bool(majority["correct"]),
            "d2_correct": bool(d2["correct"]),
            "d2_routed": bool(d2.get("routed", False)),
            "helped_vs_majority": bool(d2["correct"] and not majority["correct"]),
            "hurt_vs_majority": bool(majority["correct"] and not d2["correct"]),
        }
        records.append(record)
        phase_groups[record["phase"]].append(record)

    summary = {
        "n_items": len(records),
        "phase_counts": {phase: len(group) for phase, group in phase_groups.items()},
        "phase_summary": {phase: summarise_phase(group) for phase, group in phase_groups.items()},
        "ordered_direct_accept_accuracy": round4(
            sum(1 for record in records if record["phase"] == "ordered" and record["majority_correct"]) /
            max(1, sum(1 for record in records if record["phase"] == "ordered"))
        ),
        "non_ordered_d2_accuracy": round4(
            sum(1 for record in records if record["phase"] != "ordered" and record["d2_correct"]) /
            max(1, sum(1 for record in records if record["phase"] != "ordered"))
        ),
        "non_ordered_majority_accuracy": round4(
            sum(1 for record in records if record["phase"] != "ordered" and record["majority_correct"]) /
            max(1, sum(1 for record in records if record["phase"] != "ordered"))
        ),
        "d2_helped_items": sum(1 for record in records if record["helped_vs_majority"]),
        "d2_hurt_items": sum(1 for record in records if record["hurt_vs_majority"]),
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
        "items": records,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n── Thermodynamic phase summary ───────────────────────────────────────────")
    for phase in ("ordered", "critical", "disordered"):
        phase_summary = summary["phase_summary"].get(phase)
        if not phase_summary:
            continue
        print(
            f"  {phase:11s}: n={phase_summary['n']:3d} "
            f"majority={phase_summary['majority_accuracy']:.1%} "
            f"D2={phase_summary['d2_accuracy']:.1%} "
            f"routed={phase_summary['routed_rate']:.1%} "
            f"trust={phase_summary['mean_trust_score']:.3f}"
        )
    print(
        f"\nOrdered direct-accept accuracy: {summary['ordered_direct_accept_accuracy']:.1%}\n"
        f"Non-ordered majority accuracy: {summary['non_ordered_majority_accuracy']:.1%}\n"
        f"Non-ordered D2 accuracy: {summary['non_ordered_d2_accuracy']:.1%}\n"
        f"D2 helped items: {summary['d2_helped_items']}  hurt items: {summary['d2_hurt_items']}"
    )
    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    main()
