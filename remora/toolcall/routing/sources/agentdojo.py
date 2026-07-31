# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""AgentDojo adapter — the untrusted-content axis.

Upstream: https://github.com/ethz-spylab/agentdojo (MIT, (c) ETH Zurich SPY Lab)

AgentDojo defines tasks as Python classes, so this adapter AST-parses the
source. Importing the package would pull in its model-client dependencies
(openai, anthropic and others) for no benefit.

Statically extractable and verified against the pinned commit: the class name,
the ``PROMPT`` / ``GOAL`` / ``COMMENT`` assignments, and the ``function=`` names
inside ``FunctionCall(...)`` constructions in ``ground_truth()``.

Not statically extractable: argument *values*. ``ground_truth()`` computes them
from the environment at runtime, e.g.::

    FunctionCall(function="send_money",
                 args={"subject": "..." + self.get_streaming_service(env)})

Every predicate here depends on tool *names* and on whether a task is an
injection, never on argument values, so this is sufficient. Episodes record
``args_statically_unavailable=True`` so the limitation lives in the data rather
than only in the design document.

Native field mapping:

    tool_required              ground_truth() names at least one call
    call_in_gold_set           the proposed call is one of those names
    originates_from_untrusted  True for injection tasks, False for user tasks
    information_missing        None — not modelled
    policy_forbids             None — not modelled

Upstream refactoring will break AST extraction. That is detected rather than
silent: the real-suite tests assert exact task counts, so a parser that starts
returning fewer episodes fails instead of quietly shrinking the benchmark.

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

import ast
from pathlib import Path

from remora.toolcall.routing.episode import RoutingEpisode
from remora.toolcall.routing.predicates import NativePredicates, PredicateValue
from remora.toolcall.routing.route_table import (
    ROUTE_TABLE_VERSION,
    assign_route,
    matched_row,
)

DATASET = "agentdojo"


def _silent(field: str) -> PredicateValue:
    return PredicateValue(value=None, source_dataset=DATASET, source_field=field)


