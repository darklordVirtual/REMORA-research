# Author: Stian Skogbrott
# License: Apache-2.0
"""Check structural flag coverage of harmful benchmark tasks for M1 analysis."""
from __future__ import annotations
import json
from pathlib import Path
from remora.toolcall.benchmark_v2 import load_benchmark_v2

STRUCTURAL_FLAGS = [
    "contains_prompt_injection",
    "fallback_contains_destructive",
    "requires_human_approval",
    "intent_arg_conflict",
]

RESULT_PATH = Path(__file__).resolve().parent.parent / "results" / "m1_flag_coverage.json"


def main() -> None:
    tasks = load_benchmark_v2()
    harmful = [t for t in tasks if t.is_unsafe_if_executed]
    benign = [t for t in tasks if not t.is_unsafe_if_executed]

    def has_structural(t) -> bool:
        ctx = t.context or {}
        return any(ctx.get(f) for f in STRUCTURAL_FLAGS)

    harmful_with_flag = [t for t in harmful if has_structural(t)]
    harmful_no_flag = [t for t in harmful if not has_structural(t)]

    # Count flag breakdown for harmful tasks without structural flags
    no_flag_breakdown = {}
    for t in harmful_no_flag:
        ctx = t.context or {}
        sig = tuple(sorted(k for k, v in ctx.items() if v and k not in STRUCTURAL_FLAGS))
        no_flag_breakdown[sig] = no_flag_breakdown.get(sig, 0) + 1

    # Severity breakdown for harmful_no_flag
    sev_breakdown: dict[str, int] = {}
    for t in harmful_no_flag:
        sev_breakdown[t.severity] = sev_breakdown.get(t.severity, 0) + 1

    result = {
        "total_tasks": len(tasks),
        "harmful_tasks": len(harmful),
        "benign_tasks": len(benign),
        "harmful_with_structural_flag": len(harmful_with_flag),
        "harmful_without_any_structural_flag": len(harmful_no_flag),
        "structural_flag_coverage_pct": round(len(harmful_with_flag) / len(harmful) * 100, 1) if harmful else 0,
        "no_flag_severity_breakdown": sev_breakdown,
        "interpretation": (
            "If harmful_without_any_structural_flag > 0, then structural gates alone "
            "cannot catch all harmful tasks, and the clean-signal FAR=0 must be "
            "explained by other signals (severity, text heuristics). "
            "If == 0, benchmark design ensures all harmful tasks have structural flags."
        ),
    }

    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"Total tasks: {result['total_tasks']}")
    print(f"Harmful tasks: {result['harmful_tasks']}")
    print(f"Harmful with structural flag: {result['harmful_with_structural_flag']}")
    print(f"Harmful WITHOUT structural flag: {result['harmful_without_any_structural_flag']}")
    print(f"Structural coverage: {result['structural_flag_coverage_pct']}%")
    print(f"Severity of uncovered: {result['no_flag_severity_breakdown']}")
    print(f"Result written to {RESULT_PATH}")


if __name__ == "__main__":
    main()
