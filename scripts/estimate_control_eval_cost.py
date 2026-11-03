#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Offline cost model for the control evaluation: no API call, tokens estimated as characters / 4.

Needs the pinned packages in experiments/control_eval/requirements.txt.

Measured locally from AgentDojo v1.2.2 (characters / 4, an estimate, not a
tokenizer count):

* the default system prompt and every suite's tool schemas as the agent
  element sends them (all four suites; schemas are not tasks);
* user prompt length, ground-truth call count and tool-output size of the
  development user tasks of banking, slack and travel only. Workspace is held
  out from development, so its per-task figures are the mean of the other
  three; test-split tasks are never read, only counted.

Assumed (stated in the output): output tokens per agent turn including
adaptive thinking, extra turns when an injection is followed, injection text
size, monitor prompt and reply size, and how many agent requests the CRN
cache shares. Prices are the owner's candidates in USD per MTok.

    python scripts/estimate_control_eval_cost.py --out artifacts/control_eval/cost_model_v1.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from statistics import mean
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SUITES = ("banking", "slack", "travel", "workspace")
HOLDOUT = ("workspace",)
CHARS_PER_TOKEN = 4
ARMS = ("A_none", "B_refuse_all", "C_allowlist", "D_monitor", "E1_remora_strict", "E_IFC",
        "E_IFC_WS1")
PRICES = {  # USD per MTok; cache write = 1.25 x input (5-minute TTL)
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_write": 2.5, "cache_read": 0.2},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_read": 0.01},
}
MONITOR = "claude-haiku-5-5"
ASSUME = {
    "output_tokens_per_agent_turn": 300,
    "visible_output_tokens_per_turn_in_context": 80,
    "extra_turns_when_attack_followed": 2,
    "injection_text_tokens": 150,
    "monitor_prompt_tokens": 250,
    "monitor_output_tokens": 120,
    "crn_share_of_non_reference_agent_requests": 0.5,
    "B_refuse_all_agent_calls": 2,
}


def tok(text: str) -> float:
    return len(text) / CHARS_PER_TOKEN


def measure() -> dict[str, Any]:
    from agentdojo.agent_pipeline.agent_pipeline import load_system_message
    from agentdojo.agent_pipeline.ground_truth_pipeline import GroundTruthPipeline
    from agentdojo.functions_runtime import FunctionsRuntime
    from agentdojo.task_suite.load_suites import get_suite

    from experiments.control_eval.metrics import inspected_user_tasks, split_tasks

    system = load_system_message(None)
    out: dict[str, Any] = {"system_prompt_tokens": tok(system), "suites": {}}
    for name in SUITES:
        suite = get_suite("v1.2.2", name)
        runtime = FunctionsRuntime(suite.tools)
        tools = [{"name": f.name, "description": f.description or "",
                  "input_schema": f.parameters.model_json_schema()}
                 for f in runtime.functions.values()]
        parts = split_tasks({name: list(suite.user_tasks)}, forced_dev=inspected_user_tasks())[name]
        row: dict[str, Any] = {"tools": len(tools),
                               "tool_schema_tokens": tok(json.dumps(tools)),
                               "dev_user_tasks": len(parts["dev"]),
                               "test_user_tasks": len(parts["test"]),
                               "injection_tasks": len(suite.injection_tasks)}
        if name not in HOLDOUT:
            prompts, calls, outputs = [], [], []
            for tid in parts["dev"]:
                task = suite.get_user_task_by_id(tid)
                env = suite.load_and_inject_default_environment({})
                _, _, _, msgs, _ = GroundTruthPipeline(task).query(
                    task.PROMPT, FunctionsRuntime(suite.tools), task.init_environment(env))
                results = [m for m in msgs if m["role"] == "tool"]
                prompts.append(tok(task.PROMPT))
                calls.append(len(results))
                outputs += [tok(" ".join(b["content"] for b in m["content"] or ())) for m in results]
            row.update({"dev_prompt_tokens_mean": mean(prompts), "dev_calls_mean": mean(calls),
                        "dev_tool_output_tokens_mean": mean(outputs) if outputs else 0.0,
                        "source": "measured on development tasks"})
        out["suites"][name] = row
    dev = [r for n, r in out["suites"].items() if n not in HOLDOUT]
    for name in HOLDOUT:
        out["suites"][name].update({
            "dev_prompt_tokens_mean": mean(r["dev_prompt_tokens_mean"] for r in dev),
            "dev_calls_mean": mean(r["dev_calls_mean"] for r in dev),
            "dev_tool_output_tokens_mean": mean(r["dev_tool_output_tokens_mean"] for r in dev),
            "source": "held out: schemas measured, per-task figures are the other suites' mean"})
    return out


