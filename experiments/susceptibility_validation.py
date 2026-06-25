# Author: Stian Skogbrott
# License: Apache-2.0
#!/usr/bin/env python3
"""Validate whether high susceptibility predicts non-helpful iteration.

This experiment intentionally reuses the existing thermodynamic per-item output
so it can be run cheaply and repeatedly during calibration. The target claim is
empirical and narrow:

    Do items with higher susceptibility chi concentrate cases where D2 routing
    fails to improve over majority voting?

The script treats "iteration did not help" as the operational label
`not helped_vs_majority`. It also tracks the stronger failure label
`hurt_vs_majority` separately.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def rate(rows: list[dict], key: str) -> float | None:
    if not rows:
        return None
    return round(sum(1 for row in rows if row[key]) / len(rows), 4)


def quantile_cutpoints(values: list[float], n_bins: int) -> list[float]:
    if not values:
        return []
    sorted_values = sorted(values)
    cuts = []
    for index in range(1, n_bins):
        pos = int(round((len(sorted_values) - 1) * index / n_bins))
        cuts.append(sorted_values[pos])
    return cuts


def assign_bin(value: float, cutpoints: list[float]) -> int:
    for idx, cut in enumerate(cutpoints):
        if value <= cut:
            return idx
    return len(cutpoints)


def summarize(rows: list[dict]) -> dict:
    return {
        "n": len(rows),
        "mean_chi": mean([row["susceptibility"] for row in rows]),
        "mean_temperature": mean([row["temperature"] for row in rows]),
        "mean_trust": mean([row["trust_score"] for row in rows]),
        "majority_accuracy": rate(rows, "majority_correct"),
        "d2_accuracy": rate(rows, "d2_correct"),
        "routed_rate": rate(rows, "d2_routed"),
        "help_rate": rate(rows, "helped_vs_majority"),
        "hurt_rate": rate(rows, "hurt_vs_majority"),
        "not_help_rate": rate(rows, "not_helpful_iteration"),
        "adversarial_share": rate(rows, "is_adversarial"),
        "hard_share": rate(rows, "is_hard"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate susceptibility against iteration utility")
    parser.add_argument(
        "--input",
        default=str(ROOT / "results" / "thermodynamic_eval_results.json"),
        help="Per-item thermodynamic evaluation JSON",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "results" / "susceptibility_validation_results.json"),
        help="Output JSON path",
    )
    parser.add_argument("--n-bins", type=int, default=4, help="Number of susceptibility quantile bins")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    items = data.get("items", [])
    if not items:
        raise SystemExit(f"No items found in {args.input}")

    enriched = []
    for item in items:
        helped = bool(item.get("helped_vs_majority", False))
        _hurt = bool(item.get("hurt_vs_majority", False))  # noqa: F841
        enriched.append(
            {
                **item,
                "not_helpful_iteration": not helped,
                "is_hard": item.get("difficulty") in {"hard", "adversarial"},
                "is_adversarial": bool(item.get("is_adversarial", False)),
            }
        )

    chi_values = [item["susceptibility"] for item in enriched]
    cutpoints = quantile_cutpoints(chi_values, max(1, args.n_bins))

    chi_bands: dict[str, list[dict]] = {}
    for item in enriched:
        band_idx = assign_bin(item["susceptibility"], cutpoints)
        label = f"chi_bin_{band_idx + 1}"
        item["chi_band"] = label
        chi_bands.setdefault(label, []).append(item)

    low_band = chi_bands.get("chi_bin_1", [])
    high_band = chi_bands.get(f"chi_bin_{args.n_bins}", [])
    routed = [item for item in enriched if item.get("d2_routed")]
    routed_high = [item for item in routed if item.get("chi_band") == f"chi_bin_{args.n_bins}"]

    summary = {
        "n_items": len(enriched),
        "n_bins": args.n_bins,
        "chi_cutpoints": [round(cut, 4) for cut in cutpoints],
        "overall": summarize(enriched),
        "by_chi_band": {band: summarize(rows) for band, rows in sorted(chi_bands.items())},
        "routed_overall": summarize(routed),
        "high_vs_low": {
            "high_not_help_rate": summarize(high_band)["not_help_rate"],
            "low_not_help_rate": summarize(low_band)["not_help_rate"],
            "high_hurt_rate": summarize(high_band)["hurt_rate"],
            "low_hurt_rate": summarize(low_band)["hurt_rate"],
        },
        "routed_high_chi": summarize(routed_high),
    }

    out = {
        "meta": {
            "source": args.input,
            "target": "high susceptibility predicts non-helpful iteration",
            "label_definitions": {
                "helped_vs_majority": "D2 correct and majority incorrect",
                "hurt_vs_majority": "majority correct and D2 incorrect",
                "not_helpful_iteration": "not helped_vs_majority",
            },
        },
        "summary": summary,
        "items": enriched,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n── Susceptibility validation summary ───────────────────────────────────")
    print(
        f"Items: {summary['n_items']}  bins: {summary['n_bins']}  "
        f"overall help={summary['overall']['help_rate']:.1%}  "
        f"overall hurt={summary['overall']['hurt_rate']:.1%}"
    )
    for band, band_summary in summary["by_chi_band"].items():
        print(
            f"  {band:10s}: n={band_summary['n']:3d} "
            f"chi={band_summary['mean_chi']:.3f} "
            f"not_help={band_summary['not_help_rate']:.1%} "
            f"hurt={band_summary['hurt_rate']:.1%} "
            f"D2={band_summary['d2_accuracy']:.1%}"
        )
    print(
        f"\nHigh-vs-low chi: not_help {summary['high_vs_low']['high_not_help_rate']:.1%} vs "
        f"{summary['high_vs_low']['low_not_help_rate']:.1%}; hurt {summary['high_vs_low']['high_hurt_rate']:.1%} vs "
        f"{summary['high_vs_low']['low_hurt_rate']:.1%}"
    )
    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    main()
