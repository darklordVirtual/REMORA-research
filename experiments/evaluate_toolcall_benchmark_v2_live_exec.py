from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from experiments.evaluate_toolcall_benchmark_v2_live import CACHE_PATH, build_decision_table
from remora.toolcall.live_execution import LiveExecutionTrace, LiveToolSandboxExecutor, aggregate_execution_metrics
from remora.toolcall.scoring import aggregate_metrics
from remora.toolcall.simulators import simulate

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = REPO_ROOT / "results" / "toolcall_benchmark_v2_live_exec_results.json"


def run(
    mode: str = "replay",
    cache_path: Path = CACHE_PATH,
    *,
    keep_sandbox: bool = False,
    sandbox_root: Path | None = None,
) -> dict[str, Any]:
    tasks, decisions_by_name = build_decision_table(mode=mode, cache_path=cache_path)

    policy_outcomes_by_name: dict[str, list[Any]] = defaultdict(list)
    traces_by_name: dict[str, list[LiveExecutionTrace]] = defaultdict(list)

    for baseline_name, decisions in decisions_by_name.items():
        base_dir = None
        if sandbox_root is not None:
            base_dir = sandbox_root / baseline_name
        executor = LiveToolSandboxExecutor(base_dir=base_dir, cleanup=(not keep_sandbox))
        try:
            for task, decision in zip(tasks, decisions):
                policy_outcomes_by_name[baseline_name].append(simulate(task, decision))
                traces_by_name[baseline_name].append(executor.execute(task, decision))
        finally:
            executor.close()

    baselines: dict[str, Any] = {}
    for baseline_name, outcomes in policy_outcomes_by_name.items():
        metrics = aggregate_metrics(tasks, outcomes)
        metrics["execution_sandbox"] = aggregate_execution_metrics(traces_by_name[baseline_name])
        baselines[baseline_name] = metrics

    best_utility = max(m["mean_utility"] for m in baselines.values())
    majority_unsafe = baselines["majority_vote_3_models"]["unsafe_execution_rate"]
    for metrics in baselines.values():
        metrics["unsafe_execution_reduction_vs_majority"] = majority_unsafe - metrics["unsafe_execution_rate"]
        metrics["utility_delta_vs_best_baseline"] = metrics["mean_utility"] - best_utility

    try:
        cache_label = str(cache_path.resolve().relative_to(REPO_ROOT.resolve()).as_posix())
    except ValueError:
        cache_label = str(cache_path.resolve())

    result = {
        "benchmark": "toolcall_benchmark_v2",
        "evaluation": "sandbox_live_execution",
        "mode": mode,
        "cache_path": cache_label,
        "n_tasks": len(tasks),
        "baselines": baselines,
        "limitations": [
            "Sandbox execution is local and deterministic; no production tools are touched.",
            "When mode=replay, single-model decisions come from deterministic cached entries.",
            "Live mode still requires configured provider SDKs and API keys for decision generation.",
            "Observed unsafe effects are sandbox-proxy signals, not real-world incident outcomes.",
        ],
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("replay", "live"), default="replay")
    parser.add_argument("--cache", default=str(CACHE_PATH))
    parser.add_argument("--keep-sandbox", action="store_true")
    parser.add_argument("--sandbox-root", default=None)
    args = parser.parse_args()

    sandbox_root = Path(args.sandbox_root) if args.sandbox_root else None
    result = run(
        mode=args.mode,
        cache_path=Path(args.cache),
        keep_sandbox=args.keep_sandbox,
        sandbox_root=sandbox_root,
    )
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {RESULT_PATH}")
    for name, metrics in result["baselines"].items():
        sx = metrics["execution_sandbox"]
        print(
            f"{name}: unsafe={metrics['unsafe_execution_rate']:.4f} "
            f"utility={metrics['mean_utility']:.4f} "
            f"exec_unsafe_effect={sx['unsafe_effect_rate']:.4f}"
        )


if __name__ == "__main__":
    main()
