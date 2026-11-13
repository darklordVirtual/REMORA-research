# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The policy what-if for an embedding host: what would it take to reach a verdict?

:func:`remora.sdk.evaluate_policy` gives a host the policy decision on an
observation. :func:`what_if` gives the next answer a reviewer asks for: which
smallest sets of declared facts would move the same observation to a target
verdict, whether model signals or the agent alone could get there, and which
hard guard is firing. It is :func:`remora.policy.whatif.what_if` behind the
stable surface, unchanged: a bounded, exhaustive search over the lever
catalogue, read-only over the engine.

Like :func:`evaluate_policy` it is **pure**: the engine reads no wall clock and
no random source, so one observation and one set of options always give the
same report. The report is an analysis of the policy, **not an authorization**:
it carries no token, grant or lease, and the only way to obtain a verdict it
names is to establish the named facts and be assessed again on the governed
path.

:class:`EngineOptions` names the engine flags to analyse under, so a host
asks the policy that actually governs its traffic.
:meth:`EngineOptions.execution_surface` is the flag set ``/v1/execution``
builds its engine with (execution profile on, strict monotonicity on), with
the operator's opt-in ACCEPT paths as arguments. The options choose engine
behaviour only; no credential or configuration is read here.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction
from remora.policy.whatif import WhatIfReport

if TYPE_CHECKING:
    from remora.policy.decision_engine import RemoraDecisionEngine


@dataclass(frozen=True)
class EngineOptions:
    """The decision-engine flags an analysis runs under.

    Each field is the ``RemoraDecisionEngine`` argument of the same name and
    defaults to the library default (all off). The opt-in ACCEPT paths are
    documented on the engine and in ``docs/deployment/execution-quickstart.md``.
    """

    execution_profile: bool = False
    strict_monotone: bool = False
    low_consequence_accept: bool = False
    grounded_read_accept: bool = False
    grounded_read_in_production: bool = False
    bounded_write_accept: bool = False
    bounded_write_medium_tier: bool = False
    bounded_write_intent_optional: bool = False

    @classmethod
    def execution_surface(
        cls,
        *,
        low_consequence_accept: bool = False,
        grounded_read_accept: bool = False,
        grounded_read_in_production: bool = False,
        bounded_write_accept: bool = False,
        bounded_write_medium_tier: bool = False,
        bounded_write_intent_optional: bool = False,
        strict_monotone: bool = True,
    ) -> EngineOptions:
        """The flags of the engine ``/v1/execution`` decides with.

        The execution profile is always on there. Strict monotonicity is on
        unless ``REMORA_STRICT_MONOTONE=0``. The remaining arguments are the
        operator's opt-in paths, each off unless its variable is set (for the
        bounded-write path: ``REMORA_BOUNDED_WRITE_ACCEPT``,
        ``REMORA_BOUNDED_WRITE_MAX_TIER=medium`` and
        ``REMORA_BOUNDED_WRITE_REQUIRE_INTENT=0``). Pass the values the
        deployment runs with; nothing is read from the environment here.
        """
        return cls(
            execution_profile=True,
            strict_monotone=strict_monotone,
            low_consequence_accept=low_consequence_accept,
            grounded_read_accept=grounded_read_accept,
            grounded_read_in_production=grounded_read_in_production,
            bounded_write_accept=bounded_write_accept,
            bounded_write_medium_tier=bounded_write_medium_tier,
            bounded_write_intent_optional=bounded_write_intent_optional,
        )


@lru_cache(maxsize=16)
def _engine(options: EngineOptions) -> RemoraDecisionEngine:
    # Pure engines (no clock, no random source), so one per flag set is shared
    # without changing any result.
    from remora.policy.decision_engine import RemoraDecisionEngine

    return RemoraDecisionEngine(**dataclasses.asdict(options))


def what_if(
    observation: PolicyObservation,
    *,
    target: DecisionAction | str = DecisionAction.ACCEPT,
    max_depth: int = 4,
    max_evaluations: int = 20_000,
    engine_options: EngineOptions | None = None,
) -> WhatIfReport:
    """Report what would have to change for *observation* to reach *target*.

    ``target`` is ``accept`` (what autonomy would take) or ``verify`` (what
    would put an ABSTAINed call in front of a person); the enum or its value.
    ``max_depth`` caps how many levers one change set combines and
    ``max_evaluations`` the distinct engine calls; the report says whether the
    space was exhausted. ``engine_options`` defaults to the library engine.

    The observation is not modified. ``WhatIfReport.to_dict()`` is JSON-ready.

    Raises:
        ValueError: On a bound below 1 or a target that is not a decision action.
    """
    from remora.policy.whatif import what_if as _what_if

    action = target if isinstance(target, DecisionAction) else DecisionAction(str(target))
    return _what_if(
        observation,
        _engine(engine_options or EngineOptions()),
        target=action,
        max_depth=max_depth,
        max_evaluations=max_evaluations,
    )


__all__ = ["EngineOptions", "WhatIfReport", "what_if"]
