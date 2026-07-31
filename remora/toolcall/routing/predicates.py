# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Native predicates extracted from upstream tool-call datasets.

A predicate is admitted only when a field authored independently of REMORA
determines it. Adapters populate these and never emit a route; the route comes
from the frozen table in ``route_table.py``.

``value=None`` means the source is *silent*, not that the predicate is false.
That separation is load-bearing throughout REMORA: a confirmed negative fact
and an unknown fact must never collapse into one another (see
``tests/test_escalate_semantics_guard.py`` for the engine-side equivalent).

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# The predicate names the route table is allowed to read. Kept here rather than
# in route_table so the leakage gate can import it without importing the table.
PREDICATE_FIELDS: tuple[str, ...] = (
    "tool_required",
    "call_in_gold_set",
    "originates_from_untrusted",
    "information_missing",
    "policy_forbids",
)


@dataclass(frozen=True)
class PredicateValue:
    """One predicate, with the provenance that justifies it.

    ``source_field`` is the exact upstream path (e.g.
    ``evaluation_criteria.actions``) so any label can be traced back to the
    annotation that produced it without re-reading the adapter.
    """

    value: bool | None
    source_dataset: str
    source_field: str
    #: Verbatim upstream text, when the predicate was derived from free text.
    #: Only ``policy_forbids`` uses this; it makes every firing auditable.
    matched_text: str | None = None

    def __post_init__(self) -> None:
        if not self.source_dataset:
            raise ValueError("source_dataset must not be empty")
        if not self.source_field:
            raise ValueError("source_field must not be empty")

    def to_json_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "value": self.value,
            "source_dataset": self.source_dataset,
            "source_field": self.source_field,
        }
        if self.matched_text is not None:
            d["matched_text"] = self.matched_text
        return d


@dataclass(frozen=True)
class NativePredicates:
    """The five predicates the route table reads."""

    tool_required: PredicateValue
    call_in_gold_set: PredicateValue
    originates_from_untrusted: PredicateValue
    information_missing: PredicateValue
    policy_forbids: PredicateValue

    def values(self) -> dict[str, bool | None]:
        """Raw tri-state values keyed by predicate name."""
        return {name: getattr(self, name).value for name in PREDICATE_FIELDS}

    def to_json_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name).to_json_dict() for name in PREDICATE_FIELDS}

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> NativePredicates:
        return cls(
            **{
                name: PredicateValue(
                    value=d[name]["value"],
                    source_dataset=d[name]["source_dataset"],
                    source_field=d[name]["source_field"],
                    matched_text=d[name].get("matched_text"),
                )
                for name in PREDICATE_FIELDS
            }
        )
