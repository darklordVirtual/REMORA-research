# Author: Stian Skogbrott
# License: Apache-2.0
"""Conformal phase guardrail — holdout evaluation.

Loads (trust_score, is_correct) pairs from a results JSON, fits the
ConformalPhaseGuardrail with several target risks, and writes
results/conformal_guardrail_holdout.json with the full risk-coverage curve and
calibration metrics for each setting.

The loader accepts the canonical REMORA per-item correctness field
`majority_correct` as a fallback when `is_correct` is absent, so the script
works against the standard thermodynamic eval artifacts.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from remora.selective.guardrail import ConformalPhaseGuardrail


_CORRECTNESS_KEYS = ("is_correct", "majority_correct", "correct", "answered_correctly")


def _load_pairs(path: Path) -> tuple[list[float], list[bool]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items") or data.get("results") or data
    if not isinstance(items, list):
        raise SystemExit(f"Unrecognised structure in {path}: expected list of items")
    scores: list[float] = []
    labels: list[bool] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        s = entry.get("trust_score")
        y = None
        for key in _CORRECTNESS_KEYS:
            if key in entry and entry[key] is not None:
                y = entry[key]
                break
        if s is None or y is None:
            continue
        scores.append(float(s))
        labels.append(bool(y))
    if not scores:
        raise SystemExit(
            f"No (trust_score, correctness) pairs found in {path}. "
            f"Tried keys: {_CORRECTNESS_KEYS}"
        )
    return scores, labels


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path,
                        default=Path("results/thermodynamic_eval_results.json"),
                        help="JSON file with items containing trust_score and is_correct")
    parser.add_argument("--output", type=Path,
                        default=Path("results/conformal_guardrail_holdout.json"))
    parser.add_argument("--targets", nargs="+", type=float,
                        default=[0.02, 0.05, 0.10, 0.15, 0.20])
    parser.add_argument("--cal-fraction", type=float, default=0.6)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    scores, labels = _load_pairs(args.input)
    report_per_target: dict[str, dict] = {}
    for target in args.targets:
        g = ConformalPhaseGuardrail(
            target_risk=target,
            cal_fraction=args.cal_fraction,
            seed=args.seed,
        )
        report = g.fit(scores, labels)
        key = f"{target:.3f}"
        report_per_target[key] = asdict(report)

    payload = {
        "input": args.input.as_posix(),
        "n": len(scores),
        "cal_fraction": args.cal_fraction,
        "seed": args.seed,
        "reports": report_per_target,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
