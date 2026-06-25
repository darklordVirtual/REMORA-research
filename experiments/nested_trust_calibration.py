#!/usr/bin/env python3
"""Nested-style trust calibration experiment.

Input artifact format expected:
- JSON file with top-level `items` list
- each item has `trust_score` and correctness key (default: `majority_correct`)

Outputs a report with validation and holdout metrics before/after calibration.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from remora.calibration.trust_calibrator import (
    TrustCalibrator,
    brier_score,
    expected_calibration_error,
    log_loss,
    reliability_curve,
)


def _metrics(probs: list[float], labels: list[bool], n_bins: int) -> dict:
    return {
        "n": len(probs),
        "brier": round(brier_score(probs, labels), 6),
        "log_loss": round(log_loss(probs, labels), 6),
        "ece": round(expected_calibration_error(probs, labels, n_bins=n_bins), 6),
        "reliability": reliability_curve(probs, labels, n_bins=n_bins),
    }


def _split_three(items: list[dict], seed: int) -> tuple[list[dict], list[dict], list[dict]]:
    rows = list(items)
    random.Random(seed).shuffle(rows)
    n = len(rows)
    n_train = int(round(n * 0.60))
    n_val = int(round(n * 0.20))
    train = rows[:n_train]
    val = rows[n_train : n_train + n_val]
    holdout = rows[n_train + n_val :]
    return train, val, holdout


def _to_xy(rows: list[dict], label_key: str) -> tuple[list[float], list[bool]]:
    x = [float(row["trust_score"]) for row in rows]
    y = [bool(row[label_key]) for row in rows]
    return x, y


def main() -> None:
    parser = argparse.ArgumentParser(description="Run nested trust calibration report")
    parser.add_argument(
        "--input",
        default="results/thermodynamic_eval_results.json",
        help="Input artifact with item-level trust_score and correctness labels",
    )
    parser.add_argument("--label-key", default="majority_correct", help="Correctness key in each item row")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument(
        "--output",
        default="results/trust_calibration_report.json",
        help="Output report path",
    )
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    items = payload.get("items", [])
    if not items:
        raise ValueError("No items in input artifact")

    required = {"trust_score", args.label_key}
    for row in items:
        missing = required - set(row.keys())
        if missing:
            raise ValueError(f"Missing keys in item: {sorted(missing)}")

    train_rows, val_rows, holdout_rows = _split_three(items, seed=args.seed)
    train_x, train_y = _to_xy(train_rows, args.label_key)
    val_x, val_y = _to_xy(val_rows, args.label_key)
    holdout_x, holdout_y = _to_xy(holdout_rows, args.label_key)

    calibrator = TrustCalibrator(n_bins=args.bins)
    best_t = calibrator.fit(train_x, train_y)

    val_pre = _metrics(val_x, val_y, n_bins=args.bins)
    val_post = _metrics(calibrator.calibrate(val_x), val_y, n_bins=args.bins)
    holdout_pre = _metrics(holdout_x, holdout_y, n_bins=args.bins)
    holdout_post = _metrics(calibrator.calibrate(holdout_x), holdout_y, n_bins=args.bins)

    out = {
        "meta": {
            "input": args.input,
            "label_key": args.label_key,
            "seed": args.seed,
            "bins": args.bins,
            "split": {"train": len(train_rows), "validation": len(val_rows), "holdout": len(holdout_rows)},
        },
        "model": {"type": "temperature_scaling", "temperature": round(best_t, 6)},
        "validation": {"pre": val_pre, "post": val_post},
        "holdout": {"pre": holdout_pre, "post": holdout_post},
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print("Nested trust calibration report")
    print(f"  temperature={out['model']['temperature']:.4f}")
    print(
        "  holdout pre/post: "
        f"Brier {holdout_pre['brier']:.4f}->{holdout_post['brier']:.4f}, "
        f"ECE {holdout_pre['ece']:.4f}->{holdout_post['ece']:.4f}, "
        f"NLL {holdout_pre['log_loss']:.4f}->{holdout_post['log_loss']:.4f}"
    )
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
