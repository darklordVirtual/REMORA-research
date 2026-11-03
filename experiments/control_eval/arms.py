# SPDX-License-Identifier: BUSL-1.1
"""Arm registry for the control evaluation runner.

The runner builds every arm named in the run config from this registry, per
suite and episode. An arm is a factory ``(ArmContext) -> Defence``. New arms
register with :func:`register_arm` from their own module and are listed in
:data:`ARM_MODULES` so the runner imports them; the REMORA IFC arms
(``E_IFC``, ``E_IFC_WS1``) register this way from ``remora_ifc.py``.
:func:`validate_arms` loads those modules and refuses an unknown arm name;
the runner calls it before it builds an SDK client.

Factories that need REMORA import it inside the factory, so this module and
the non-REMORA arms import nothing beyond the policies.
"""
from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from experiments.control_eval.policies import (
    Defence,
    LLMMonitor,
    NoGate,
    ProposedCall,
    RefuseAll,
    TaskAllowlist,
    ToolSpec,
)


@dataclass(frozen=True)
class ArmContext:
    suite: str
    tools: tuple[ToolSpec, ...]
    #: user task id -> function names of its ground-truth calls (arm C only).
    allowlist: Mapping[str, Sequence[str]] = field(default_factory=dict)
    #: Arm D's scorer; ``None`` when no monitor is configured.
    monitor_scorer: Callable[[ProposedCall], float] | None = None
    monitor_threshold: float = 50.0
    extra: Mapping[str, Any] = field(default_factory=dict)


ArmFactory = Callable[[ArmContext], Defence]
ARM_REGISTRY: dict[str, ArmFactory] = {}
#: Modules imported by :func:`load_arm_modules` so their arms register.
ARM_MODULES: list[str] = ["experiments.control_eval.remora_ifc"]
#: Arms that call a model when they decide; their cost is metered per arm.
MODEL_CALLING_ARMS: set[str] = set()


class UnknownArm(KeyError):
    pass


def register_arm(name: str, *, calls_model: bool = False) -> Callable[[ArmFactory], ArmFactory]:
    def wrap(factory: ArmFactory) -> ArmFactory:
        if name in ARM_REGISTRY and ARM_REGISTRY[name] is not factory:
            raise ValueError(f"arm {name!r} is already registered")
        ARM_REGISTRY[name] = factory
        if calls_model:
            MODEL_CALLING_ARMS.add(name)
        return factory
    return wrap


def load_arm_modules(modules: Sequence[str] = ()) -> None:
    for module in [*ARM_MODULES, *modules]:
        importlib.import_module(module)


def validate_arms(names: Sequence[str]) -> None:
    """Load every arm module, then refuse any name that is not registered."""
    load_arm_modules()
    unknown = [n for n in names if n not in ARM_REGISTRY]
    if unknown:
        raise UnknownArm(f"arms {unknown} are not registered; known: {sorted(ARM_REGISTRY)}")
    if len(set(names)) != len(names):
        raise UnknownArm(f"arms are listed twice: {list(names)}")


def build_arm(name: str, ctx: ArmContext) -> Defence:
    if name not in ARM_REGISTRY:
        raise UnknownArm(f"arm {name!r} is not registered; known: {sorted(ARM_REGISTRY)}")
    defence = ARM_REGISTRY[name](ctx)
    # The registry name is what the logs and the analysis key on.
    defence.name = name
    return defence


@register_arm("A_none")
def _a(ctx: ArmContext) -> Defence:
    return NoGate()


@register_arm("B_refuse_all")
def _b(ctx: ArmContext) -> Defence:
    return RefuseAll()


@register_arm("C_allowlist")
def _c(ctx: ArmContext) -> Defence:
    return TaskAllowlist(ctx.allowlist)


@register_arm("D_monitor", calls_model=True)
def _d(ctx: ArmContext) -> Defence:
    if ctx.monitor_scorer is None:
        raise ValueError("D_monitor needs a monitor scorer")
    return LLMMonitor(ctx.monitor_scorer, ctx.monitor_threshold)


@register_arm("E1_remora_strict")
def _e1(ctx: ArmContext) -> Defence:
    from experiments.control_eval.remora_adapter import STRICT, RemoraGate
    return RemoraGate(ctx.tools, STRICT, ctx.suite)
