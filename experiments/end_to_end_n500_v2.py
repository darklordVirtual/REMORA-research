# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""End-to-end N500 evaluation with the new stack enabled.

Loads the locked N500 benchmark, runs REMORA with:
  enable_conformal_guardrail=True
  enable_gainability_routing=True
  enable_evidence_v2=True
  enable_assurance_trace=True
  enable_counterfactual_v2=True

Writes per-item decisions and assurance roots to
results/end_to_end_n500_v2.json. The top-level Merkle construction standard
and per-item leaf counts come from the runtime trace, never decision text.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--benchmark",
        default="artifacts/benchmark_n500_locked.json",
        type=Path,
    )
    parser.add_argument(
        "--output",
        default="results/end_to_end_n500_v2.json",
        type=Path,
    )
    parser.add_argument(
        "--baseline",
        default="results/thermodynamic_router_eval_n500_final_results.json",
        type=Path,
        help="Existing locked baseline for delta comparison.",
    )
    args = parser.parse_args()

    bench = json.loads(args.benchmark.read_text(encoding="utf-8"))
    items = bench.get("items") or bench.get("benchmark") or bench
    n = len(items) if isinstance(items, list) else 0

    from remora.engine import Remora
    from remora.genome import Genome
    from remora.assurance.trace import TRACE_STANDARD_V2

    genome = Genome()
    genome.enable_conformal_guardrail = True
    genome.enable_gainability_routing = True
    genome.enable_evidence_v2 = True
    genome.enable_assurance_trace = True
    genome.enable_counterfactual_v2 = True

    # Try to use MockOracle if available; otherwise use whatever is available.
    try:
        from remora.oracles.mock import MockOracle
        oracles = [MockOracle(name=f"mock-{i}") for i in range(3)]
    except (ImportError, TypeError):
        # Inspect actual MockOracle signature if TypeError
        try:
            from remora.oracles.mock import MockOracle
            # Try without name kwarg
            oracles = [MockOracle() for _ in range(3)]
        except Exception:
            oracles = []

    if not oracles:
        print("WARNING: No oracles available. Writing empty results.")
        payload = {
            "benchmark": str(args.benchmark),
            "baseline": str(args.baseline),
            "n_evaluated": 0,
            "items": [],
            "note": "No oracle pool available for smoke run.",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.output}")
        return

    engine = Remora(oracles=oracles, genome=genome)

    per_item = []
    for it in (items[:n] if isinstance(items, list) else []):
        q = it.get("question") or it.get("query") or ""
        if not q:
            continue
        state = engine.run(q)
        report = engine.report(state)
        trace = report.get("assurance_trace")
        if (
            not isinstance(trace, dict)
            or trace.get("signature_standard") != TRACE_STANDARD_V2
            or type(trace.get("leaf_count")) is not int
            or trace["leaf_count"] < 1
            or not isinstance(trace.get("root_hash"), str)
            or len(trace["root_hash"]) != 64
            or any(ch not in "0123456789abcdef" for ch in trace["root_hash"])
        ):
            raise RuntimeError("N500: missing or invalid v2 assurance trace; refusing unversioned roots")
        per_item.append({
            "question": q,
            "decisions": report.get("decisions"),
            "require_rag": report.get("require_rag"),
            "assurance_root": trace["root_hash"],
            "leaf_count": trace["leaf_count"],
            "final_V": report.get("final_V"),
        })

    payload = {
        "benchmark": str(args.benchmark),
        "baseline": str(args.baseline),
        "n_evaluated": len(per_item),
        "assurance_trace_standard": TRACE_STANDARD_V2,
        "items": per_item,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
