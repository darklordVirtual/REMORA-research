# Author: Stian Skogbrott
# License: Apache-2.0
"""Critical-phase trust-inversion split (backs CLAIM-005).

Deterministic, offline, read-only. Produces the per-bucket artifact that
CLAIM-005 (critical-phase trust inversion) requires, computed directly from the
committed N500 thermodynamic evaluation so every number is reproducible.

Why this exists
---------------
CLAIM-005 previously quoted a low-trust 71.4% (N=21) / high-trust 27.3% (N=11)
critical-phase split, but the per-item artifact behind those exact numbers was
never committed (docs/06-reproducibility.md flagged it "directional, source
artifact pending"; open audit flag CAB-04). Worse, 71.4%*21 + 27.3%*11 = 18
correct, which is inconsistent with the committed aggregate of 20/32 correct in
the critical bucket (results/selective_n500_results.json). Those numbers came
from a different, uncommitted computation.

This script replaces them with a fully reproducible split from the committed
artifact, using a principled rule (split at the median critical-phase trust
score) so there is no free parameter to tune. The scientific finding is
preserved: within the critical phase, lower-trust items are MORE often correct
than higher-trust items (trust inversion). The split is consistent with the
20/32 aggregate by construction.

Input : results/thermodynamic_eval_n500_calibrated_results.json
Output: results/critical_trust_split_v1.json

Run: python scripts/compute_critical_trust_split.py
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INPUT = _REPO_ROOT / "results" / "thermodynamic_eval_n500_calibrated_results.json"
_OUTPUT = _REPO_ROOT / "results" / "critical_trust_split_v1.json"

SCHEMA_VERSION = "critical_trust_split_v1"


def compute() -> dict:
    items = json.loads(_INPUT.read_text(encoding="utf-8"))["items"]
    critical = [
        (it["trust_score"], 1 if it["majority_correct"] else 0)
        for it in items
        if it.get("phase") == "critical"
    ]
    n = len(critical)
    total_correct = sum(y for _, y in critical)

    median_trust = statistics.median(t for t, _ in critical)
    low = [y for t, y in critical if t < median_trust]
    high = [y for t, y in critical if t >= median_trust]

    def _bucket(ys: list[int]) -> dict:
        return {
            "n": len(ys),
            "correct": sum(ys),
            "accuracy": round(sum(ys) / len(ys), 4) if ys else None,
        }

    low_b, high_b = _bucket(low), _bucket(high)
    inversion = (
        low_b["accuracy"] is not None
        and high_b["accuracy"] is not None
        and low_b["accuracy"] > high_b["accuracy"]
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "input_artifact": "results/thermodynamic_eval_n500_calibrated_results.json",
        "split_rule": (
            "Critical-phase items split at the median critical-phase trust_score "
            "(low = trust < median, high = trust >= median). No tuned parameter."
        ),
        "median_critical_trust": round(median_trust, 6),
        "n_critical": n,
        "aggregate_correct": total_correct,
        "aggregate_accuracy": round(total_correct / n, 4) if n else None,
        "low_trust_bucket": low_b,
        "high_trust_bucket": high_b,
        "trust_inversion_present": inversion,
        "accuracy_delta_low_minus_high": (
            round(low_b["accuracy"] - high_b["accuracy"], 4)
            if inversion or (low_b["accuracy"] is not None and high_b["accuracy"] is not None)
            else None
        ),
        "consistency_check": {
            "sum_of_bucket_correct": low_b["correct"] + high_b["correct"],
            "matches_aggregate": (low_b["correct"] + high_b["correct"]) == total_correct,
        },
        "supersedes": (
            "The earlier uncommitted low-trust 71.4% (N=21) / high-trust 27.3% "
            "(N=11) figures, whose bucket correct counts (15 + 3 = 18) were "
            "inconsistent with the committed 20/32 critical aggregate. This "
            "artifact is the reproducible replacement (CAB-04)."
        ),
        "limitations": [
            "Small sample: 32 critical items total; treat as a directional finding.",
            "Correctness label is majority_correct from the committed N500 artifact.",
        ],
    }


def main() -> None:
    result = compute()
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    lo, hi = result["low_trust_bucket"], result["high_trust_bucket"]
    print("=== Critical-phase trust split (CLAIM-005) ===")
    print(f"n_critical={result['n_critical']}  aggregate={result['aggregate_correct']}"
          f"/{result['n_critical']} ({result['aggregate_accuracy']})")
    print(f"median trust = {result['median_critical_trust']}")
    print(f"LOW  trust: {lo['correct']}/{lo['n']} = {lo['accuracy']}")
    print(f"HIGH trust: {hi['correct']}/{hi['n']} = {hi['accuracy']}")
    print(f"trust inversion present: {result['trust_inversion_present']}  "
          f"(delta={result['accuracy_delta_low_minus_high']})")
    print(f"consistent with 20/32 aggregate: {result['consistency_check']['matches_aggregate']}")
    print(f"Written to: {_OUTPUT}")


if __name__ == "__main__":
    main()
