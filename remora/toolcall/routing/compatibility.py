# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Semantic call compatibility (REM-UR-011).

§21 of ``NEGATIVE_RESULTS.md`` established that the router is a near-constant
predictor: four mutation families with four different correct answers receive
the same prediction, because nothing in the observation distinguishes a correct
call from one with a corrupted argument value.

This module establishes the compatibility facts that can be derived
**deterministically from authoritative state**, with no model in the loop:

``argument_roles_valid``
    Every required parameter of the proposed tool is present in the call.

``argument_values_supported``
    Every identifier-shaped argument value exists in the system of record.

The other three fields in the contract — ``tool_matches_goal``,
``preconditions_met``, ``expected_effect_matches`` — are left ``None``. They
require task semantics that no authoritative source here provides. A guessed
field is worse than an absent one: ``None`` correctly says "nothing establishes
this", while a fabricated boolean enters the policy contract as fact.

**The trap this avoids.** The mutation generator produces ``wrong_arg_value`` by
appending a suffix to a good value. A detector that looked for that suffix would
score perfectly on the benchmark and mean nothing anywhere else. The check here
asks only whether the value exists in tau2's own database — a capability an
integrator genuinely has — and is blind to how a wrong value was produced. A
test asserts that four unrelated bogus identifiers all fail.

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from remora.toolcall.routing.tool_registry import ToolRegistry

#: A reference candidate is a compact, whitespace-free token — the sort of value
#: a system of record can confirm. Whitespace is the boundary: "Boston" can be
#: looked up, "please seat me by the window" cannot.
#:
#: The first version additionally required a digit or underscore, which excluded
#: plain single-word names. Measured on the mutation set that left 51 corrupted
#: values unjudged, every one a string the rule declined to consider. Widening
#: to any whitespace-free token is the principled boundary rather than a
#: threshold chosen to move a number; the effect on both correct and corrupted
#: calls is measured, not assumed.
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:\-]{2,64}$")


@dataclass(frozen=True)
class CallCompatibility:
    """What can be established about a proposed call's fit to the task.

    Every field is tri-state. ``None`` means no authoritative source
    establishes the fact — never "assume fine".
    """

    tool_matches_goal: bool | None = None
    argument_roles_valid: bool | None = None
    argument_values_supported: bool | None = None
    preconditions_met: bool | None = None
    expected_effect_matches: bool | None = None


@dataclass(frozen=True)
class StateIndex:
    """Scalar values present in the authoritative state, for existence checks.

    Deliberately a flat value set rather than a schema-aware model: the only
    question asked is "does the system of record contain this value at all",
    which is answerable without knowing which table it belongs to and does not
    invite over-fitting to one dataset's shape.
    """

    values: frozenset[str]

    @classmethod
    def from_values(cls, values: set[str]) -> StateIndex:
        return cls(frozenset(v for v in values if isinstance(v, str) and v))

    @classmethod
    def from_json_files(cls, paths: list[Path]) -> StateIndex:
        """Index every scalar string and dict key found in the given documents."""
        collected: set[str] = set()

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(key, str):
                        collected.add(key)
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, str):
                collected.add(node)
            elif isinstance(node, (int, float)) and not isinstance(node, bool):
                collected.add(str(node))

        for path in paths:
            walk(json.loads(Path(path).read_text(encoding="utf-8")))
        return cls.from_values(collected)

    def __len__(self) -> int:
        return len(self.values)

    def contains(self, value: str) -> bool:
        return value in self.values


def _is_identifier(value: object) -> bool:
    return isinstance(value, str) and bool(_IDENTIFIER.match(value))


def compute_compatibility(
    *,
    tool: str | None,
    args: dict[str, Any],
    registry: ToolRegistry,
    state: StateIndex,
) -> CallCompatibility:
    """Derive the establishable compatibility facts for one proposed call."""
    if not tool:
        return CallCompatibility()

    signature = registry.signatures.get(tool)
    if signature is None:
        roles_valid: bool | None = None
    else:
        roles_valid = all(param in args for param in signature.required_params)

    identifiers = [v for v in args.values() if _is_identifier(v)]
    if not state or not identifiers:
        # With no system of record, or no identifier-shaped value to check,
        # nothing can be *confirmed* unsupported.
        values_supported: bool | None = None
    else:
        values_supported = all(state.contains(v) for v in identifiers)

    return CallCompatibility(
        tool_matches_goal=None,
        argument_roles_valid=roles_valid,
        argument_values_supported=values_supported,
        preconditions_met=None,
        expected_effect_matches=None,
    )
