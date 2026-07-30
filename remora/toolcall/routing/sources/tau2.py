# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""tau2-bench adapter — policy/authority axis.

Upstream: https://github.com/sierra-research/tau2-bench (MIT, (c) Sierra Research)

Extracts native predicates only; the route comes from the frozen table. Each
predicate records the exact upstream field that determined it.

Native field mapping:

    tool_required        evaluation_criteria.actions non-empty
    call_in_gold_set     proposed call name in evaluation_criteria.actions[].name
    information_missing  user_scenario.instructions.unknown_info non-null
    policy_forbids       actions empty AND an nl_assertions entry matches
                         REFUSAL_PATTERN
    originates_from_untrusted   None — tau2 does not model untrusted content

One episode is a (task, proposed_call) pair. Tasks with gold actions yield one
positive episode per action plus one substituted negative, where the substitute
is a gold call drawn deterministically from a different task in the same
domain. Refusal tasks yield a single episode with no proposed call: there is no
natively annotated call to gate, and synthesizing one would mean authoring the
test this benchmark exists to source externally.

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from remora.toolcall.routing.episode import RoutingEpisode
from remora.toolcall.routing.predicates import NativePredicates, PredicateValue
from remora.toolcall.routing.route_table import (
    ROUTE_TABLE_VERSION,
    assign_route,
    matched_row,
)

DATASET = "tau2"

#: The one predicate derived from free text. Frozen and versioned; every firing
#: records the matched assertion verbatim so all of them can be read by hand.
#: See the design document for why this is admitted and under what constraints.
REFUSAL_PATTERN = re.compile(
    r"refus|not (be )?(allowed|possible)|deny|decline|should not",
    re.IGNORECASE,
)
REFUSAL_PATTERN_VERSION = "1"

#: Filenames to try per domain, in order. telecom ships tasks_small.json.
_TASK_FILES = ("tasks.json", "tasks_small.json")


def _silent(field: str) -> PredicateValue:
    """A predicate this source does not determine."""
    return PredicateValue(value=None, source_dataset=DATASET, source_field=field)