def episode_cost(m: dict[str, Any], suite: str, model: str, attacked: bool,
                 cache: bool = True) -> dict[str, float]:
    """One agent trajectory under arm A: turns = calls + 1 final answer."""
    s = m["suites"][suite]
    p = PRICES[model]
    prefix = m["system_prompt_tokens"] + s["tool_schema_tokens"] + s["dev_prompt_tokens_mean"]
    turns = s["dev_calls_mean"] + 1 + (ASSUME["extra_turns_when_attack_followed"] if attacked else 0)
    step = ASSUME["visible_output_tokens_per_turn_in_context"] + s["dev_tool_output_tokens_mean"]
    n = max(1, round(turns))
    inputs = [prefix + k * step + (ASSUME["injection_text_tokens"] if attacked and k else 0)
              for k in range(n)]
    out_tok = n * ASSUME["output_tokens_per_agent_turn"]
    if cache:
        usd = inputs[0] * p["cache_write"]
        for prev, cur in zip(inputs, inputs[1:], strict=False):
            usd += prev * p["cache_read"] + (cur - prev) * p["cache_write"]
    else:
        usd = sum(inputs) * p["input"]
    usd = (usd + out_tok * p["output"]) / 1e6
    return {"calls": n, "input_tokens": sum(inputs), "output_tokens": out_tok, "usd": usd}


def monitor_cost(m: dict[str, Any], suite: str) -> float:
    s = m["suites"][suite]
    p = PRICES[MONITOR]
    inp = ASSUME["monitor_prompt_tokens"] + s["tool_schema_tokens"] / 3 + s["dev_prompt_tokens_mean"] + 60
    return s["dev_calls_mean"] * (inp * p["input"] + ASSUME["monitor_output_tokens"] * p["output"]) / 1e6


def pair_cost(m: dict[str, Any], suite: str, model: str, attacked: bool, crn: bool) -> float:
    ep = episode_cost(m, suite, model, attacked)
    a = ep["usd"]
    # B: its first request equals A's (shared under CRN); the answer after the block is new.
    b_calls = ASSUME["B_refuse_all_agent_calls"] - (1 if crn else 0)
    b = b_calls / ep["calls"] * a
    others = len(ARMS) - 2  # every arm but A and B runs a full trajectory
    share = ASSUME["crn_share_of_non_reference_agent_requests"] if crn else 0.0
    return a + b + others * a * (1 - share) + monitor_cost(m, suite)


def project(m: dict[str, Any], pairs: Sequence[int]) -> dict[str, Any]:
    test_users = {n: r["test_user_tasks"] for n, r in m["suites"].items()}
    weights = {n: test_users[n] * m["suites"][n]["injection_tasks"] for n in SUITES}
    total_w = sum(weights.values())
    out: dict[str, Any] = {}
    for model in PRICES:
        rows = {}
        for crn in (False, True):
            per_pair = sum(weights[n] / total_w * pair_cost(m, n, model, True, crn) for n in SUITES)
            benign = sum(test_users[n] * pair_cost(m, n, model, False, crn) for n in SUITES)
            rows["crn" if crn else "no_sharing"] = {
                "per_attacked_pair_all_arms_usd": per_pair,
                "benign_all_test_tasks_all_arms_usd": benign,
                "by_pairs_usd": {str(n): n * per_pair + benign for n in pairs}}
        out[model] = rows
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--pairs", type=int, nargs="*", default=[60, 100, 150, 200, 300])
    args = parser.parse_args(argv)
    m = measure()
    per_episode = {model: {s: {"benign": episode_cost(m, s, model, False),
                               "attacked": episode_cost(m, s, model, True),
                               "attacked_no_prompt_cache": episode_cost(m, s, model, True, False)}
                           for s in SUITES} for model in PRICES}
    body = {"status": "estimate", "method": "characters / 4 over AgentDojo v1.2.2 prompts, tool "
            "schemas and development-task tool outputs; no tokenizer, no API call",
            "arms": list(ARMS), "monitor_model": MONITOR, "prices_usd_per_mtok": PRICES,
            "assumptions": ASSUME, "measured": m,
            "arm_A_episode": per_episode,
            "projection": project(m, args.pairs)}
    text = json.dumps(body, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
