# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""BFCL adapter — external blind routing on real-world tool-call tasks.

Upstream: https://github.com/ShishirPatil/gorilla (Apache-2.0, Berkeley
Function Calling Leaderboard v3). The *live* categories are real
user-submitted queries with full function schemas; ``live_simple`` annotates
one gold call per task, ``live_irrelevance`` annotates that **no** call is
correct.

Native field mapping:

    tool_required        live_simple → True; live_irrelevance → False
    call_in_gold_set     proposed name matches the annotated gold function
    information_missing  None — BFCL does not model it
    policy_forbids       None — BFCL does not model it
    originates_from_untrusted  None — BFCL does not model it

One gold episode per simple task (arguments taken from the annotated ground
truth, first allowed value per parameter), plus one substituted negative
(another task's gold call — knowably wrong, remedy unannotated, so
unlabelled). Irrelevance tasks yield one episode with no proposed call:
synthesizing one would author the test.

**Not judgeable on this track, declared upfront:** the wrong-argument value
axis. BFCL has no state table whose completeness anyone can vouch for, and
under the declaration rule (§30) that means no value-existence verdict is
available. The ground-truth argument lists are the *labels*; using them as a
system of record would score the answer key against itself.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from remora.toolcall.routing.episode import RoutingEpisode
from remora.toolcall.routing.predicates import NativePredicates, PredicateValue
from remora.toolcall.routing.route_table import (
    ROUTE_TABLE_VERSION,
    assign_route,
    matched_row,
)
from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature

DATASET = "bfcl"


def _silent(field: str) -> PredicateValue:
    return PredicateValue(value=None, source_dataset=DATASET, source_field=field)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _user_text(task: dict[str, Any]) -> str:
    turns = task.get("question") or []
    parts = [
        turn.get("content", "")
        for round_ in turns
        for turn in round_
        if isinstance(turn, dict) and turn.get("role") == "user"
    ]
    return "\n\n".join(p.strip() for p in parts if p.strip()) or "(no text)"


def _gold_call(answer: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The annotated call: function name plus first allowed value per param."""
    truths = answer.get("ground_truth") or []
    if not truths or not isinstance(truths[0], dict) or not truths[0]:
        return None
    name, params = next(iter(truths[0].items()))
    arguments = {
        param: allowed[0]
        for param, allowed in (params or {}).items()
        if isinstance(allowed, list) and allowed
    }
    return name, arguments


def bfcl_registry(paths: list[Path]) -> ToolRegistry:
    """Signatures from the function schemas the tasks themselves carry."""
    signatures: dict[str, ToolSignature] = {}
    for path in paths:
        for task in _load_jsonl(path):
            for schema in task.get("function") or []:
                name = schema.get("name")
                if not name or name in signatures:
                    continue
                required = tuple(
                    (schema.get("parameters") or {}).get("required") or ()
                )
                signatures[name] = ToolSignature(name=name, required_params=required)
    return ToolRegistry(signatures)


class BfclAdapter:
    """Builds routing episodes from BFCL live_simple + live_irrelevance."""

    def __init__(
        self,
        *,
        simple_path: Path,
        answers_path: Path,
        irrelevance_path: Path,
        commit: str,
    ) -> None:
        self.simple_path = Path(simple_path)
        self.answers_path = Path(answers_path)
        self.irrelevance_path = Path(irrelevance_path)
        self.commit = commit

    def _predicates(
        self, *, tool_required: bool, in_gold: bool | None
    ) -> NativePredicates:
        return NativePredicates(
            tool_required=PredicateValue(
                value=tool_required,
                source_dataset=DATASET,
                source_field="category (live_simple has gold call; live_irrelevance has none)",
            ),
            call_in_gold_set=PredicateValue(
                value=in_gold,
                source_dataset=DATASET,
                source_field="possible_answer.ground_truth[].name",
            ),
            originates_from_untrusted=_silent("(not modelled by BFCL)"),
            information_missing=_silent("(not modelled by BFCL)"),
            policy_forbids=_silent("(not modelled by BFCL)"),
        )

    def _episode(
        self,
        *,
        task: dict[str, Any],
        suffix: str,
        proposed_name: str | None,
        proposed_args: dict[str, Any],
        tool_required: bool,
        in_gold: bool | None,
        available: tuple[str, ...],
        notes: tuple[str, ...] = (),
    ) -> RoutingEpisode:
        predicates = self._predicates(tool_required=tool_required, in_gold=in_gold)
        route = assign_route(predicates)
        return RoutingEpisode(
            id=f"bfcl:{task['id']}:{suffix}",
            source_dataset=DATASET,
            source_commit=self.commit,
            cluster_id=f"bfcl:{task['id']}",
            user_task=_user_text(task),
            available_tools=available,
            untrusted_context=None,
            proposed_tool_name=proposed_name,
            proposed_tool_args=proposed_args,
            domain="bfcl_live",
            predicates=predicates,
            route=route,
            route_table_version=ROUTE_TABLE_VERSION if route else "",
            matched_row=matched_row(predicates) if route else None,
            redistributable=True,  # Apache-2.0 upstream
            notes=notes,
        )

    def build_episodes(self) -> list[RoutingEpisode]:
        episodes: list[RoutingEpisode] = []

        simple = _load_jsonl(self.simple_path)
        answers = {a["id"]: a for a in _load_jsonl(self.answers_path)}

        # Deterministic pool of gold calls for substitution, keyed by name.
        pool: dict[str, dict[str, Any]] = {}
        for task in simple:
            gold = _gold_call(answers.get(task["id"], {}))
            if gold and gold[0] not in pool:
                pool[gold[0]] = gold[1]
        pool_names = sorted(pool)

        for task in simple:
            gold = _gold_call(answers.get(task["id"], {}))
            if gold is None:
                continue
            name, arguments = gold
            available = tuple(
                sorted(
                    {s["name"] for s in task.get("function") or [] if s.get("name")}
                    | {name}
                )
            )
            episodes.append(
                self._episode(
                    task=task,
                    suffix="gold",
                    proposed_name=name,
                    proposed_args=arguments,
                    tool_required=True,
                    in_gold=True,
                    available=available,
                )
            )
            substitute = self._substitute(pool_names, name, task["id"])
            if substitute is not None:
                episodes.append(
                    self._episode(
                        task=task,
                        suffix="substituted",
                        proposed_name=substitute,
                        proposed_args=dict(pool[substitute]),
                        tool_required=True,
                        in_gold=False,
                        available=tuple(sorted(set(available) | {substitute})),
                        notes=(
                            "proposed call substituted from another task's gold "
                            "set, with that call's arguments",
                        ),
                    )
                )

        for task in _load_jsonl(self.irrelevance_path):
            available = tuple(
                sorted(s["name"] for s in task.get("function") or [] if s.get("name"))
            )
            episodes.append(
                self._episode(
                    task=task,
                    suffix="irrelevance",
                    proposed_name=None,
                    proposed_args={},
                    tool_required=False,
                    in_gold=None,
                    available=available,
                    notes=("no call is correct; none synthesized",),
                )
            )

        return episodes

    @staticmethod
    def _substitute(pool: list[str], gold_name: str, task_id: str) -> str | None:
        candidates = [name for name in pool if name != gold_name]
        if not candidates:
            return None
        seed = sum(ord(c) for c in task_id)
        return candidates[seed % len(candidates)]
