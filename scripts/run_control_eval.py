#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""SAP v7 control evaluation runner (docs/assurance/statistical_analysis_plan_v7_control_eval.md).

Needs the pinned packages in experiments/control_eval/requirements.txt.

Modes:

``--split``
    Print the development/test split of user tasks (seed 20261017) of the
    suites that are not held out. A held-out suite is never loaded here; its
    test tasks are drawn only inside the sealed ``--test`` path.
``--dry-run``
    Development tasks only, no model call. A scripted agent proposes each
    user task's ground-truth calls in order and never adapts. Arms A, B, C,
    E1 and E2 run on the benign tasks. This shows how often each defence
    blocks legitimate calls and what that costs in AgentDojo utility, which
    is what adapter development needs. It touches no test task.

``--pilot --config <run config>``
    Development tasks of the non-held-out suites only (``holdout_suites``
    in the config; workspace is held out as a transfer test). Every arm in
    the config runs every episode with the real agent. Writes the pilot
    artifact: cost per episode, undefended attack success, per-arm counts.
``--test --config <run config> [--resume]``
    The sealed run, all four suites' test pairs. Refused unless the
    readiness gates G0-G6 pass (``scripts/check_study_readiness.py``) and
    the manifest status is ``locked_never_run``; sets ``evaluated`` after
    the run and refuses a second one. ``--resume`` continues a crashed run
    with the same run id from its response cache and ledger.

Both refuse to start without an owner-approved run config (model IDs,
prices per token, effort, max_tokens, monitor prompt) and an armed budget
ledger with a sub-cap for the phase. Every model call is reserved against
the ledger before it is sent (``experiments/control_eval/spend_ledger.py``).
The arms come from ``experiments/control_eval/arms.py``.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

BENCHMARK_VERSION = "v1.2.2"
SUITES = ("banking", "slack", "travel", "workspace")

from experiments.control_eval.run_config import HELD_OUT_SUITES  # noqa: E402


class RunRefused(RuntimeError):
    pass


def development_suites(names: Sequence[str]) -> list[str]:
    """The suites a development mode may load: every suite not held out."""
    return [name for name in names if name not in HELD_OUT_SUITES]


def _load_suite(name: str) -> Any:
    from agentdojo.task_suite.load_suites import get_suite
    return get_suite(BENCHMARK_VERSION, name)


def _suites(names: Sequence[str] | None = None) -> dict[str, Any]:
    """Load development suites. A held-out suite is refused before it is loaded
    (as in scripts/run_control_eval_g1.py)."""
    names = development_suites(SUITES) if names is None else list(names)
    held = sorted(set(names) & HELD_OUT_SUITES)
    if held:
        raise RunRefused(f"{held} held out of all development; not loaded")
    return {name: _load_suite(name) for name in names}


def split(suites: dict[str, Any] | None = None) -> dict[str, dict[str, list[str]]]:
    from experiments.control_eval.metrics import inspected_user_tasks, split_tasks
    suites = _suites() if suites is None else suites
    return split_tasks({name: list(s.user_tasks) for name, s in suites.items()},
                       forced_dev=inspected_user_tasks())


def _scripted_agent(task: Any):
    """An AgentDojo element that proposes *task*'s ground-truth calls one per turn."""
    from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
    from agentdojo.types import ChatAssistantMessage, text_content_block_from_string

    class ScriptedAgent(BasePipelineElement):
        def __init__(self) -> None:
            self._plan: list[Any] | None = None

        def query(self, query, runtime, env, messages=(), extra_args=None):
            extra_args = dict(extra_args or {})
            if self._plan is None:
                self._plan = list(task.ground_truth(env))
            if self._plan:
                call = self._plan.pop(0)
                message = ChatAssistantMessage(role="assistant", tool_calls=[call],
                                               content=[text_content_block_from_string("")])
            else:
                message = ChatAssistantMessage(
                    role="assistant", tool_calls=None,
                    content=[text_content_block_from_string(task.GROUND_TRUTH_OUTPUT)])
            return query, runtime, env, [*messages, message], extra_args

    return ScriptedAgent()


