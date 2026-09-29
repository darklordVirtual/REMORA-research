# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""An allowed tool cannot exceed its argument scope (quality program Q8.4).

A capability set says which tools a principal may use. A tool in the set can
still be used beyond its purpose: ``invoice.update`` on the amount rather
than the note, ``invoice.pay`` to another recipient or above a limit. A
:class:`ToolConstraint` narrows an allowed tool at two levels:

level 2, allowed fields
    the call may only carry the named argument keys.
level 3, semantic constraints
    each :class:`Condition` compares one value with an operator. The value is
    either an argument (``argument``) or a fact read from trusted state
    (``state``). The operand is either a literal or, with ``equals_state``,
    another fact from trusted state: ``recipient`` must equal the invoice's
    authorised recipient, and the invoice's status must be ``APPROVED``.
    ``within`` compares a resource identity with canonical resource patterns
    (``remora.capabilities.resource``); a resource outside them, or one with
    no single canonical form, refuses as ``capability_resource_not_authorized``.

Trusted state is read only through a :class:`StateReader` the deployment
supplies, keyed by the call's arguments. An agent's own assertion about state
is never an input: a condition names where its fact comes from, and the
agent chooses neither the source nor the value read from it. A condition
that needs state when no reader is bound, or whose read fails, refuses as
``capability_state_unverifiable``; an unknown fact is not a satisfied one.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from remora.capabilities.model import CapabilityRefusal

__all__ = ["Condition", "StateReader", "ToolConstraint", "evaluate_constraint"]

#: ``(source, arguments) -> value``. ``source`` names a fact such as
#: ``invoice.authorized_recipient``; ``arguments`` let the reader find the
#: record (the invoice id). Raises when the fact cannot be read.
StateReader = Callable[[str, Mapping[str, Any]], Any]

_OPERATORS = {"eq", "ne", "in", "not_in", "lt", "lte", "gt", "gte", "equals_state", "within"}
_NUMERIC = {"lt", "lte", "gt", "gte"}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass(frozen=True)
class Condition:
    """One comparison. Exactly one of ``argument`` or ``state`` names the subject."""

    operator: str
    operand: Any
    argument: str | None = None
    state: str | None = None

    def __post_init__(self) -> None:
        if (self.argument is None) == (self.state is None):
            raise ValueError("a condition names exactly one of argument or state")
        if self.operator not in _OPERATORS:
            raise ValueError(f"unknown operator {self.operator!r}")
        if self.operator in _NUMERIC and not _number(self.operand):
            raise ValueError(f"{self.operator} needs a numeric operand")
        if self.operator in {"in", "not_in"} and not isinstance(self.operand, (list, tuple)):
            raise ValueError(f"{self.operator} needs a list operand")
        if self.operator == "equals_state" and not isinstance(self.operand, str):
            raise ValueError("equals_state names a state source")
        if self.operator == "within":
            from remora.capabilities.resource import canonical_resource_pattern

            if not isinstance(self.operand, (list, tuple)) or not self.operand:
                raise ValueError("within needs a non-empty list of resource patterns")
            canonical = [canonical_resource_pattern(p) for p in self.operand]
            object.__setattr__(self, "operand", sorted(set(canonical)))

    @property
    def needs_state(self) -> bool:
        return self.state is not None or self.operator == "equals_state"

    def canonical(self) -> dict[str, Any]:
        """The policy form, ``{operator: operand, argument|state: name}``, so
        that ``from_dict(canonical())`` is the identity: a set carries its
        constraints in this form and parses them back at every check."""
        out: dict[str, Any] = {self.operator: self.operand}
        if self.argument is not None:
            out["argument"] = self.argument
        if self.state is not None:
            out["state"] = self.state
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Condition":
        ops = [k for k in data if k in _OPERATORS]
        if len(ops) != 1:
            raise ValueError(f"a condition names exactly one operator, got {sorted(ops)}")
        operand = data[ops[0]]
        return cls(operator=ops[0], operand=list(operand) if isinstance(operand, tuple) else operand,
                   argument=data.get("argument"), state=data.get("state"))


@dataclass(frozen=True)
class ToolConstraint:
    """The scope an allowed tool may be used in."""

    allowed_fields: tuple[str, ...] | None = None
    conditions: tuple[Condition, ...] = field(default_factory=tuple)

    def canonical(self) -> dict[str, Any]:
        out: dict[str, Any] = {"conditions": [c.canonical() for c in self.conditions]}
        if self.allowed_fields is not None:
            out["allowed_fields"] = sorted(self.allowed_fields)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ToolConstraint":
        fields_ = data.get("allowed_fields")
        return cls(
            allowed_fields=tuple(sorted(fields_)) if fields_ is not None else None,
            conditions=tuple(Condition.from_dict(c) for c in data.get("conditions") or ()),
        )


class _Unverifiable(Exception):
    pass


def _read(reader: StateReader | None, source: str, arguments: Mapping[str, Any]) -> Any:
    if reader is None:
        raise _Unverifiable(source)
    try:
        return reader(source, arguments)
    except Exception as exc:  # noqa: BLE001 - any failure to read is not a satisfied fact
        raise _Unverifiable(source) from exc


def _holds(condition: Condition, value: Any, reader: StateReader | None,
           arguments: Mapping[str, Any]) -> bool:
    op, operand = condition.operator, condition.operand
    if op == "equals_state":
        return bool(value == _read(reader, operand, arguments))
    if op == "within":
        from remora.capabilities.resource import resource_within

        return resource_within(value, operand)
    if op == "eq":
        return bool(value == operand)
    if op == "ne":
        return bool(value != operand)
    if op == "in":
        return value in operand
    if op == "not_in":
        return value not in operand
    if not _number(value):
        return False  # a numeric bound is never met by a non-number
    return {"lt": value < operand, "lte": value <= operand,
            "gt": value > operand, "gte": value >= operand}[op]


def evaluate_constraint(constraint: ToolConstraint | None, arguments: Any,
                        reader: StateReader | None = None) -> CapabilityRefusal | None:
    """Why ``arguments`` exceed the tool's scope, or None when they do not."""
    if constraint is None:
        return None
    if not isinstance(arguments, Mapping):
        return CapabilityRefusal.ARGUMENT_MISMATCH
    if constraint.allowed_fields is not None and set(arguments) - set(constraint.allowed_fields):
        return CapabilityRefusal.ARGUMENT_MISMATCH
    try:
        for condition in constraint.conditions:
            if condition.argument is not None:
                if condition.argument not in arguments:
                    return CapabilityRefusal.ARGUMENT_MISMATCH
                value = arguments[condition.argument]
            else:
                value = _read(reader, str(condition.state), arguments)
            if not _holds(condition, value, reader, arguments):
                if condition.operator == "within":
                    return CapabilityRefusal.RESOURCE_NOT_AUTHORIZED
                return (CapabilityRefusal.SCOPE_VIOLATION if condition.needs_state
                        else CapabilityRefusal.ARGUMENT_MISMATCH)
    except _Unverifiable:
        return CapabilityRefusal.STATE_UNVERIFIABLE
    return None


def constraints_from_policy(raw: Mapping[str, Any] | None) -> dict[str, ToolConstraint]:
    return {str(tool): ToolConstraint.from_dict(spec) for tool, spec in (raw or {}).items()}


def canonical_constraints(constraints: Mapping[str, ToolConstraint],
                          tools: Sequence[str]) -> dict[str, Any]:
    """The constraints that apply to ``tools``, in canonical form."""
    return {t: constraints[t].canonical() for t in sorted(tools) if t in constraints}
