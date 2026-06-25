"""Evaluate TSF forecasters on SYNTHETIC traces. No claims permitted.

Reads results/synthetic_traces.jsonl, computes AUROC of each method's
destabilization score against the within-h label, writes results/tsf_results.json
with claims_allowed:false and data_source:synthetic.
"""
from __future__ import annotations

import json
from pathlib import Path

from experiments.tsf.forecast import destabilization_score

HERE = Path(__file__).parent
TRACES = HERE / "results" / "synthetic_traces.jsonl"
OUT = HERE / "results" / "tsf_results.json"
METHODS = ["b1", "b2", "b3"]
HORIZONS = [1, 3, 5]


def auroc(scores: list[float], labels: list[int]) -> float:
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def main() -> int:
    if not TRACES.exists():
        print("No synthetic traces. Run synthetic_trace_generator.py first.")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"status": "pending", "data_source": "synthetic",
                                   "claims_allowed": False, "horizons": []}, indent=2))
        return 2
    traces = [
        json.loads(line)
        for line in TRACES.read_text().splitlines()
        if line.strip()
    ]
    horizons_out = []
    for h in HORIZONS:
        entry = {"h": h, "baselines": {}}
        for m in METHODS:
            scores, labels = [], []
            for tr in traces:
                vals, labs = tr["values"], tr["labels"]
                for t in range(len(vals) - h):
                    scores.append(destabilization_score(vals[: t + 1], h, m))
                    labels.append(1 if any(labs[t + 1: t + 1 + h]) else 0)
            a = auroc(scores, labels)
            entry["baselines"][m] = round(a, 4) if a == a else None
        entry["auroc"] = entry["baselines"]["b1"]
        horizons_out.append(entry)
    OUT.write_text(json.dumps({
        "status": "ok",
        "data_source": "synthetic",
        "claims_allowed": False,
        "seed": 42,
        "note": "Synthetic harness only. Not evidence of predictive destabilization.",
        "horizons": horizons_out,
    }, indent=2))
    print(f"Wrote {OUT}")
    print("Synthetic harness only. Not evidence of predictive destabilization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
