# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Episode schema for the routing benchmark.

Follows the observable / sealed-ground-truth split established by
``ToolCallTaskV3``: the gate under evaluation may read only the observable
surface. The leakage gate in ``leakage.py`` enforces that mechanically.

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from remora.toolcall.routing.predicates import NativePredicates


class Route(str, Enum):
    """The four REMORA control decisions this benchmark labels."""

    ACCEPT = "accept"
    VERIFY = "verify"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"


#: Fields the gate under evaluation is allowed to read. Anything outside this
#: set is sealed ground truth. ``leakage.py`` asserts the two are disjoint.
OBSERVABLE_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "source_dataset",
        "domain",
        "user_task",
        "available_tools",
        "untrusted_context",
        "proposed_tool_name",
        "proposed_tool_args",
        "args_statically_unavailable",
    }
)


@dataclass(frozen=True)
class RoutingEpisode:
    """One (task, proposed_call) decision point with a native-derived label."""

    # Identity and provenance
    id: str
    source_dataset: str
    source_commit: str
    #: Upstream task id. Episodes derived from one task share it, so confidence
    #: intervals can use cluster counts rather than treating them as
    #: independent draws (NEGATIVE_RESULTS.md §17).
    cluster_id: str

    # Observable surface
    user_task: str
    available_tools: tuple[str, ...]
    untrusted_context: str | None
    proposed_tool_name: str | None
    proposed_tool_args: dict[str, Any]
    domain: str
    #: True when the adapter could not statically recover argument values
    #: (AgentDojo computes them at runtime). Observable so the limitation is
    #: visible in the data, not only in the design document.
    args_statically_unavailable: bool = False

    # Sealed ground truth
    predicates: NativePredicates | None = None
    route: Route | None = None
    route_table_version: str = ""
    matched_row: int | None = None
    #: False for sources whose license forbids redistributing derived episodes
    #: (e.g. ToolSandbox). Those are built locally and never committed.
    redistributable: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if not self.id:
            raise ValueError("id must not be empty")
        if not self.source_dataset:
            raise ValueError("source_dataset must not be empty")
        if not self.cluster_id:
            raise ValueError("cluster_id must not be empty")
        if not self.user_task:
            raise ValueError("user_task must not be empty")
        if self.route is not None and not self.route_table_version:
            raise ValueError("a labelled episode must record route_table_version")
        if self.route is None and self.matched_row is not None:
            raise ValueError("matched_row must be None when route is None")

    def observable(self) -> dict[str, Any]:
        """The subset the gate under evaluation may read."""
        return {
            "id": self.id,
            "source_dataset": self.source_dataset,
            "domain": self.domain,
            "user_task": self.user_task,
            "available_tools": list(self.available_tools),
            "untrusted_context": self.untrusted_context,
            "proposed_tool_name": self.proposed_tool_name,
            "proposed_tool_args": dict(self.proposed_tool_args),
            "args_statically_unavailable": self.args_statically_unavailable,
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_dataset": self.source_dataset,
            "source_commit": self.source_commit,
            "cluster_id": self.cluster_id,
            "user_task": self.user_task,
            "available_tools": list(self.available_tools),
            "untrusted_context": self.untrusted_context,
            "proposed_tool_name": self.proposed_tool_name,
            "proposed_tool_args": dict(self.proposed_tool_args),
            "domain": self.domain,
            "args_statically_unavailable": self.args_statically_unavailable,
            "predicates": self.predicates.to_json_dict() if self.predicates else None,
            "route": self.route.value if self.route else None,
            "route_table_version": self.route_table_version,
            "matched_row": self.matched_row,
            "redistributable": self.redistributable,
            "notes": list(self.notes),
        }

    def to_jsonl(self) -> str:
        """Deterministic single-line JSON: sorted keys, no trailing whitespace."""
        return json.dumps(self.to_json_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> RoutingEpisode:
        return cls(
            id=d["id"],
            source_dataset=d["source_dataset"],
            source_commit=d["source_commit"],
            cluster_id=d["cluster_id"],
            user_task=d["user_task"],
            available_tools=tuple(d["available_tools"]),
            untrusted_context=d["untrusted_context"],
            proposed_tool_name=d["proposed_tool_name"],
            proposed_tool_args=dict(d["proposed_tool_args"]),
            domain=d["domain"],
            args_statically_unavailable=d.get("args_statically_unavailable", False),
            predicates=(
                NativePredicates.from_json_dict(d["predicates"])
                if d.get("predicates")
                else None
            ),
            route=Route(d["route"]) if d.get("route") else None,
            route_table_version=d.get("route_table_version", ""),
            matched_row=d.get("matched_row"),
            redistributable=d.get("redistributable", True),
            notes=tuple(d.get("notes", ())),
        )
