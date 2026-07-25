# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Critical-phase trust-inversion split (backs CLAIM-005).

Deterministic, offline, read-only. Produces the per-bucket artifact that
CLAIM-005 (critical-phase trust inversion) requires, computed directly from the
committed N500 thermodynamic evaluation so every number is reproducible.

Why this exists
---------------
CLAIM-005 and the paper quoted a low-trust 71.4% (N=21) / high-trust 27.3%
(N=11) critical-phase split at the tau = 0.10 "groupthink boundary", but the
per-item artifact behind those exact percentages was never committed
(docs/06-reproducibility.md flagged it "directional, source artifact pending";
open audit flag CAB-04). Worse, 0.714*21 + 0.273*11 = 18 correct is inconsistent
with the committed aggregate of 20/32 correct in the critical bucket. Those
percentages came from a different, uncommitted computation.

This script replaces them with the fully reproducible split from the committed
artifact, at the SAME documented threshold the paper uses (tau = 0.10), so the
sample sizes (N=21 low / N=11 high) are unchanged and only the percentages move
to their true, aggregate-consistent values. The scientific finding is preserved:
within the critical phase, lower-trust items are MORE often correct than
higher-trust items (trust inversion). The Q1/Q4 quartile view the paper also
cites is reported alongside.

Input : results/thermodynamic_eval_n500_calibrated_results.json
Output: results/critical_trust_split_v1.json

Run: python scripts/compute_critical_trust_split.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INPUT = _REPO_ROOT / "results" / "thermodynamic_eval_n500_calibrated_results.json"
_OUTPUT = _REPO_ROOT / "results" / "critical_trust_split_v1.json"

SCHEMA_VERSION = "critical_trust_split_v1"
# The paper's documented "groupthink boundary": items with tau >= this are the
# high-trust bucket. This is the operating point PhaseAwareGuardrail rejects on,
# not a parameter tuned to the labels.
TAU_GROUPTHINK_BOUNDARY = 0.10


def _wilson_ci(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (centre - half), 1), round(100 * (centre + half), 1)]


def _bucket(ys: list[int]) -> dict:
    n = len(ys)
    k = sum(ys)
    return {
        "n": n,
        "correct": k,
        "accuracy_pct": round(100 * k / n, 1) if n else None,
        "wilson_ci_95_pct": _wilson_ci(k, n),
    }


def compute() -> dict:
    items = json.loads(_INPUT.read_text(encoding="utf-8"))["items"]
    critical = sorted(
        (it["trust_score"], 1 if it["majority_correct"] else 0)
        for it in items
        if it.get("phase") == "critical"
    )
    n = len(critical)
    total_correct = sum(y for _, y in critical)

    low = [y for t, y in critical if t < TAU_GROUPTHINK_BOUNDARY]
    high = [y for t, y in critical if t >= TAU_GROUPTHINK_BOUNDARY]
    low_b, high_b = _bucket(low), _bucket(high)

    # Quartile view (paper §13.3): Q1 lowest-trust vs Q4 highest-trust.
    q = n // 4
    q1 = [y for _, y in critical[:q]]
    q4 = [y for _, y in critical[-q:]]

    inversion = (
        low_b["accuracy_pct"] is not None
        and high_b["accuracy_pct"] is not None
        and low_b["accuracy_pct"] > high_b["accuracy_pct"]
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "input_artifact": "results/thermodynamic_eval_n500_calibrated_results.json",
        "split_rule": (
            f"Critical-phase items split at the tau = {TAU_GROUPTHINK_BOUNDARY} "
            "groupthink boundary (low = trust < boundary, high = trust >= "
            "boundary). This is the paper's documented operating point, not a "
            "parameter tuned to the labels."
        ),
        "tau_groupthink_boundary": TAU_GROUPTHINK_BOUNDARY,
        "n_critical": n,
        "aggregate_correct": total_correct,
        "aggregate_accuracy_pct": round(100 * total_correct / n, 1) if n else None,
        "low_trust_bucket": low_b,
        "high_trust_bucket": high_b,
        "trust_inversion_present": inversion,
        "accuracy_delta_pct_low_minus_high": (
            round(low_b["accuracy_pct"] - high_b["accuracy_pct"], 1)
            if inversion else None
        ),
        "quartile_view": {
            "q_size": q,
            "q1_low_trust_accuracy_pct": round(100 * sum(q1) / len(q1), 1) if q1 else None,
            "q4_high_trust_accuracy_pct": round(100 * sum(q4) / len(q4), 1) if q4 else None,
        },
        "consistency_check": {
            "sum_of_bucket_correct": low_b["correct"] + high_b["correct"],
            "matches_aggregate": (low_b["correct"] + high_b["correct"]) == total_correct,
        },
        "supersedes": (
            "The earlier uncommitted low-trust 71.4% (N=21) / high-trust 27.3% "
            "(N=11) percentages, whose bucket correct counts (15 + 3 = 18) were "
            "inconsistent with the committed 20/32 critical aggregate. Sample "
            "sizes are unchanged (N=21 / N=11); only the percentages are "
            "corrected to their reproducible values (CAB-04)."
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
    print("=== Critical-phase trust split (CLAIM-005), tau=0.10 boundary ===")
    print(f"n_critical={result['n_critical']}  aggregate={result['aggregate_correct']}"
          f"/{result['n_critical']} ({result['aggregate_accuracy_pct']}%)")
    print(f"LOW  (tau<0.10): {lo['correct']}/{lo['n']} = {lo['accuracy_pct']}%  CI={lo['wilson_ci_95_pct']}")
    print(f"HIGH (tau>=0.10): {hi['correct']}/{hi['n']} = {hi['accuracy_pct']}%  CI={hi['wilson_ci_95_pct']}")
    q = result["quartile_view"]
    print(f"Q1={q['q1_low_trust_accuracy_pct']}%  Q4={q['q4_high_trust_accuracy_pct']}%")
    print(f"inversion={result['trust_inversion_present']}  consistent={result['consistency_check']['matches_aggregate']}")
    print(f"Written to: {_OUTPUT}")


if __name__ == "__main__":
    main()