class Tau2Adapter:
    """Builds routing episodes from a tau2 domain tree.

    ``root`` contains one directory per domain, each holding a tasks file.
    """

    def __init__(self, root: Path, commit: str) -> None:
        self.root = Path(root)
        self.commit = commit

    # -- loading ---------------------------------------------------------

    def _domains(self) -> list[str]:
        return sorted(
            d.name
            for d in self.root.iterdir()
            if d.is_dir() and any((d / f).exists() for f in _TASK_FILES)
        )

    def _load(self, domain: str) -> list[dict[str, Any]]:
        for name in _TASK_FILES:
            path = self.root / domain / name
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        return []

    # -- predicate extraction --------------------------------------------

    @staticmethod
    def _actions(task: dict[str, Any]) -> list[dict[str, Any]]:
        return (task.get("evaluation_criteria") or {}).get("actions") or []

    @staticmethod
    def _assertions(task: dict[str, Any]) -> list[str]:
        return (task.get("evaluation_criteria") or {}).get("nl_assertions") or []

    @staticmethod
    def _unknown_info(task: dict[str, Any]) -> str | None:
        instructions = (task.get("user_scenario") or {}).get("instructions") or {}
        return instructions.get("unknown_info")

    @staticmethod
    def _user_task(task: dict[str, Any]) -> str:
        instructions = (task.get("user_scenario") or {}).get("instructions") or {}
        parts = [
            instructions.get("reason_for_call") or "",
            instructions.get("task_instructions") or "",
        ]
        text = "\n\n".join(p.strip() for p in parts if p.strip())
        return text or (task.get("description") or {}).get("purpose") or "(no text)"

    def _refusal_assertion(self, task: dict[str, Any]) -> str | None:
        """Return the assertion that states a refusal expectation, if any."""
        for assertion in self._assertions(task):
            if REFUSAL_PATTERN.search(assertion):
                return assertion
        return None

    def _predicates(
        self,
        task: dict[str, Any],
        *,
        proposed: str | None,
        gold_names: frozenset[str],
    ) -> NativePredicates:
        actions = self._actions(task)
        unknown = self._unknown_info(task)
        refusal = self._refusal_assertion(task) if not actions else None

        return NativePredicates(
            tool_required=PredicateValue(
                value=bool(actions) if (actions or refusal) else None,
                source_dataset=DATASET,
                source_field="evaluation_criteria.actions",
            ),
            call_in_gold_set=PredicateValue(
                value=(proposed in gold_names) if proposed is not None else None,
                source_dataset=DATASET,
                source_field="evaluation_criteria.actions[].name",
            ),
            originates_from_untrusted=_silent("(not modelled by tau2)"),
            information_missing=PredicateValue(
                value=True if unknown else None,
                source_dataset=DATASET,
                source_field="user_scenario.instructions.unknown_info",
            ),
            policy_forbids=PredicateValue(
                value=True if refusal else None,
                source_dataset=DATASET,
                source_field="evaluation_criteria.nl_assertions",
                matched_text=refusal,
            ),
        )

    # -- episode construction --------------------------------------------

    def _episode(
        self,
        *,
        domain: str,
        task: dict[str, Any],
        suffix: str,
        proposed_name: str | None,
        proposed_args: dict[str, Any],
        gold_names: frozenset[str],
        available: tuple[str, ...],
        notes: tuple[str, ...] = (),
    ) -> RoutingEpisode:
        predicates = self._predicates(
            task, proposed=proposed_name, gold_names=gold_names
        )
        route = assign_route(predicates)
        return RoutingEpisode(
            id=f"tau2:{domain}:{task['id']}:{suffix}",
            source_dataset=DATASET,
            source_commit=self.commit,
            cluster_id=f"tau2:{domain}:{task['id']}",
            user_task=self._user_task(task),
            available_tools=available,
            untrusted_context=None,
            proposed_tool_name=proposed_name,
            proposed_tool_args=proposed_args,
            domain=domain,
            predicates=predicates,
            route=route,
            route_table_version=ROUTE_TABLE_VERSION if route else "",
            matched_row=matched_row(predicates) if route else None,
            redistributable=True,
            notes=notes,
        )

    def build_episodes(self) -> list[RoutingEpisode]:
        """Build every episode, in a deterministic order."""
        episodes: list[RoutingEpisode] = []

        for domain in self._domains():
            tasks = self._load(domain)
            # Domain-wide pool of gold call names, used for substitution. Sorted
            # so the choice never depends on dict or file ordering.
            # Name -> a real argument set for that call, taken from the first
            # task that uses it. A substituted call must be shaped like a call
            # an agent would actually propose; leaving its arguments empty
            # would make it look unsatisfiable for a reason that is an artifact
            # of this adapter rather than a property of the call.
            pool_args: dict[str, dict[str, Any]] = {}
            for task in tasks:
                for action in self._actions(task):
                    name = action.get("name")
                    if name and name not in pool_args:
                        pool_args[name] = dict(action.get("arguments") or {})
            pool = sorted(pool_args)

            for task in tasks:
                actions = self._actions(task)
                gold_names = frozenset(
                    a["name"] for a in actions if a.get("name")
                )
                available = tuple(sorted(gold_names)) or ()

                if not actions:
                    # No natively annotated call. Emitted once, with none.
                    episodes.append(
                        self._episode(
                            domain=domain,
                            task=task,
                            suffix="no_call",
                            proposed_name=None,
                            proposed_args={},
                            gold_names=gold_names,
                            available=available,
                            notes=("no gold action; no call synthesized",),
                        )
                    )
                    continue

                for index, action in enumerate(actions):
                    episodes.append(
                        self._episode(
                            domain=domain,
                            task=task,
                            suffix=f"gold{index}",
                            proposed_name=action.get("name"),
                            proposed_args=dict(action.get("arguments") or {}),
                            gold_names=gold_names,
                            available=available,
                        )
                    )

                substitute = self._substitute(pool, gold_names, task["id"])
                if substitute is not None:
                    episodes.append(
                        self._episode(
                            domain=domain,
                            task=task,
                            suffix="substituted",
                            proposed_name=substitute,
                            proposed_args=dict(pool_args.get(substitute, {})),
                            gold_names=gold_names,
                            available=tuple(sorted(gold_names | {substitute})),
                            notes=(
                                "proposed call substituted from another task in "
                                "the same domain, with that call's arguments",
                            ),
                        )
                    )

        return episodes

    @staticmethod
    def _substitute(
        pool: list[str], gold_names: frozenset[str], task_id: str
    ) -> str | None:
        """Pick a call name absent from *gold_names*, deterministically.

        Seeded by the task id rather than a random generator, so the selection
        reproduces byte-identically without carrying RNG state.
        """
        candidates = [name for name in pool if name not in gold_names]
        if not candidates:
            return None
        seed = sum(ord(c) for c in task_id)
        return candidates[seed % len(candidates)]
