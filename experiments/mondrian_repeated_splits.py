"""Mondrian phase-stratified conformal repeated-splits validation.

Runs MondrianPhaseGuardrail over 20 random seeds on the N=544 calibrated
benchmark.  Reports per-phase coverage rates and failure counts, directly
addressing the statistical weakness documented in NEGATIVE_RESULTS.md §5.

Comparison:
- Global ConformalPhaseGuardrail (existing result from conformal_repeated_splits.py)
- MondrianPhaseGuardrail (per-phase calibration)

Output: results/mondrian_repeated_splits_results.json
"""
from __future__ import annotations

import json
import pathlib
import statistics

_REPO_ROOT = pathlib.Path(__file__).parent.parent
_EVAL_PATH  = _REPO_ROOT / "results" / "thermodynamic_eval_n500_calibrated_results.json"
_OUT_PATH   = _REPO_ROOT / "results" / "mondrian_repeated_splits_results.json"


def _load_data() -> tuple[list[float], list[bool], list[str]]:
    with open(_EVAL_PATH) as fh:
        data = json.load(fh)
    items = data["items"]
    scores = [float(i["trust_score"])  for i in items]
    labels = [bool(i["majority_correct"]) for i in items]
    phases = [str(i["phase"])          for i in items]
    return scores, labels, phases


def run() -> dict:
    from remora.selective.guardrail import MondrianPhaseGuardrail

    scores, labels, phases = _load_data()
    target_risks = [0.05, 0.10, 0.15]
    seeds = list(range(20))
    all_phases = ("ordered", "critical", "disordered")

    results_by_target: list[dict] = []

    for target_risk in target_risks:
        per_phase_risks:     dict[str, list[float]] = {p: [] for p in all_phases}
        per_phase_coverages: dict[str, list[float]] = {p: [] for p in all_phases}
        failures_per_phase:  dict[str, int]         = {p: 0  for p in all_phases}
        seed_records: list[dict] = []

        for seed in seeds:
            g = MondrianPhaseGuardrail(target_risk=target_risk, seed=seed)
            report = g.fit(scores, labels, phases)

            rec: dict = {"seed": seed, "thresholds": report.thresholds}
            for phase in all_phases:
                risk = report.holdout_risk_per_phase.get(phase)
                cov  = report.holdout_coverage_per_phase.get(phase, 0.0)
                rec[f"risk_{phase}"]     = risk
                rec[f"coverage_{phase}"] = cov
                if risk is not None:
                    per_phase_risks[phase].append(risk)
                    per_phase_coverages[phase].append(cov)
                    if risk > target_risk:
                        failures_per_phase[phase] += 1
            seed_records.append(rec)

        phase_summaries: dict[str, dict] = {}
        for phase in all_phases:
            risks = per_phase_risks[phase]
            covs  = per_phase_coverages[phase]
            phase_summaries[phase] = {
                "n_seeds_with_data":  len(risks),
                "mean_risk":          statistics.mean(risks)    if risks else None,
                "mean_coverage":      statistics.mean(covs)     if covs  else None,
                "failures_out_of_20": failures_per_phase[phase],
            }

        results_by_target.append({
            "target_risk":      target_risk,
            "n_seeds":          len(seeds),
            "phase_summaries":  phase_summaries,
            "seed_records":     seed_records,
        })

    out = {
        "method":          "MondrianPhaseGuardrail",
        "data_source":     str(_EVAL_PATH.name),
        "n_items":         len(scores),
        "results_by_target": results_by_target,
        "interpretation": (
            "Failures = seeds where holdout_risk > target_risk for that phase. "
            "Mondrian calibrates one threshold per phase so coverage holds "
            "conditionally within each stratum.  Compare to global conformal "
            "(results/conformal_repeated_splits.json) where 5%% target failed "
            "20/20 splits."
        ),
    }

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUT_PATH, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Wrote {_OUT_PATH}")
    return out


def summarise(out: dict) -> None:
    print(f"\nMondrian phase-stratified conformal — {out['n_items']} items")
    print(f"{'Target':>8}  {'Phase':<12}  {'Mean risk':>10}  {'Mean cov':>10}  {'Failures/20':>11}")
    print("-" * 60)
    for entry in out["results_by_target"]:
        tr = entry["target_risk"]
        for phase, s in entry["phase_summaries"].items():
            mr  = f"{s['mean_risk']:.3f}"  if s["mean_risk"]  is not None else "  n/a"
            mc  = f"{s['mean_coverage']:.3f}" if s["mean_coverage"] is not None else "  n/a"
            fai = s["failures_out_of_20"]
            print(f"{tr:>8.2f}  {phase:<12}  {mr:>10}  {mc:>10}  {fai:>11}")
    print()


if __name__ == "__main__":
    out = run()
    summarise(out)