def _pipeline(task: Any, defence: Any, suite: str, task_id: str, log: list[dict[str, Any]]):
    from agentdojo.agent_pipeline import AgentPipeline, InitQuery, SystemMessage, ToolsExecutionLoop

    from experiments.control_eval.agentdojo_glue import GatedToolsExecutor

    agent = _scripted_agent(task)
    executor = GatedToolsExecutor(defence, suite=suite, user_task_id=task_id,
                                  injection_task_id=None, log=log)
    pipe = AgentPipeline([SystemMessage("You are a helpful assistant."), InitQuery(), agent,
                          ToolsExecutionLoop([executor, agent], max_iters=30)])
    pipe.name = "scripted-ground-truth"
    return pipe


def _dry_run_suite(suite_name: str, suite: Any, dev_ids: Sequence[str], report: dict[str, Any],
                   log: list[dict[str, Any]]) -> None:
    from agentdojo.functions_runtime import FunctionsRuntime

    from experiments.control_eval.agentdojo_glue import tool_specs
    from experiments.control_eval.policies import NoGate, RefuseAll, TaskAllowlist
    from experiments.control_eval.remora_adapter import OBSERVED, STRICT, RemoraGate

    env0 = suite.load_and_inject_default_environment({})
    tools = tool_specs(FunctionsRuntime(suite.tools))
    allowed = {tid: [c.function for c in suite.get_user_task_by_id(tid).ground_truth(env0)]
               for tid in dev_ids}
    arms = [NoGate(), RefuseAll(), TaskAllowlist(allowed), RemoraGate(tools, STRICT, suite_name),
            RemoraGate(tools, OBSERVED, suite_name)]
    for defence in arms:
        for tid in dev_ids:
            task = suite.get_user_task_by_id(tid)
            before = len(log)
            utility, _ = suite.run_task_with_pipeline(
                _pipeline(task, defence, suite_name, tid, log), task, None, {})
            calls = log[before:]
            arm = report["arms"].setdefault(defence.name, defaultdict(int))
            arm["tasks"] += 1
            arm["utility"] += int(utility)
            arm["calls"] += len(calls)
            arm["blocked"] += sum(1 for c in calls if not c["execute"])


def dry_run() -> dict[str, Any]:
    suites = _suites()
    dev = {name: parts["dev"] for name, parts in split(suites).items()}
    report: dict[str, Any] = {"status": "development_dry_run",
                              "held_out_suites": sorted(HELD_OUT_SUITES),
                              "benchmark_version": BENCHMARK_VERSION,
                              "agent": "scripted ground truth, non-adaptive, no model call",
                              "dev_tasks": dev, "arms": {}}
    log: list[dict[str, Any]] = []
    for suite_name, suite in suites.items():
        _dry_run_suite(suite_name, suite, dev[suite_name], report, log)
    report["arms"] = {k: dict(v) for k, v in report["arms"].items()}
    report["block_reasons"] = {
        name: dict(Counter(c["reason"] for c in log if c["defence"] == name and not c["execute"]))
        for name in report["arms"]}
    return report


def _armed_config(config: Path | None, phase: str, root: Path):
    """Load the config, check the phase cap and every arm name, before any client exists."""
    from experiments.control_eval.arms import UnknownArm, validate_arms
    from experiments.control_eval.run_config import ConfigRefused, load_run_config
    try:
        cfg = load_run_config(config, root)
    except ConfigRefused as exc:
        raise RunRefused(str(exc)) from exc
    if cfg.phase_caps_usd.get(phase, 0.0) <= 0:
        raise RunRefused(f"budget guard not armed: no positive sub-cap for phase {phase!r}")
    try:
        validate_arms(cfg.arms)
    except UnknownArm as exc:
        raise RunRefused(str(exc.args[0] if exc.args else exc)) from exc
    return cfg