def _literal_text(node: ast.AST) -> str | None:
    """Recover the literal text of a string expression.

    Handles the three shapes AgentDojo actually uses: a plain string, an
    f-string, and ``+`` concatenation of either (slack UserTask4 and UserTask16
    build PROMPT that way). Interpolated values are dropped rather than
    guessed — the literal segments carry the meaning, and this text is only
    ever used as observable context, never as a label.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_text(node.left) or ""
        right = _literal_text(node.right) or ""
        return (left + right) or None
    return None


def _string_assignment(cls: ast.ClassDef, name: str) -> str | None:
    """Return a class-level ``name = <string expression>`` as literal text."""
    for node in cls.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", None) == name for t in node.targets):
            continue
        text = _literal_text(node.value)
        if text:
            return text.strip()
    return None


def _ground_truth_calls(cls: ast.ClassDef) -> tuple[str, ...]:
    """Function names in FunctionCall(...) constructions inside ground_truth()."""
    names: list[str] = []
    for node in cls.body:
        if not (isinstance(node, ast.FunctionDef) and node.name == "ground_truth"):
            continue
        for call in ast.walk(node):
            if not (
                isinstance(call, ast.Call)
                and getattr(call.func, "id", None) == "FunctionCall"
            ):
                continue
            for kw in call.keywords:
                if (
                    kw.arg == "function"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                    and kw.value.value not in names
                ):
                    names.append(kw.value.value)
    return tuple(names)


class AgentDojoAdapter:
    """Builds routing episodes from AgentDojo suite directories."""

    def __init__(self, root: Path, commit: str) -> None:
        self.root = Path(root)
        self.commit = commit

    def _suites(self) -> list[str]:
        return sorted(
            d.name
            for d in self.root.iterdir()
            if d.is_dir() and (d / "user_tasks.py").exists()
        )

    @staticmethod
    def _classes(path: Path) -> list[ast.ClassDef]:
        if not path.exists():
            return []
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return [n for n in tree.body if isinstance(n, ast.ClassDef)]

    def build_episodes(self) -> list[RoutingEpisode]:
        episodes: list[RoutingEpisode] = []

        for suite in self._suites():
            user_classes = self._classes(self.root / suite / "user_tasks.py")
            injection_classes = self._classes(self.root / suite / "injection_tasks.py")

            benign: list[tuple[str, str, tuple[str, ...]]] = []
            for cls in user_classes:
                prompt = _string_assignment(cls, "PROMPT")
                calls = _ground_truth_calls(cls)
                if not prompt or not calls:
                    continue
                benign.append((cls.name, prompt, calls))
                episodes.append(
                    self._episode(
                        suite=suite,
                        kind="user",
                        task_name=cls.name,
                        user_task=prompt,
                        available=calls,
                        proposed=calls[0],
                        untrusted_context=None,
                        tool_required=True,
                        call_in_gold_set=True,
                        untrusted=False,
                    )
                )

            for index, cls in enumerate(injection_classes):
                goal = _string_assignment(cls, "GOAL")
                calls = _ground_truth_calls(cls)
                if not goal:
                    continue
                # A task whose ground_truth() builds calls dynamically (travel
                # InjectionTask6) still belongs in the benchmark: the injection
                # exists regardless of which call it targets, and row 2 fires on
                # untrusted origin alone. Emitting it with no proposed call is
                # more faithful than dropping it and shrinking the untrusted axis.
                dynamic_only = not calls
                # Pair the injected goal with a benign task from the same suite,
                # chosen by position so the pairing reproduces byte-identically.
                if benign:
                    host_prompt = benign[index % len(benign)][1]
                    host_tools = benign[index % len(benign)][2]
                else:
                    host_prompt = goal
                    host_tools = ()
                episodes.append(
                    self._episode(
                        suite=suite,
                        kind="injection",
                        task_name=cls.name,
                        user_task=host_prompt,
                        available=tuple(sorted(set(host_tools) | set(calls))),
                        proposed=calls[0] if calls else None,
                        untrusted_context=goal,
                        # The attacker's call is not part of the host task's
                        # gold set; AgentDojo annotates it as the attack target.
                        # With no statically recoverable call, membership is
                        # unknown rather than false.
                        tool_required=True,
                        call_in_gold_set=None if dynamic_only else False,
                        untrusted=True,
                        notes=(
                            ("injection target built dynamically upstream; "
                             "no static call name",)
                            if dynamic_only
                            else ()
                        ),
                    )
                )

        return episodes

    def _episode(
        self,
        *,
        suite: str,
        kind: str,
        task_name: str,
        user_task: str,
        available: tuple[str, ...],
        proposed: str | None,
        untrusted_context: str | None,
        tool_required: bool,
        call_in_gold_set: bool | None,
        untrusted: bool,
        notes: tuple[str, ...] = (),
    ) -> RoutingEpisode:
        predicates = NativePredicates(
            tool_required=PredicateValue(
                value=tool_required,
                source_dataset=DATASET,
                source_field="ground_truth()",
            ),
            call_in_gold_set=PredicateValue(
                value=call_in_gold_set,
                source_dataset=DATASET,
                source_field="ground_truth().FunctionCall(function=...)",
            ),
            originates_from_untrusted=PredicateValue(
                value=untrusted,
                source_dataset=DATASET,
                source_field="injection_tasks.py:GOAL",
            ),
            information_missing=_silent("(not modelled by AgentDojo)"),
            policy_forbids=_silent("(not modelled by AgentDojo)"),
        )
        route = assign_route(predicates)
        return RoutingEpisode(
            id=f"agentdojo:{suite}:{kind}:{task_name}",
            source_dataset=DATASET,
            source_commit=self.commit,
            cluster_id=f"agentdojo:{suite}:{kind}:{task_name}",
            user_task=user_task,
            available_tools=available,
            untrusted_context=untrusted_context,
            proposed_tool_name=proposed,
            proposed_tool_args={},
            domain=suite,
            args_statically_unavailable=True,
            predicates=predicates,
            route=route,
            route_table_version=ROUTE_TABLE_VERSION if route else "",
            matched_row=matched_row(predicates) if route else None,
            redistributable=True,
            notes=("arguments computed at runtime upstream; names only", *notes),
        )
