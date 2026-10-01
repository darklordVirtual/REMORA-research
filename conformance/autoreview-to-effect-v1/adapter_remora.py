# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REMORA adapter for the AutoReview-to-Effect benchmark.

Built on the decision-to-effect-v1 REMORA adapter, which is imported and not
modified: approval issues the same signed PDP grant and execution lease, and
dispatch goes through the same ``GovernedToolDispatcher``. What this adapter
adds is the dispatching identity as a parameter (AR-02) and a second
registered tool with identical behaviour (AR-03).

The refusal-reason map extends the decision-to-effect map by one entry,
``actor_identity_mismatch``. Anything else unmapped is reported as
``UNMAPPED:<reason>`` rather than guessed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from remora.enforcement.lease import GovernedToolDispatcher

D2E = Path(__file__).resolve().parent.parent / "decision-to-effect-v1"


def _load_d2e_adapter() -> Any:
    name = "decision_to_effect_v1_adapter_remora"
    if name in sys.modules:
        return sys.modules[name]
    # adapter_remora.py in decision-to-effect-v1 imports nothing from its own
    # directory, so loading it by path does not need that directory on sys.path.
    spec = importlib.util.spec_from_file_location(name, D2E / "adapter_remora.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {D2E / 'adapter_remora.py'}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_d2e = _load_d2e_adapter()

REASON_CLASS = {
    **_d2e.REASON_CLASS,
    "actor_identity_mismatch": "IDENTITY_MISMATCH",
    "actor_identity_required": "IDENTITY_MISMATCH",
}


def _classify(reason: str) -> str:
    return REASON_CLASS.get(reason, f"UNMAPPED:{reason}")


class RemoraAutoReviewAdapter:
    name = "remora"

    def __init__(self) -> None:
        self._inner = _d2e.RemoraAdapter()
        self.version = self._inner.version
        self.reset()

    def reset(self) -> None:
        self._inner.reset()
        self._alternates: list[str] = []

    def approve(self, call: dict[str, Any]) -> str:
        return self._inner.authorize(call, audience="pep-a")

    def _dispatcher(self) -> GovernedToolDispatcher:
        inner = self._inner
        if inner._bundle == _d2e.BUNDLE_A:
            return inner._dispatcher
        dispatcher = GovernedToolDispatcher(expected_policy_bundle_hash=inner._bundle)
        dispatcher.bind_toolspec_identity(lambda _name: inner._spec)
        dispatcher.register("transfer_funds", inner._tool)
        for tool in self._alternates:
            dispatcher.register(tool, inner._tool)
        return dispatcher

    def dispatch(
        self, handle: str, call: dict[str, Any], *, actor: str | None = None
    ) -> str:
        _token, lease, _meta = self._inner._grants[handle]
        result = self._dispatcher().dispatch(
            lease,
            call["name"],
            call["arguments"],
            tenant_id=call["tenant"],
            target_environment=call["target"],
            actor_identity=actor if actor is not None else _d2e.PRINCIPAL,
        )
        if result.executed:
            return "EXECUTED"
        return _classify(result.refusal_reason or "")

    def register_alternate_tool(self, tool: str) -> None:
        # Same body as transfer_funds: if it runs, it moves money and is
        # counted as an execution.
        self._alternates.append(tool)
        self._inner._dispatcher.register(tool, self._inner._tool)

    def change_policy_bundle(self) -> None:
        self._inner.change_policy_bundle()

    def verify_effect(
        self, handle: str, observed: dict[str, Any], *, claimed: dict[str, Any]
    ) -> str:
        # ``claimed`` is deliberately not passed on. REMORA's verifier compares
        # the declared postcondition against the observed read-back only.
        del claimed
        return self._inner.verify_effect(handle, observed)

    def executions(self) -> int:
        return len(self._inner._executed)


def build() -> RemoraAutoReviewAdapter:
    return RemoraAutoReviewAdapter()
