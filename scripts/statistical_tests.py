#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Paired statistical tests for REMORA result files.

Computes:
- Paired bootstrap CI for accuracy deltas
- McNemar exact test on discordant pairs

Default input: results/ablation_v2_results.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def mcnemar_exact_pvalue(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value via binomial tail on discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = 0.0
    for i in range(0, k + 1):
        p += math.comb(n, i) * (0.5**n)
    return min(1.0, 2.0 * p)


def paired_bootstrap_delta(a: list[int], b: list[int], n_boot: int = 10000, seed: int = 42):
    """Return mean delta and percentile CI for paired binary outcomes."""
    if len(a) != len(b):
        raise ValueError("Paired vectors must have equal length")
    n = len(a)
    if n == 0:
        return {"delta": 0.0, "ci_95": [0.0, 0.0]}

    rng = random.Random(seed)
    deltas = []
    for _ in range(n_boot):
        idx = [rng.randrange(0, n) for _ in range(n)]
        aa = sum(a[i] for i in idx) / n
        bb = sum(b[i] for i in idx) / n
        deltas.append(bb - aa)
    deltas.sort()
    lo = deltas[int(0.025 * n_boot)]
    hi = deltas[int(0.975 * n_boot)]
    return {
        "delta": round((sum(b) / n) - (sum(a) / n), 6),
        "ci_95": [round(lo, 6), round(hi, 6)],
    }


def correctness_vector(cond: dict) -> list[int]:
    return [1 if it.get("correct") else 0 for it in cond.get("items", [])]


def compare(name_a: str, name_b: str, conditions: dict, n_boot: int):
    a = correctness_vector(conditions[name_a])
    b = correctness_vector(conditions[name_b])
    if len(a) != len(b):
        raise ValueError(f"Length mismatch between {name_a} and {name_b}")

    b_only = sum(1 for ai, bi in zip(a, b) if ai == 0 and bi == 1)
    a_only = sum(1 for ai, bi in zip(a, b) if ai == 1 and bi == 0)
    both = sum(1 for ai, bi in zip(a, b) if ai == 1 and bi == 1)
    neither = sum(1 for ai, bi in zip(a, b) if ai == 0 and bi == 0)

    boot = paired_bootstrap_delta(a, b, n_boot=n_boot)
    pval = mcnemar_exact_pvalue(a_only, b_only)
    return {
        "A": name_a,
        "B": name_b,
        "n": len(a),
        "acc_A": round(sum(a) / len(a), 6) if a else 0.0,
        "acc_B": round(sum(b) / len(b), 6) if b else 0.0,
        "delta_B_minus_A": boot["delta"],
        "delta_ci_95": boot["ci_95"],
        "discordant": {
            "A_only_correct": a_only,
            "B_only_correct": b_only,
            "both_correct": both,
            "both_wrong": neither,
        },
        "mcnemar_exact_p": round(pval, 8),
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# REMORA Statistical Tests",
        "",
        f"Source: {report['source']}",
        "",
        "| Comparison | n | Acc A | Acc B | Delta (B-A) | 95% CI | McNemar p |",
        "|---|---:|---:|---:|---:|---|---:|",
    ]
    for c in report["comparisons"]:
        lines.append(
            f"| {c['A']} vs {c['B']} | {c['n']} | {c['acc_A']:.4f} | {c['acc_B']:.4f} | "
            f"{c['delta_B_minus_A']:.4f} | [{c['delta_ci_95'][0]:.4f}, {c['delta_ci_95'][1]:.4f}] | {c['mcnemar_exact_p']:.6f} |"
        )
    lines.append("")
    lines.append("McNemar uses exact binomial on discordant pairs.")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Run paired stats on ablation results")
    ap.add_argument("--input", default="results/ablation_v2_results.json")
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument(
        "--pairs",
        nargs="*",
        default=["B_majority:D2_balanced", "C_remora:D2_balanced", "C_remora:D3_hybrid"],
        help="Condition pairs in A:B form",
    )
    args = ap.parse_args()

    in_path = ROOT / args.input
    data = json.loads(in_path.read_text())
    cond = data.get("conditions", {})

    comparisons = []
    for p in args.pairs:
        a, b = p.split(":", 1)
        if a not in cond or b not in cond:
            raise SystemExit(f"Unknown condition in pair {p}")
        comparisons.append(compare(a, b, cond, n_boot=args.bootstrap))

    report = {
        "source": args.input,
        "n_items": data.get("meta", {}).get("n_items"),
        "comparisons": comparisons,
    }

    out_json = ROOT / "results" / "stat_tests.json"
    out_md = ROOT / "docs" / "stat_tests.md"
    out_json.write_text(json.dumps(report, indent=2) + "\n")
    out_md.write_text(render_markdown(report))
    print(f"Wrote {out_json} and {out_md}")


if __name__ == "__main__":
    main()
