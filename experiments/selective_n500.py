"""N500 selective-trust curve analysis.

Runs multi-signal selective prediction on the 544-item N500 calibrated
benchmark and writes results/selective_n500_results.json.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

DATA_PATH = Path("results/thermodynamic_eval_n500_calibrated_results.json")
OUT_PATH = Path("results/selective_n500_results.json")

SIGNALS = [
    "neg_temperature",
    "trust_score",
    "neg_susceptibility",
    "order_parameter",
]

COVERAGES = [0.05, 0.10, 0.15, 0.18, 0.20, 0.25, 0.30, 0.40]


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Two-sided Wilson interval."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _p_value_one_sided(k: int, n: int, p0: float) -> float:
    """One-sided binomial p-value (H1: accuracy > p0) via normal approximation."""
    if n == 0:
        return 1.0
    p_hat = k / n
    se = math.sqrt(p0 * (1 - p0) / n)
    if se == 0:
        return 0.0 if p_hat > p0 else 1.0
    z = (p_hat - p0) / se
    # P(Z > z) approximated via erfc
    return 0.5 * math.erfc(z / math.sqrt(2))


def _signal_values(items: list[dict], signal: str) -> list[float]:
    """Return sort-key (higher = more trusted) for each item."""
    if signal == "neg_temperature":
        return [-it["temperature"] for it in items]
    if signal == "trust_score":
        return [float(it.get("trust_score", 0.0)) for it in items]
    if signal == "neg_susceptibility":
        return [-float(it.get("susceptibility", 0.0)) for it in items]
    if signal == "order_parameter":
        return [float(it.get("order_parameter", 0.0)) for it in items]
    raise ValueError(f"Unknown signal: {signal}")


def selective_curve(
    items: list[dict],
    signal: str,
    coverages: list[float],
    baseline: float,
    baseline_ci: tuple[float, float],
) -> list[dict]:
    n_total = len(items)
    vals = _signal_values(items, signal)
    # Sort by (signal_value DESC, index ASC) to avoid dict comparison on ties
    order = sorted(range(n_total), key=lambda i: (-vals[i], i))
    ranked_items = [items[i] for i in order]

    rows = []
    for cov in coverages:
        k = max(1, round(n_total * cov))
        top = ranked_items[:k]
        correct = sum(1 for it in top if it["majority_correct"])
        acc = correct / k
        ci_lo, ci_hi = _wilson(correct, k)
        lift = acc - baseline
        p_val = _p_value_one_sided(correct, k, baseline)

        # Phase composition
        phase_counts: dict[str, int] = {}
        for it in top:
            phase_counts[it["phase"]] = phase_counts.get(it["phase"], 0) + 1

        rows.append(
            {
                "signal": signal,
                "coverage": round(cov, 4),
                "k": k,
                "correct": correct,
                "accuracy": round(acc, 6),
                "lift_pp": round(lift * 100, 4),
                "wilson_ci_lo": round(ci_lo, 4),
                "wilson_ci_hi": round(ci_hi, 4),
                "ci_nonoverlap": ci_lo > baseline_ci[1],
                "p_one_sided": round(p_val, 8),
                "phase_composition": phase_counts,
            }
        )
    return rows


def run(data_path: Path = DATA_PATH, out_path: Path = OUT_PATH) -> dict:
    raw = json.loads(data_path.read_text())
    items: list[dict] = raw if isinstance(raw, list) else raw.get("items", raw.get("results", []))

    n = len(items)
    n_correct = sum(1 for it in items if it["majority_correct"])
    baseline = n_correct / n
    baseline_ci = _wilson(n_correct, n)

    phase_summary: dict[str, dict] = {}
    for ph in ("ordered", "critical", "disordered"):
        sub = [it for it in items if it["phase"] == ph]
        nc = sum(1 for it in sub if it["majority_correct"])
        phase_summary[ph] = {
            "n": len(sub),
            "correct": nc,
            "accuracy": round(nc / len(sub), 6) if sub else 0.0,
        }

    all_rows: list[dict] = []
    for sig in SIGNALS:
        rows = selective_curve(items, sig, COVERAGES, baseline, baseline_ci)
        all_rows.extend(rows)

    # Best operating point: neg_temperature signal, maximise accuracy
    neg_temp_rows = [r for r in all_rows if r["signal"] == "neg_temperature"]
    best = max(neg_temp_rows, key=lambda r: r["accuracy"])

    result = {
        "n": n,
        "baseline_accuracy": round(baseline, 6),
        "baseline_wilson_ci": [round(baseline_ci[0], 4), round(baseline_ci[1], 4)],
        "phase_summary": phase_summary,
        "best_operating_point": best,
        "selective_curve": all_rows,
        "summary": (
            f"Best: {best['accuracy']*100:.2f}% accuracy at {best['coverage']*100:.0f}% coverage "
            f"(k={best['k']}, lift +{best['lift_pp']:.2f} pp over {baseline*100:.2f}% baseline, "
            f"Wilson CI [{best['wilson_ci_lo']:.3f}, {best['wilson_ci_hi']:.3f}], "
            f"p={best['p_one_sided']:.2e})"
        ),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(result["summary"])
    return result


if __name__ == "__main__":
    run()
