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
from dataclasses import dataclass, field
from enum import Enum
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


class ArgumentValueStatus(str, Enum):
    """What the system of record establishes about one argument value.

    UNSUPPORTED is a claim about the world; UNKNOWN is a claim about our
    evidence. Reporting the first when only the second holds is precisely the
    §26 holdout failure.
    """

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CoverageScope:
    """What an index is entitled to make negative claims about.

    Coverage is per *argument*, not per domain. tau2's telecom state covers
    ``plan_id`` and ``device_id`` while its tasks operate on ``customer_id`` and
    ``line_id``, so a domain-level flag would call those covered and reproduce
    §26 one level up.
    """

    domain: str
    argument_names: frozenset[str]
    #: Absence may only mean UNSUPPORTED when the index is complete for this
    #: scope. Without that guarantee, absence is not evidence of absence.
    closed_world: bool = True


@dataclass(frozen=True)
class ArgumentValueEvidence:
    """The basis for a value verdict, so an envelope can show why, not just what."""

    status: ArgumentValueStatus
    domain: str
    argument_name: str
    coverage_complete: bool
    closed_world: bool
    reason: str


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
    #: The decisive value verdict and what it rested on.
    value_evidence: ArgumentValueEvidence | None = None


@dataclass(frozen=True)
class StateIndex:
    """Scalar values present in the authoritative state, for existence checks.

    Deliberately a flat value set rather than a schema-aware model: the only
    question asked is "does the system of record contain this value at all",
    which is answerable without knowing which table it belongs to and does not
    invite over-fitting to one dataset's shape.
    """

    values: frozenset[str]
    #: What this index is entitled to make negative claims about.
    scopes: tuple[CoverageScope, ...] = field(default_factory=tuple)

    def status(
        self, domain: str, argument_name: str, value: str
    ) -> ArgumentValueStatus:
        """What this index establishes about *value* for that domain/argument."""
        scope = self._scope(domain, argument_name)
        if scope is None:
            return ArgumentValueStatus.UNKNOWN
        if value in self.values:
            return ArgumentValueStatus.SUPPORTED
        if not scope.closed_world:
            return ArgumentValueStatus.UNKNOWN
        return ArgumentValueStatus.UNSUPPORTED

    def _scope(self, domain: str, argument_name: str) -> CoverageScope | None:
        for scope in self.scopes:
            if scope.domain == domain and argument_name in scope.argument_names:
                return scope
        return None

    def covers(self, domain: str, argument_name: str) -> bool:
        return self._scope(domain, argument_name) is not None

    @classmethod
    def from_values(
        cls, values: set[str], scopes: tuple[CoverageScope, ...] = ()
    ) -> StateIndex:
        return cls(frozenset(v for v in values if isinstance(v, str) and v), scopes)

    @classmethod
    def from_json_files(cls, paths: list[Path]) -> StateIndex:
        """Index scalar values, deriving coverage from the keys actually seen.

        The domain is the file stem. An argument name counts as covered when the
        document carries it as a key mapping to a scalar — the index knows what
        it covers because it saw those keys, rather than being told.
        """
        collected: set[str] = set()
        covered: dict[str, set[str]] = {}

        def walk(node: Any, domain: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(key, str):
                        collected.add(key)
                        if isinstance(value, (str, int, float)) and not isinstance(
                            value, bool
                        ):
                            covered.setdefault(domain, set()).add(key)
                    walk(value, domain)
            elif isinstance(node, list):
                for item in node:
                    walk(item, domain)
            elif isinstance(node, str):
                collected.add(node)
            elif isinstance(node, (int, float)) and not isinstance(node, bool):
                collected.add(str(node))

        for path in paths:
            walk(json.loads(Path(path).read_text(encoding="utf-8")), Path(path).stem)

        scopes = tuple(
            CoverageScope(domain=d, argument_names=frozenset(names), closed_world=True)
            for d, names in sorted(covered.items())
        )
        return cls.from_values(collected, scopes)

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
    domain: str = "",
) -> CallCompatibility:
    """Derive the establishable compatibility facts for one proposed call."""
    if not tool:
        return CallCompatibility()

    signature = registry.signatures.get(tool)
    if signature is None:
        roles_valid: bool | None = None
    else:
        roles_valid = all(param in args for param in signature.required_params)

    # One confirmed-unsupported value is decisive. Otherwise the call counts as
    # supported only if at least one value was actually judged: a call whose
    # values all fall outside coverage is UNKNOWN, never "fine".
    verdicts = [
        (name, state.status(domain, name, value))
        for name, value in args.items()
        if _is_identifier(value)
    ]
    unsupported = [p for p in verdicts if p[1] is ArgumentValueStatus.UNSUPPORTED]
    supported = [p for p in verdicts if p[1] is ArgumentValueStatus.SUPPORTED]

    if unsupported:
        name, status = unsupported[0]
        reason = f"{name!r} absent from a closed-world index covering {domain!r}"
    elif supported:
        name, status = supported[0]
        reason = f"{name!r} present in the index covering {domain!r}"
    else:
        name = verdicts[0][0] if verdicts else ""
        status = ArgumentValueStatus.UNKNOWN
        reason = (
            f"no closed-world coverage for {domain!r}"
            f"{'/' + repr(name) if name else ''}; absence is not evidence of absence"
        )

    scope_covered = bool(name) and state.covers(domain, name)

    return CallCompatibility(
        tool_matches_goal=None,
        argument_roles_valid=roles_valid,
        argument_values_supported={
            ArgumentValueStatus.SUPPORTED: True,
            ArgumentValueStatus.UNSUPPORTED: False,
            ArgumentValueStatus.UNKNOWN: None,
        }[status],
        preconditions_met=None,
        expected_effect_matches=None,
        value_evidence=ArgumentValueEvidence(
            status=status,
            domain=domain,
            argument_name=name,
            coverage_complete=scope_covered,
            closed_world=scope_covered,
            reason=reason,
        ),
    )
