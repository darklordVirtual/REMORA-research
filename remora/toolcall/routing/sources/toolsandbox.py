# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""ToolSandbox adapter — the ABSTAIN axis.

Upstream: https://github.com/apple/ToolSandbox

**Licensing.** ToolSandbox is distributed under Apple's own terms, not an OSI
license. Neither its source nor anything derived from it is committed to this
repository: every episode this adapter produces carries
``redistributable=False``, and ``scripts/build_routing_bench.py`` writes only
redistributable episodes to ``data/``. Build and evaluate locally.

**Why this source exists.** No other admitted dataset annotates "no tool call is
correct here" in volume, so without it the ABSTAIN route has no support and the
benchmark cannot make any claim about it.

Native field mapping (scenarios are Python, so the module is AST-parsed rather
than imported; importing would require ToolSandbox's runtime dependencies):

    tool_required        milestones == []  ->  False
                         milestones non-empty  ->  True
    call_in_gold_set     a minefielded tool is never correct  ->  False
    information_missing  None — see below
    policy_forbids       None — not modelled
    originates_from_untrusted   None — not modelled

``information_missing`` is deliberately left silent. ToolSandbox insufficiency
and tau2's ``unknown_info`` sound alike in English but are different claims:
tau2 means the user could supply the fact if asked, which is machine-resolvable
and routes to VERIFY; ToolSandbox means the fact is unobtainable with the
available tools, which routes to ABSTAIN. Setting the predicate true here would
make row 3 fire before row 4 and relabel every unanswerable task as resolvable.

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

DATASET = "toolsandbox"
_CALL_NAME = "ScenarioExtension"


def _silent(field: str) -> PredicateValue:
    return PredicateValue(value=None, source_dataset=DATASET, source_field=field)


def _str_list(node: ast.AST | None) -> tuple[str, ...]:
    """Extract a list of string literals; non-literal entries are skipped."""
    if not isinstance(node, ast.List):
        return ()
    return tuple(
        e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
    )


def _string_constants(node: ast.AST) -> list[str]:
    """Every string literal anywhere under *node*, in source order."""
    return [
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def _user_message(messages: ast.AST | None) -> str | None:
    """Return the content of the first message addressed to the agent.

    Messages are dict literals whose ``sender``/``recipient`` are ``RoleType``
    attribute accesses. The user turn is the one sent by USER.
    """
    if not isinstance(messages, ast.List):
        return None
    for element in messages.elts:
        if not isinstance(element, ast.Dict):
            continue
        entry: dict[str, ast.AST] = {
            k.value: v
            for k, v in zip(element.keys, element.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        sender = entry.get("sender")
        is_user = isinstance(sender, ast.Attribute) and sender.attr == "USER"
        content = entry.get("content")
        if is_user and isinstance(content, ast.Constant) and isinstance(content.value, str):
            return content.value
    return None


class ToolSandboxAdapter:
    """Builds routing episodes by AST-parsing ToolSandbox scenario modules."""

    def __init__(self, paths: list[Path], commit: str) -> None:
        self.paths = [Path(p) for p in paths]
        self.commit = commit

    def build_episodes(self) -> list[RoutingEpisode]:
        episodes: list[RoutingEpisode] = []
        for path in self.paths:
            episodes.extend(self._parse(path))
        return episodes

    def _parse(self, path: Path) -> list[RoutingEpisode]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out: list[RoutingEpisode] = []

        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == _CALL_NAME
            ):
                continue

            kwargs = {k.arg: k.value for k in node.keywords if k.arg}
            name_node = kwargs.get("name")
            if not (isinstance(name_node, ast.Constant) and isinstance(name_node.value, str)):
                continue
            name = name_node.value

            allow = _str_list(kwargs.get("tool_allow_list"))
            deny = _str_list(kwargs.get("tool_deny_list"))
            milestones = kwargs.get("milestones")
            minefields = kwargs.get("minefields")

            # milestones == [] is the source stating no tool call is correct.
            # A missing or non-literal milestones argument stays unknown.
            if isinstance(milestones, ast.List):
                tool_required: bool | None = bool(milestones.elts)
            else:
                tool_required = None

            mined = self._mined_tools(minefields, known=set(allow) | set(deny))
            proposed = self._proposed_call(mined, allow)

            user_task = _user_message(kwargs.get("messages")) or name
            out.append(
                self._episode(
                    scenario=name,
                    source_file=path.name,
                    user_task=user_task,
                    available=allow,
                    proposed=proposed,
                    tool_required=tool_required,
                    proposed_is_mined=proposed is not None and proposed in mined,
                )
            )

        return out

    @staticmethod
    def _mined_tools(minefields: ast.AST | None, known: set[str]) -> tuple[str, ...]:
        """Tool names named inside minefield constraints.

        The constraint bodies nest dataframes several levels deep, so rather
        than tracking that structure the adapter collects every string literal
        under the node and keeps those that name a declared tool.
        """
        if minefields is None:
            return ()
        seen: list[str] = []
        for value in _string_constants(minefields):
            if value in known and value not in seen:
                seen.append(value)
        return tuple(seen)

    @staticmethod
    def _proposed_call(mined: tuple[str, ...], allow: tuple[str, ...]) -> str | None:
        """The call a naive agent would make: a mined tool it is allowed to call."""
        for tool in mined:
            if tool in allow:
                return tool
        return allow[0] if allow else None

    def _episode(
        self,
        *,
        scenario: str,
        source_file: str,
        user_task: str,
        available: tuple[str, ...],
        proposed: str | None,
        tool_required: bool | None,
        proposed_is_mined: bool,
    ) -> RoutingEpisode:
        predicates = NativePredicates(
            tool_required=PredicateValue(
                value=tool_required,
                source_dataset=DATASET,
                source_field="ScenarioExtension.milestones",
            ),
            call_in_gold_set=PredicateValue(
                # A minefielded tool is never a correct call. Anything else is
                # unknown: milestones name the required end state, not a call.
                value=False if proposed_is_mined else None,
                source_dataset=DATASET,
                source_field="ScenarioExtension.minefields",
            ),
            originates_from_untrusted=_silent("(not modelled by ToolSandbox)"),
            information_missing=_silent(
                "(deliberately silent: ToolSandbox insufficiency is not "
                "user-resolvable; see module docstring)"
            ),
            policy_forbids=_silent("(not modelled by ToolSandbox)"),
        )
        route = assign_route(predicates)
        return RoutingEpisode(
            id=f"toolsandbox:{scenario}",
            source_dataset=DATASET,
            source_commit=self.commit,
            cluster_id=f"toolsandbox:{scenario}",
            user_task=user_task,
            available_tools=available,
            untrusted_context=None,
            proposed_tool_name=proposed,
            proposed_tool_args={},
            domain=source_file.replace("_scenarios.py", ""),
            args_statically_unavailable=True,
            predicates=predicates,
            route=route,
            route_table_version=ROUTE_TABLE_VERSION if route else "",
            matched_row=matched_row(predicates) if route else None,
            redistributable=False,
            notes=("ToolSandbox: local-only, not redistributable",),
        )
