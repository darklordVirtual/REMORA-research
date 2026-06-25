"""Synthetic trust-trace generator for TSF code validation ONLY.

Generates labeled synthetic traces (value series + destabilization labels) so the
forecaster/evaluator can be unit-tested. These traces are NOT REMORA data and
carry no evidentiary weight. Deterministic given a seed.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path


def generate_trace(n: int, seed: int, destabilize_at: int | None) -> dict:
    rng = random.Random(seed)
    values, labels = [], []
    level = 0.8
    for t in range(n):
        noise = rng.gauss(0, 0.02)
        if destabilize_at is not None and t >= destabilize_at:
            level -= 0.05  # synthetic decay
        v = max(0.0, min(1.0, level + noise + 0.03 * math.sin(t / 5)))
        values.append(round(v, 4))
        labels.append(int(destabilize_at is not None and t >= destabilize_at))
    return {"seed": seed, "values": values, "labels": labels, "synthetic": True}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Synthetic TSF trace generator (validation only).")
    p.add_argument("--n", type=int, default=200)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--out", type=Path, default=Path(__file__).parent / "results" / "synthetic_traces.jsonl")
    args = p.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    with open(args.out, "w") as f:
        for i in range(args.count):
            dest = rng.choice([None, rng.randint(args.n // 2, args.n - 10)])
            f.write(json.dumps(generate_trace(args.n, args.seed + i, dest)) + "\n")
    print(f"Wrote {args.count} SYNTHETIC traces to {args.out}")
    print("Synthetic harness only. Not evidence of predictive destabilization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
