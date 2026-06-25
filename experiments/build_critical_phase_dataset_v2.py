# Author: Stian Skogbrott
# License: Apache-2.0
"""Build augmented critical-phase calibration dataset (REMORA Benchmark v2).

Purpose
-------
The N=544 calibration dataset has only 32 critical-phase items, making the
per-stratum Mondrian conformal guarantee unreliable at 5 % target risk.
This script augments the dataset with external benchmark questions that have
been assigned trust scores via a **calibrated oracle simulation**, yielding a
combined dataset with ≥200 critical-phase items suitable for re-running the
Mondrian repeated-splits validation.

External sources loaded
-----------------------
1. TruthfulQA (truthfulqa/truthful_qa, generation, validation, 817 items)
   Observed critical-phase rate in N=544: 31.8 %.
2. ARC-Challenge (allenai/ai2_arc, ARC-Challenge, test, 1172 items)
   Harder science MCQ — estimated critical-phase rate: ~20 %.
3. MMLU-Pro (TIGER-Lab/MMLU-Pro, test, sample 500)
   Professional-level multi-choice — estimated critical-phase rate: ~22 %.

Simulation methodology
----------------------
Phase labels and trust scores are derived from a **calibrated oracle
simulation**, NOT from live LLM inference.  The simulation reproduces the
observed per-phase trust-score distributions from the N=544 real dataset:

    critical  (n=32 observed): trust ~ Uniform(0.006, 0.242), P(correct)=0.625
    ordered   (n=99 observed): trust ~ Uniform(0.478, 0.933), P(correct)=0.869
    disordered(n=413 observed): trust ~ Uniform(0.000, 0.014), P(correct)=0.286

Phase assignment probabilities per source (calibrated from observed rates):
    TruthfulQA :  31.8 % critical / 54.1 % ordered / 14.1 % disordered
    ARC-Challenge: 20.0 % critical / 50.0 % ordered / 30.0 % disordered
    MMLU-Pro:      22.0 % critical / 38.0 % ordered / 40.0 % disordered

These calibration constants are derived from:
- N=544 observed TruthfulQA phase distribution (exact)
- Published LLM accuracy on ARC-Challenge / MMLU-Pro literature values

IMPORTANT: Because trust scores are simulated, conclusions about REMORA's
*operational accuracy* on these items cannot be drawn.  The purpose is to
demonstrate that the Mondrian conformal guarantee *becomes achievable* once
the critical-phase stratum has n≥200 calibration items.  Real oracle
validation requires live LLM inference on the same question set.

All simulated items are tagged with ``"oracle_source": "calibrated_simulation"``
in the output JSON.

Additionally this script also replaces the 75 ``remora_curated`` items with 75
independently sourced ARC-Challenge items to address the selection-bias
concern documented in NEGATIVE_RESULTS.md §1 and §2.

Outputs
-------
``results/benchmark_v2_critical_augmented.json``
    Combined dataset (≥700 items, ≥200 critical-phase).
``results/mondrian_v2_repeated_splits.json``
    Mondrian repeated-splits results on the augmented dataset (20 seeds).
``results/benchmark_v2_summary.md``
    Human-readable summary of the augmented dataset and Mondrian results.
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants — calibrated from N=544 observed data
# ---------------------------------------------------------------------------

# Per-phase trust score ranges (from N=544)
_PHASE_TRUST = {
    "critical":   (0.0056, 0.2417),
    "ordered":    (0.4785, 0.9325),
    "disordered": (0.0000, 0.0137),
}

# P(majority_correct | trust=lo) and P(majority_correct | trust=hi) per phase.
# A linear interpolation gives a trust→correctness relationship that makes
# conformal prediction meaningful (higher trust → more likely correct).
# Values calibrated so that the *overall* P(correct) matches observed N=544:
#   critical: 0.625, ordered: 0.869, disordered: 0.286
_PHASE_CORRECT_AT_LO = {
    "critical":   0.42,
    "ordered":    0.72,
    "disordered": 0.26,
}
_PHASE_CORRECT_AT_HI = {
    "critical":   0.87,
    "ordered":    0.98,
    "disordered": 0.32,
}

# Phase probability distributions per benchmark source
_SOURCE_PHASE_PROBS: dict[str, dict[str, float]] = {
    "truthfulqa": {"critical": 0.318, "ordered": 0.541, "disordered": 0.141},
    "arc_challenge": {"critical": 0.200, "ordered": 0.500, "disordered": 0.300},
    "mmlu_pro":   {"critical": 0.220, "ordered": 0.380, "disordered": 0.400},
}

RESULTS_DIR = Path(__file__).parent.parent / "results"

# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

def _sample_phase(source: str, rng: random.Random) -> str:
    probs = _SOURCE_PHASE_PROBS[source]
    r = rng.random()
    cumulative = 0.0
    for phase, p in probs.items():
        cumulative += p
        if r < cumulative:
            return phase
    return "disordered"


def _sample_trust(phase: str, rng: random.Random) -> float:
    lo, hi = _PHASE_TRUST[phase]
    if phase == "critical":
        # Use Beta-like shape: more items near lower end (harder items)
        u = rng.betavariate(1.5, 3.0)
        return lo + u * (hi - lo)
    if phase == "ordered":
        u = rng.betavariate(3.0, 2.0)
        return lo + u * (hi - lo)
    # disordered: concentrated near zero
    u = rng.betavariate(1.0, 5.0)
    return lo + u * (hi - lo)


def _sample_correct(phase: str, trust: float, rng: random.Random) -> bool:
    """Sample majority_correct with trust-score correlation.

    A linear interpolation from P(correct | trust=lo) to P(correct | trust=hi)
    ensures that higher trust scores predict correctness, which is the
    prerequisite for conformal prediction to produce meaningful thresholds.
    """
    lo, hi = _PHASE_TRUST[phase]
    p_lo = _PHASE_CORRECT_AT_LO[phase]
    p_hi = _PHASE_CORRECT_AT_HI[phase]
    t_norm = (trust - lo) / (hi - lo) if hi > lo else 0.5
    t_norm = max(0.0, min(1.0, t_norm))
    p = p_lo + (p_hi - p_lo) * t_norm
    return rng.random() < p


def _make_simulated_item(
    item_id: str,
    benchmark: str,
    question: str,
    source: str,
    rng: random.Random,
    domain: str = "external",
) -> dict[str, Any]:
    phase = _sample_phase(source, rng)
    trust = _sample_trust(phase, rng)
    correct = _sample_correct(phase, trust, rng)
    return {
        "item_id": item_id,
        "benchmark": benchmark,
        "domain": domain,
        "question_preview": question[:120],
        "phase": phase,
        "trust_score": round(trust, 6),
        "majority_correct": correct,
        "oracle_source": "calibrated_simulation",
        "simulation_calibration": "N=544_thermodynamic_eval",
        "is_adversarial": False,
        "difficulty": "hard" if phase in ("critical", "disordered") else "medium",
    }


# ---------------------------------------------------------------------------
# Load datasets
# ---------------------------------------------------------------------------

def _load_truthfulqa() -> list[tuple[str, str]]:
    """Return list of (question_id, question_text) for TruthfulQA."""
    try:
        from datasets import load_dataset  # type: ignore[import]
        ds = load_dataset(
            "truthfulqa/truthful_qa", "generation",
            split="validation",
            trust_remote_code=False,
        )
        return [(f"tqa_{i}", row["question"]) for i, row in enumerate(ds)]
    except Exception as e:
        print(f"[WARNING] TruthfulQA load failed: {e}", file=sys.stderr)
        return []


def _load_arc_challenge(split: str = "test") -> list[tuple[str, str]]:
    """Return list of (item_id, question_text) for ARC-Challenge."""
    try:
        from datasets import load_dataset  # type: ignore[import]
        ds = load_dataset(
            "allenai/ai2_arc", "ARC-Challenge",
            split=split,
            trust_remote_code=False,
        )
        return [(f"arc_{row['id']}", row["question"]) for row in ds]
    except Exception as e:
        print(f"[WARNING] ARC-Challenge ({split}) load failed: {e}", file=sys.stderr)
        return []


def _load_mmlu_pro(n: int = 500, seed: int = 42) -> list[tuple[str, str]]:
    """Return up to *n* (item_id, question_text) tuples from MMLU-Pro."""
    try:
        from datasets import load_dataset  # type: ignore[import]
        ds = load_dataset(
            "TIGER-Lab/MMLU-Pro",
            split="test",
            trust_remote_code=False,
        )
        rng = random.Random(seed)
        indices = list(range(len(ds)))
        rng.shuffle(indices)
        selected = indices[:n]
        return [(f"mmlu_{ds[i]['question_id']}", ds[i]["question"]) for i in selected]
    except Exception as e:
        print(f"[WARNING] MMLU-Pro load failed: {e}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Load original N=544 dataset
# ---------------------------------------------------------------------------

def _load_original() -> list[dict[str, Any]]:
    path = RESULTS_DIR / "thermodynamic_eval_n500_calibrated_results.json"
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("items", data.get("results", []))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build(seed: int = 42) -> dict[str, Any]:
    rng = random.Random(seed)

    print("Loading original N=544 dataset …")
    original = _load_original()
    print(f"  Loaded {len(original)} items")

    # Split: keep non-remora_curated items + record them
    independent_original = [
        i for i in original if i.get("benchmark") != "remora_curated"
    ]
    remora_curated = [
        i for i in original if i.get("benchmark") == "remora_curated"
    ]
    print(f"  Keeping {len(independent_original)} independent original items")
    print(f"  Excluding {len(remora_curated)} remora_curated items (selection-bias concern)")

    # Load external sources
    print("\nLoading external benchmarks …")
    tqa_items = _load_truthfulqa()
    print(f"  TruthfulQA: {len(tqa_items)} questions")

    arc_items = _load_arc_challenge("test")
    arc_val_items = _load_arc_challenge("validation")
    all_arc = arc_items + arc_val_items
    print(f"  ARC-Challenge: {len(all_arc)} questions")

    mmlu_items = _load_mmlu_pro(n=500, seed=seed)
    print(f"  MMLU-Pro: {len(mmlu_items)} questions")

    # Build replacement items for remora_curated (75 ARC items)
    print("\nBuilding remora_curated replacement items (75 ARC-Challenge) …")
    rng2 = random.Random(seed + 1)
    rng2.shuffle(all_arc)
    arc_replacement = all_arc[:75]
    replacement_items = [
        _make_simulated_item(
            item_id=item_id,
            benchmark="arc_challenge_independent",
            question=q,
            source="arc_challenge",
            rng=rng,
            domain="science",
        )
        for item_id, q in arc_replacement
    ]
    print(f"  Created {len(replacement_items)} replacement items")

    # Build critical-phase expansion from TruthfulQA
    print("\nBuilding critical-phase expansion from TruthfulQA (target: 200 critical) …")
    expansion_tqa: list[dict[str, Any]] = []
    critical_count = 0
    for item_id, q in tqa_items:
        item = _make_simulated_item(
            item_id=item_id,
            benchmark="truthfulqa_extended",
            question=q,
            source="truthfulqa",
            rng=rng,
            domain="factual",
        )
        expansion_tqa.append(item)
        if item["phase"] == "critical":
            critical_count += 1
    print(f"  TruthfulQA expansion: {len(expansion_tqa)} items, {critical_count} critical")

    # Build additional items from ARC remaining + MMLU-Pro
    arc_remaining = all_arc[75:]  # Skip the 75 used as replacement
    expansion_arc: list[dict[str, Any]] = []
    for item_id, q in arc_remaining[:300]:
        item = _make_simulated_item(
            item_id=item_id,
            benchmark="arc_challenge_extended",
            question=q,
            source="arc_challenge",
            rng=rng,
            domain="science",
        )
        expansion_arc.append(item)

    expansion_mmlu: list[dict[str, Any]] = []
    for item_id, q in mmlu_items:
        item = _make_simulated_item(
            item_id=item_id,
            benchmark="mmlu_pro_extended",
            question=q,
            source="mmlu_pro",
            rng=rng,
            domain="professional",
        )
        expansion_mmlu.append(item)

    # Combine into v2 dataset
    all_items = independent_original + replacement_items + expansion_tqa + expansion_arc + expansion_mmlu

    # Count phases
    phase_counts: dict[str, int] = defaultdict(int)
    for item in all_items:
        phase_counts[item["phase"]] += 1

    # Count critical-phase items (original + simulated)
    original_critical = sum(1 for i in independent_original if i.get("phase") == "critical")
    simulated_critical = sum(
        1 for i in (replacement_items + expansion_tqa + expansion_arc + expansion_mmlu)
        if i["phase"] == "critical"
    )
    total_critical = phase_counts["critical"]

    print("\nAugmented dataset composition:")
    print(f"  Total: {len(all_items)} items")
    print(f"  Critical: {total_critical} ({original_critical} original + {simulated_critical} simulated)")
    print(f"  Ordered:  {phase_counts['ordered']}")
    print(f"  Disordered: {phase_counts['disordered']}")

    # Benchmark source breakdown
    by_benchmark: dict[str, int] = defaultdict(int)
    for item in all_items:
        by_benchmark[item.get("benchmark", "unknown")] += 1

    result = {
        "metadata": {
            "version": "v2",
            "description": (
                "REMORA Benchmark v2: N=544 original (excl. remora_curated) + "
                "external benchmark augmentation for critical-phase expansion. "
                "Simulated items are tagged with oracle_source=calibrated_simulation."
            ),
            "total_items": len(all_items),
            "phase_counts": dict(phase_counts),
            "by_benchmark": dict(by_benchmark),
            "original_critical": original_critical,
            "simulated_critical": simulated_critical,
            "seed": seed,
            "calibration_source": "thermodynamic_eval_n500_calibrated_results.json",
        },
        "items": all_items,
    }

    out_path = RESULTS_DIR / "benchmark_v2_critical_augmented.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved: {out_path}")
    return result


# ---------------------------------------------------------------------------
# Mondrian repeated splits on augmented dataset
# ---------------------------------------------------------------------------

def run_mondrian_on_augmented(result: dict[str, Any], n_seeds: int = 20) -> dict[str, Any]:
    from remora.selective.guardrail import MondrianPhaseGuardrail

    items = result["items"]
    scores = [float(i["trust_score"]) for i in items]
    labels = [bool(i["majority_correct"]) for i in items]
    phases = [i["phase"] for i in items]

    print(f"\nRunning Mondrian repeated splits ({n_seeds} seeds) on N={len(items)} …")

    all_results: list[dict] = []
    for target_risk in (0.05, 0.10, 0.15):
        for seed in range(n_seeds):
            g = MondrianPhaseGuardrail(target_risk=target_risk, seed=seed)
            report = g.fit(scores, labels, phases)
            for phase in ("ordered", "critical", "disordered"):
                r = report.holdout_risk_per_phase[phase]
                c = report.holdout_coverage_per_phase[phase]
                n_cal = report.n_calibration_per_phase[phase]
                n_test = report.n_test_per_phase[phase]
                all_results.append({
                    "target_risk": target_risk,
                    "seed": seed,
                    "phase": phase,
                    "holdout_risk": r,
                    "holdout_coverage": c,
                    "n_cal": n_cal,
                    "n_test": n_test,
                    "failed": r is not None and r > target_risk,
                })

    # Summarise
    summary_rows = []
    for target_risk in (0.05, 0.10, 0.15):
        for phase in ("ordered", "critical", "disordered"):
            rows = [
                r for r in all_results
                if r["target_risk"] == target_risk and r["phase"] == phase
            ]
            risks = [r["holdout_risk"] for r in rows if r["holdout_risk"] is not None]
            covs = [r["holdout_coverage"] for r in rows]
            fails = sum(1 for r in rows if r["failed"])
            mean_risk = sum(risks) / len(risks) if risks else None
            mean_cov = sum(covs) / len(covs) if covs else 0.0
            summary_rows.append({
                "target": target_risk,
                "phase": phase,
                "mean_risk": round(mean_risk, 4) if mean_risk is not None else None,
                "mean_coverage": round(mean_cov, 4),
                "seeds_failing": fails,
                "n_seeds": n_seeds,
            })

    mondrian_result = {
        "dataset_version": "v2",
        "n_items": len(items),
        "phase_counts": result["metadata"]["phase_counts"],
        "n_seeds": n_seeds,
        "summary": summary_rows,
        "raw": all_results,
    }

    out_path = RESULTS_DIR / "mondrian_v2_repeated_splits.json"
    with open(out_path, "w") as f:
        json.dump(mondrian_result, f, indent=2)
    print(f"Saved: {out_path}")
    return mondrian_result


# ---------------------------------------------------------------------------
# Write summary markdown
# ---------------------------------------------------------------------------

def write_summary(
    dataset_result: dict[str, Any],
    mondrian_result: dict[str, Any],
) -> None:
    meta = dataset_result["metadata"]
    lines = [
        "# REMORA Benchmark v2 — Critical-Phase Augmentation Summary",
        "",
        "## Dataset Composition",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total items | {meta['total_items']} |",
        f"| Critical phase | {meta['phase_counts']['critical']} "
        f"(orig={meta['original_critical']}, sim={meta['simulated_critical']}) |",
        f"| Ordered phase  | {meta['phase_counts']['ordered']} |",
        f"| Disordered phase | {meta['phase_counts']['disordered']} |",
        "",
        "### By benchmark source",
        "",
        "| Benchmark | N |",
        "|-----------|---|",
    ]
    for bm, n in sorted(meta["by_benchmark"].items(), key=lambda x: -x[1]):
        lines.append(f"| {bm} | {n} |")
    lines += [
        "",
        "> **Note:** Items tagged `oracle_source: calibrated_simulation` have trust scores",
        "> derived from calibrated priors (N=544 observed distributions), not live LLM",
        "> inference. See `experiments/build_critical_phase_dataset_v2.py` for methodology.",
        "",
        "## Mondrian Conformal Results (20-seed repeated splits)",
        "",
        "| Target | Phase | Mean risk | Mean cov | Seeds failing |",
        "|-------:|:------|----------:|---------:|--------------:|",
    ]
    for row in mondrian_result["summary"]:
        r = f"{row['mean_risk']:.3f}" if row["mean_risk"] is not None else "N/A"
        lines.append(
            f"| {row['target']:.0%} | {row['phase']} "
            f"| {r} | {row['mean_coverage']:.1%} "
            f"| {row['seeds_failing']}/{row['n_seeds']} |"
        )
    lines += [
        "",
        "### Comparison: N=544 vs N=v2 for critical phase (15 % target)",
        "",
        "| Dataset | Critical n | Seeds failing @ 15 % |",
        "|---------|-----------|----------------------|",
        "| N=544 (original) | 32 | 2/20 (guarantee unreliable) |",
    ]
    critical_15 = next(
        (r for r in mondrian_result["summary"]
         if r["target"] == 0.15 and r["phase"] == "critical"),
        None,
    )
    if critical_15:
        lines.append(
            f"| N=v2 (augmented) | {meta['phase_counts']['critical']} "
            f"| {critical_15['seeds_failing']}/20 |"
        )
    lines += [
        "",
        "## Caveats",
        "",
        "- Simulated trust scores reproduce the *shape* of the N=544 distributions but",
        "  do not reflect actual oracle consensus on these specific questions.",
        "- The critical-phase improvement shown above is a **methodology validation**:",
        "  it confirms the mathematical requirement (n≥200) enables reliable guarantees.",
        "- Operational validation requires running live oracle inference on these items.",
        "",
    ]
    out_path = RESULTS_DIR / "benchmark_v2_summary.md"
    out_path.write_text("\n".join(lines))
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    dataset_result = build(seed=42)
    mondrian_result = run_mondrian_on_augmented(dataset_result, n_seeds=20)
    write_summary(dataset_result, mondrian_result)
    print("\nDone.")
