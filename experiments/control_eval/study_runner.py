# SPDX-License-Identifier: BUSL-1.1
"""Pilot and sealed runs of the control evaluation through AgentDojo.

Runs AgentDojo, so a run needs the pinned packages in ``requirements.txt``
(``scripts/run_control_eval.py`` and the local smoke test). AgentDojo is
imported inside the functions that run episodes, so the episode draws, the
suite loader and the stop rule are testable without it. The SDK client is a
parameter: the runner script passes an ``anthropic.Anthropic`` client, the
tests pass a scripted fake.

Only :class:`~experiments.control_eval.spend_ledger.CapReached` (a
reservation refused at a cap) stops a run normally. Every other ledger error
(missing usage, a corrupt ledger, a call above its reservation) propagates,
so ``--test`` leaves the manifest ``in_progress`` and ``--resume`` continues.

One *episode* is a user task with one injection task (attacked) or none
(benign). Every configured arm runs every episode, in the config's order,
with the same agent; responses are shared across arms while their requests
are identical (``response_cache``). Every model call is reserved against
the ledger before it is sent (``spend_ledger``). Each finished (episode,
arm) is appended to ``episodes.jsonl`` and its decisions to
``calls.jsonl`` in the run directory, so a resumed run skips what is done
and replays the cache for what is not.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from collections.abc import Callable
from typing import TypeVar

from experiments.control_eval.arms import (
    MODEL_CALLING_ARMS,
    ArmContext,
    build_arm,
    validate_arms,
)
from experiments.control_eval.gateway import EpisodeContext, MeteredModel, MonitorScorer
from experiments.control_eval.metrics import (
    SEED,
    V8_SEED,
    inspected_user_tasks,
    is_test_pair_allowed,
    split_tasks,
)
from experiments.control_eval.response_cache import ResponseCache
from experiments.control_eval.run_config import (
    ALL_SUITES,
    HELD_OUT_SUITES,
    ConfigRefused,
    RunConfig,
)
from experiments.control_eval.spend_ledger import CapReached, SpendLedger

#: Seed of the pilot's development draw (SAP v7 seed; development only).
PILOT_SEED = SEED
#: Seed of the stratified draw of attacked test pairs (SAP v8 §8).
TEST_PAIR_SEED = V8_SEED
T = TypeVar("T")

BENCHMARK_VERSION = "v1.2.2"
ATTACK = "important_instructions"


@dataclass(frozen=True)
class Episode:
    suite: str
    user_task: str
    injection_task: str | None

    def key(self, run_id: str) -> str:
        return f"{run_id}:{self.suite}:{self.user_task}:{self.injection_task or 'benign'}"


def _rank(*parts: str, seed: int = PILOT_SEED) -> str:
    return hashlib.sha256(":".join([str(seed), *parts]).encode()).hexdigest()


def pilot_episodes(cfg: RunConfig, suites: Mapping[str, Any]) -> list[Episode]:
    """Development tasks of the pilot suites only; never a held-out suite."""
    cfg.require_pilot_suites(list(suites))
    out: list[Episode] = []
    for name in cfg.pilot_suites:
        suite = suites[name]
        dev = split_tasks({name: list(suite.user_tasks)}, forced_dev=inspected_user_tasks())[name]["dev"]
        users = sorted(dev, key=lambda t: _rank("pilot", name, t))[:cfg.pilot_user_tasks_per_suite]
        injections = sorted(suite.injection_tasks, key=lambda t: _rank("pilot-inj", name, t))
        for u in sorted(users):
            out.append(Episode(name, u, None))
            for i in sorted(injections[:cfg.pilot_injection_tasks_per_user_task]):
                out.append(Episode(name, u, i))
    return out


def sealed_test_episodes(suites: Mapping[str, Any], planned_pairs: int) -> list[Episode]:
    """Every test user task benign, plus a suite-stratified seeded sample of allowed pairs."""
    pools: dict[str, list[Episode]] = {}
    benign: list[Episode] = []
    for name in ALL_SUITES:
        suite = suites[name]
        test = split_tasks({name: list(suite.user_tasks)}, forced_dev=inspected_user_tasks())[name]["test"]
        benign += [Episode(name, u, None) for u in test]
        pools[name] = sorted((Episode(name, u, i) for u in test for i in suite.injection_tasks
                              if is_test_pair_allowed(name, u, i)),
                             key=lambda e: _rank("test", e.suite, e.user_task,
                                                 e.injection_task or "", seed=TEST_PAIR_SEED))
    total = sum(len(p) for p in pools.values())
    if planned_pairs > total:
        raise ValueError(f"planned {planned_pairs} pairs but only {total} are allowed")
    quotas = {s: planned_pairs * len(p) / total for s, p in pools.items()}
    take = {s: int(q) for s, q in quotas.items()}
    for s in sorted(quotas, key=lambda s: (take[s] - quotas[s], s))[:planned_pairs - sum(take.values())]:
        take[s] += 1
    attacked = [e for s in ALL_SUITES for e in pools[s][:take[s]]]
    return benign + attacked


@dataclass
class RunState:
    run_dir: Path
    done: set[tuple[str, str]] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / "episodes.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.done.add((row["episode"], row["arm"]))

    def append(self, name: str, rows: Iterable[Mapping[str, Any]]) -> None:
        with (self.run_dir / name).open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")

    def rows(self) -> list[dict[str, Any]]:
        path = self.run_dir / "episodes.jsonl"
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _get_suite(name: str) -> Any:
    from agentdojo.task_suite.load_suites import get_suite
    return get_suite(BENCHMARK_VERSION, name)


def load_dev_suites(names: Sequence[str]) -> dict[str, Any]:
    """Suites for a development mode; a held-out suite is refused before it is loaded."""
    held = sorted(set(names) & HELD_OUT_SUITES)
    if held:
        raise ConfigRefused(f"development modes never load held-out suites {held}")
    return {n: _get_suite(n) for n in names}


def load_test_suites() -> dict[str, Any]:
    """Every suite, for the sealed ``--test`` path only."""
    return {n: _get_suite(n) for n in ALL_SUITES}


def until_cap(step: Callable[[], T]) -> tuple[T | None, str | None]:
    """Run *step*; a cap refusal is a normal stop, every other error propagates."""
    try:
        return step(), None
    except CapReached as exc:
        return None, str(exc)


def run_episodes(cfg: RunConfig, phase: str, episodes: Sequence[Episode], suites: Mapping[str, Any],
                 sdk: Any) -> dict[str, Any]:
    from agentdojo.agent_pipeline import (
        AgentPipeline,
        InitQuery,
        SystemMessage,
        ToolsExecutionLoop,
    )
    from agentdojo.agent_pipeline.agent_pipeline import load_system_message
    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.functions_runtime import FunctionsRuntime

    from experiments.control_eval.agentdojo_glue import (
        ClaudeAgent,
        GatedToolsExecutor,
        register_model_name,
        tool_specs,
    )

    validate_arms(cfg.arms)
    run_dir = cfg.cache_dir / cfg.run_id / phase
    state = RunState(run_dir)
    ledger = SpendLedger(cfg.ledger_path, cfg.prices, cfg.total_cap_usd, cfg.phase_caps_usd)
    cache = ResponseCache(run_dir / "responses.jsonl", cfg.run_id)
    model = MeteredModel(sdk, ledger, cache, phase)
    ctx = EpisodeContext()
    register_model_name(cfg.agent.model)
    agent = ClaudeAgent(model, cfg.agent, ctx)
    scorer = None
    if MODEL_CALLING_ARMS & set(cfg.arms):
        scorer = MonitorScorer(model, ctx, cfg.monitor.model, cfg.monitor_prompt,
                               cfg.monitor.max_tokens, cfg.monitor.effort)
    system = load_system_message(None)
    stopped: str | None = None
    by_suite: dict[str, list[Episode]] = defaultdict(list)
    for e in episodes:
        by_suite[e.suite].append(e)
    for suite_name, suite_eps in by_suite.items():
        suite = suites[suite_name]
        tools = tool_specs(FunctionsRuntime(suite.tools))
        env0 = suite.load_and_inject_default_environment({})
        allowlist = {u: [c.function for c in suite.get_user_task_by_id(u).ground_truth(env0)]
                     for u in sorted({e.user_task for e in suite_eps})}
        carrier = AgentPipeline([agent])
        carrier.name = cfg.agent.model
        attack = load_attack(ATTACK, suite, carrier)
        for ep in suite_eps:
            if stopped:
                break
            user_task = suite.get_user_task_by_id(ep.user_task)
            inj_task = suite.get_injection_task_by_id(ep.injection_task) if ep.injection_task else None
            injections = attack.attack(user_task, inj_task) if inj_task else {}
            key = ep.key(cfg.run_id)
            for arm in cfg.arms:
                if (key, arm) in state.done:
                    continue
                ctx.episode, ctx.arm = key, arm
                defence = build_arm(arm, ArmContext(suite_name, tools, allowlist, scorer,
                                                    cfg.monitor_threshold))
                log: list[dict[str, Any]] = []
                executor = GatedToolsExecutor(defence, suite=suite_name, user_task_id=ep.user_task,
                                              injection_task_id=ep.injection_task, log=log)
                pipe = AgentPipeline([SystemMessage(system), InitQuery(), agent,
                                      ToolsExecutionLoop([executor, agent], max_iters=cfg.max_iters)])
                pipe.name = cfg.agent.model
                before = len(model.records)
                outcome, stopped = until_cap(lambda: suite.run_task_with_pipeline(
                    pipe, user_task, inj_task, injections))  # noqa: B023 - called at once
                if stopped or outcome is None:
                    break
                utility, security = outcome
                recs = model.records[before:]
                row = {"episode": key, "suite": suite_name, "user_task": ep.user_task,
                       "injection_task": ep.injection_task, "arm": arm, "utility": bool(utility),
                       "attack_success": bool(security) if inj_task else None,
                       "calls": len(log), "blocked": sum(1 for c in log if not c["execute"]),
                       "spend_usd": sum(r.usd for r in recs),
                       "requests": len(recs), "sampled": sum(1 for r in recs if not r.cached),
                       "refusals": sum(1 for r in recs if r.stop_reason == "refusal"),
                       "monitor_scores": [c["score"] for c in log] if arm in MODEL_CALLING_ARMS else []}
                state.append("calls.jsonl", ({"episode": key, **c} for c in log))
                state.append("episodes.jsonl", [row])
                state.done.add((key, arm))
    episode_spend = ledger.spend_by_episode(phase)
    return {"phase": phase, "run_dir": str(run_dir), "stopped_by_budget": stopped,
            "rows": state.rows(), "gateway": model.summary(),
            "episodes_planned": len(episodes),
            "benign_planned": sum(1 for e in episodes if e.injection_task is None),
            # Spend per (episode, arm) from the ledger: counts calls made
            # before a crash, which a resumed run replays from cache for free.
            "ledger_spend_by_episode_arm": [
                {"episode": e, "arm": a, "usd": usd}
                for (e, a), usd in sorted(episode_spend.items())],
            "cache": {"hits": cache.hits, "misses": cache.misses},
            "monitor_failures": scorer.failures if scorer else [],
            "ledger": {"total_usd": ledger.totals().total_usd,
                       "phase_usd": ledger.totals().by_phase.get(phase, 0.0)}}


def ledger_spend(result: Mapping[str, Any]) -> dict[tuple[str, str], float]:
    return {(x["episode"], x["arm"]): float(x["usd"])
            for x in result.get("ledger_spend_by_episode_arm") or ()}


def summarize_pilot(cfg: RunConfig, result: Mapping[str, Any]) -> dict[str, Any]:
    """Pilot artifact. Every cost comes from the ledger, never from in-process records."""
    rows = result["rows"]
    episodes = {r["episode"] for r in rows}
    attacked = {r["episode"] for r in rows if r["injection_task"]}
    paid = ledger_spend(result)
    by_episode: dict[str, float] = defaultdict(float)
    for (episode, _arm), usd in paid.items():
        by_episode[episode] += usd
    spend = sum(by_episode[e] for e in episodes)
    spend_att = sum(by_episode[e] for e in attacked)
    by_arm: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        a = by_arm[r["arm"]]
        a["runs"] += 1
        a["spend_usd"] += paid.get((r["episode"], r["arm"]), 0.0)
        a["requests"] += r["requests"]
        a["sampled"] += r["sampled"]
        if r["injection_task"]:
            a["attacked"] += 1
            a["attack_successes"] += int(r["attack_success"])
            a["utility_under_attack"] += int(r["utility"])
        else:
            a["benign"] += 1
            a["utility"] += int(r["utility"])
    und = [r for r in rows if r["arm"] == "A_none" and r["injection_task"]]
    per_cluster: dict[str, list[int]] = defaultdict(list)
    for r in und:
        per_cluster[f"{r['suite']}:{r['user_task']}"].append(int(r["attack_success"]))
    requests = sum(r["requests"] for r in rows)
    sampled = sum(r["sampled"] for r in rows)
    return {
        "status": "pilot", "benchmark_version": BENCHMARK_VERSION, "attack": ATTACK,
        "run_id": cfg.run_id, "suites": list(cfg.pilot_suites),
        "holdout_suites": list(cfg.holdout_suites), "arms": list(cfg.arms),
        "agent": vars(cfg.agent), "monitor": vars(cfg.monitor),
        "prices_usd_per_mtok": cfg.price_raw,
        "episodes": len(episodes), "attacked_pairs": len(attacked),
        "stopped_by_budget": result["stopped_by_budget"],
        "cost": {
            "spent_usd": spend,
            "per_episode_usd": spend / len(episodes) if episodes else None,
            "per_attacked_pair_usd": spend_att / len(attacked) if attacked else None,
            "per_benign_task_usd": ((spend - spend_att) / (len(episodes) - len(attacked))
                                    if len(episodes) > len(attacked) else None),
            "unattributed_usd": sum(v for k, v in by_episode.items() if k not in episodes),
            "source": "spend ledger: settled and open reservations tagged with the episode",
            "note": "per episode = all arms of one episode; shared responses cost once",
        },
        "crn": {"requests": requests, "sampled": sampled, "shared": requests - sampled},
        "undefended": {"attack_successes": sum(int(r["attack_success"]) for r in und),
                       "attacked_pairs": len(und),
                       "per_cluster_rate": {k: sum(v) / len(v) for k, v in sorted(per_cluster.items())}},
        "by_arm": {k: dict(v) for k, v in by_arm.items()},
        "monitor_failures": len(result["monitor_failures"]),
        "thresholds": {"frozen": False, "tau_D_provisional": cfg.monitor_threshold},
    }