def _anthropic_client() -> Any:
    """The only real client. ``max_retries=0``: the metered gateway retries, so
    every attempt is reserved and settled in the ledger."""
    import anthropic
    return anthropic.Anthropic(max_retries=0)


def pilot(config: Path | None, sdk: Any = None, root: Path = REPO_ROOT) -> dict[str, Any]:
    cfg = _armed_config(config, "pilot", root)
    from experiments.control_eval import study_runner as sr
    if cfg.pilot_out.exists():
        earlier = json.loads(cfg.pilot_out.read_text(encoding="utf-8"))
        if earlier.get("run_id") != cfg.run_id:
            raise RunRefused(f"{cfg.pilot_out} holds pilot {earlier.get('run_id')!r}; "
                             "a pilot never overwrites another")
    try:
        suites = sr.load_dev_suites(cfg.pilot_suites)
    except sr.ConfigRefused as exc:
        raise RunRefused(str(exc)) from exc
    episodes = sr.pilot_episodes(cfg, suites)
    result = sr.run_episodes(cfg, "pilot", episodes, suites, sdk or _anthropic_client())
    report = sr.summarize_pilot(cfg, result)
    cfg.pilot_out.parent.mkdir(parents=True, exist_ok=True)
    cfg.pilot_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def sealed_test(config: Path | None, sdk: Any = None, root: Path = REPO_ROOT,
                resume: bool = False, fetch: Any = None) -> dict[str, Any]:
    cfg = _armed_config(config, "test", root)
    from experiments.control_eval import readiness, sealed_run
    try:
        config_rel = Path(cfg.path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError as exc:
        raise RunRefused(f"run config {cfg.path} is outside {root}; it must be sealed") from exc
    gates = readiness.check_readiness(cfg.raw, root, fetch, config_path=config_rel)
    if not resume and not readiness.all_pass(gates):
        raise RunRefused("readiness gates do not all pass:\n" + readiness.render(gates))
    r = cfg.readiness
    manifest = root / r["manifest"]
    required = readiness.sealed_dependencies(cfg.raw, root, config_rel)
    try:
        body = sealed_run.check_test_start(manifest, root, required, cfg.run_id, resume=resume)
    except sealed_run.SealRefused as exc:
        raise RunRefused(str(exc)) from exc
    from experiments.control_eval import study_runner as sr
    suites = sr.load_test_suites()
    episodes = sr.sealed_test_episodes(suites, int(body["planned_pairs"]))
    benign = sum(1 for e in episodes if e.injection_task is None)
    if body.get("planned_benign_tasks") != benign:
        # G6 projected the cost with the manifest's count; the run must use the same.
        raise RunRefused(f"manifest planned_benign_tasks {body.get('planned_benign_tasks')!r} "
                         f"differs from the {benign} benign test tasks the run would use")
    try:
        body = sealed_run.start_test_run(manifest, root, required, cfg.run_id, resume=resume)
    except sealed_run.SealRefused as exc:
        raise RunRefused(str(exc)) from exc
    result = sr.run_episodes(cfg, "test", episodes, suites, sdk or _anthropic_client())
    out = root / r.get("result", "artifacts/control_eval/test_result_v1.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({k: v for k, v in result.items()}, indent=2, sort_keys=True,
                              default=str) + "\n", encoding="utf-8")
    sealed_run.finish_test_run(manifest, cfg.run_id, result_file=str(out.relative_to(root)),
                               stopped_by_budget=result["stopped_by_budget"])
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--split", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--pilot", action="store_true")
    mode.add_argument("--test", action="store_true")
    parser.add_argument("--config", type=Path, help="owner-approved run config (JSON)")
    parser.add_argument("--resume", action="store_true", help="--test: continue a crashed run")
    parser.add_argument("--out", type=Path, help="write the JSON report here")
    args = parser.parse_args(argv)
    try:
        if args.pilot:
            body = pilot(args.config)
        elif args.test:
            body = sealed_test(args.config, resume=args.resume)
        else:
            body = split() if args.split else dry_run()
    except RunRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(body, indent=2, sort_keys=True, default=str) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
