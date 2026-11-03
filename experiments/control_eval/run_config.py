# SPDX-License-Identifier: BUSL-1.1
"""The owner's run config for ``--pilot`` and ``--test`` (gate G2).

A run refuses to start without one. The config names the models, their
prices per million tokens, effort and ``max_tokens``, the monitor prompt,
the budget caps and ledger, the arms, and the suites held out from
development. ``owner_approved`` must be true: the committed example is not.

``holdout_suites`` lists suites kept out of all development as a transfer
test (lead decision 2026-11-03: ``workspace``). ``--pilot`` refuses to run a
held-out suite; ``--test`` still runs every suite's test pairs.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from experiments.control_eval.spend_ledger import DEFAULT_TOTAL_CAP_USD, PriceTable

ALL_SUITES = ("banking", "slack", "travel", "workspace")
PHASES = ("pilot", "test")


class ConfigRefused(ValueError):
    """The run config is missing, incomplete or not approved."""


@dataclass(frozen=True)
class ModelSpec:
    model: str
    max_tokens: int
    effort: str | None


@dataclass(frozen=True)
class RunConfig:
    path: Path
    run_id: str
    agent: ModelSpec
    monitor: ModelSpec
    monitor_prompt_path: Path
    monitor_threshold: float
    prices: PriceTable
    price_raw: Mapping[str, Any]
    total_cap_usd: float
    phase_caps_usd: Mapping[str, float]
    ledger_path: Path
    cache_dir: Path
    arms: tuple[str, ...]
    holdout_suites: tuple[str, ...]
    pilot_suites: tuple[str, ...]
    pilot_user_tasks_per_suite: int
    pilot_injection_tasks_per_user_task: int
    pilot_out: Path
    max_iters: int
    readiness: Mapping[str, Any]
    raw: Mapping[str, Any]

    @property
    def monitor_prompt(self) -> str:
        return self.monitor_prompt_path.read_text(encoding="utf-8")

    def require_pilot_suites(self, suites: Sequence[str]) -> None:
        held = sorted(set(suites) & set(self.holdout_suites))
        if held:
            raise ConfigRefused(f"--pilot refuses held-out suites {held}; "
                                f"holdout_suites = {list(self.holdout_suites)}")


def _need(raw: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in raw or raw[key] in (None, ""):
        raise ConfigRefused(f"run config: {where}{key} is required")
    return raw[key]


def _model(raw: Mapping[str, Any], where: str) -> ModelSpec:
    max_tokens = int(_need(raw, "max_tokens", where))
    if max_tokens <= 0:
        raise ConfigRefused(f"run config: {where}max_tokens must be positive")
    if "temperature" in raw or "budget_tokens" in raw:
        raise ConfigRefused(f"run config: {where} sets temperature or budget_tokens, which the "
                            "current Claude models reject")
    return ModelSpec(str(_need(raw, "model", where)), max_tokens, raw.get("effort"))


def load_run_config(path: Path | None, root: Path) -> RunConfig:
    if path is None:
        raise ConfigRefused("a run config (--config) is required: model IDs, prices, effort, "
                            "max_tokens and the monitor prompt")
    path = Path(path)
    if not path.is_file():
        raise ConfigRefused(f"run config {path} does not exist")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ConfigRefused(f"run config {path} is not JSON: {exc}") from exc
    if raw.get("owner_approved") is not True:
        raise ConfigRefused("run config is not owner_approved; the example config never is")
    agent = _model(_need(raw, "agent", ""), "agent.")
    mon_raw = _need(raw, "monitor", "")
    monitor = _model(mon_raw, "monitor.")
    prompt = root / str(_need(mon_raw, "prompt", "monitor."))
    if not prompt.is_file():
        raise ConfigRefused(f"monitor prompt {prompt} does not exist")
    prices_raw = _need(raw, "prices_usd_per_mtok", "")
    prices = PriceTable(prices_raw)
    for spec in (agent, monitor):
        prices.price(spec.model)
    budget = _need(raw, "budget", "")
    total = float(budget.get("total_cap_usd", DEFAULT_TOTAL_CAP_USD))
    caps = {k: float(v) for k, v in _need(budget, "phase_caps_usd", "budget.").items()}
    if set(caps) - set(PHASES):
        raise ConfigRefused(f"unknown phases in budget.phase_caps_usd: {sorted(set(caps) - set(PHASES))}")
    if total > DEFAULT_TOTAL_CAP_USD:
        raise ConfigRefused(f"total_cap_usd {total} exceeds the owner's {DEFAULT_TOTAL_CAP_USD} USD")
    if sum(caps.values()) > total + 1e-9:
        raise ConfigRefused("phase sub-caps add up to more than the total cap")
    holdout = tuple(raw.get("holdout_suites", ()))
    unknown = sorted(set(holdout) - set(ALL_SUITES))
    if unknown:
        raise ConfigRefused(f"unknown holdout suites {unknown}")
    pilot = raw.get("pilot", {})
    pilot_suites = tuple(pilot.get("suites") or [s for s in ALL_SUITES if s not in holdout])
    cfg = RunConfig(
        path=path, run_id=str(_need(raw, "run_id", "")), agent=agent, monitor=monitor,
        monitor_prompt_path=prompt, monitor_threshold=float(_need(mon_raw, "threshold", "monitor.")),
        prices=prices, price_raw=prices_raw, total_cap_usd=total, phase_caps_usd=caps,
        ledger_path=root / str(_need(budget, "ledger", "budget.")),
        cache_dir=root / str(raw.get("cache_dir", "artifacts/control_eval/runs")),
        arms=tuple(_need(raw, "arms", "")), holdout_suites=holdout, pilot_suites=pilot_suites,
        pilot_user_tasks_per_suite=int(pilot.get("user_tasks_per_suite", 3)),
        pilot_injection_tasks_per_user_task=int(pilot.get("injection_tasks_per_user_task", 2)),
        pilot_out=root / str(pilot.get("out", "artifacts/control_eval/pilot_v1.json")),
        max_iters=int(raw.get("max_iters", 15)), readiness=raw.get("readiness", {}), raw=raw)
    cfg.require_pilot_suites(cfg.pilot_suites)
    return cfg
