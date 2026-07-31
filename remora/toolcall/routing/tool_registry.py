# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tool registry and argument-satisfiability check.

A deployment knows which tools exist and what each requires and produces — that
is ordinary integration infrastructure, not benchmark metadata. This module
turns that knowledge into one signal the policy engine can consume: **can the
proposed call's required parameters be sourced at all?**

Why this signal and not blast radius. Enabling the low-consequence ACCEPT path
took ABSTAIN recall from 62.5% to 0% on the routing benchmark. Inspecting every
lost case showed they were not high-blast-radius calls: ``search_lat_lon`` with
no latitude obtainable, ``timestamp_diff`` with no clock available,
``unit_conversion`` with no amount to convert. ``unit_conversion`` is pure
arithmetic — about as bounded as a call gets — and still wrong. The shared
property is that the call's required arguments do not exist, so an agent making
it would have to fabricate them.

Inputs are observable: the proposed tool name, the available tool list, the task
text, and the registry. No label is read.

The check is deliberately asymmetric. ``False`` means *confirmed
unsatisfiable*; ``None`` means the registry does not cover this tool. Unknown
must never behave like a negative, or every source whose schemas have not been
extracted would be disqualified.

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

#: Verbs stripped from a function name to derive what it produces:
#: ``get_current_timestamp`` -> ``timestamp``.
_PRODUCER_PREFIXES = (
    "get_", "fetch_", "read_", "current_", "retrieve_", "load_", "lookup_",
)

#: Trailing index suffixes are normalised away so ``timestamp_0`` and
#: ``timestamp_1`` are both satisfied by a producer of ``timestamp``.
_INDEX_SUFFIX = re.compile(r"_\d+$")


def _normalise(name: str) -> str:
    return _INDEX_SUFFIX.sub("", name.strip().lower())


@dataclass(frozen=True)
class ToolSignature:
    """What a tool requires and what it yields."""

    name: str
    #: Parameters without a default. Defaulted parameters are optional and are
    #: not required for the call to be well-formed.
    required_params: tuple[str, ...] = ()
    #: Names this tool can supply to a later call, from its return annotation's
    #: ``Literal`` keys plus the noun in its own name.
    produced_names: tuple[str, ...] = ()

    def produces(self) -> set[str]:
        return {_normalise(n) for n in self.produced_names}


@dataclass
class ToolRegistry:
    """Maps tool name to signature and answers satisfiability questions."""

    signatures: dict[str, ToolSignature] = field(default_factory=dict)

    def __contains__(self, tool: str) -> bool:
        return tool in self.signatures

    def arguments_satisfiable(
        self,
        *,
        proposed: str | None,
        available: Sequence[str],
        task_text: str,
        proposed_args: dict[str, object] | None = None,
    ) -> bool | None:
        """Can every required parameter of *proposed* be sourced?

        A parameter counts as sourced when it is already present in
        ``proposed_args``, named in the task text, or produced by an available
        tool. Returns ``False`` when at least one has no possible source, and
        ``None`` when the tool is not registered.

        Arguments already in the call are sourced by definition — the agent
        obtained the value somewhere. Whether that somewhere was legitimate is
        ``argument_tainted``'s question, not this one.
        """
        if not proposed:
            return None
        signature = self.signatures.get(proposed)
        if signature is None:
            return None
        if not signature.required_params:
            return True

        supplied: set[str] = set()
        for tool in available:
            if tool == proposed:
                continue
            other = self.signatures.get(tool)
            if other is not None:
                supplied |= other.produces()
                continue
            # An unregistered tool whose name declares what it yields still
            # declares it: get_current_location, lookup_reservation_id. Without
            # this fallback, satisfiability silently depends on whether the
            # registry happens to have been populated with that tool, which
            # makes the answer a property of setup order rather than of the
            # call. Caught by the metamorphic obtainable/unobtainable invariant.
            derived = _name_derived_output(tool)
            if derived:
                supplied.add(_normalise(derived))

        given = {
            _normalise(k)
            for k, v in (proposed_args or {}).items()
            if v is not None and str(v).strip()
        }

        text = task_text.lower()
        for param in signature.required_params:
            key = _normalise(param)
            if key in given or key in supplied:
                continue
            # A task that names the parameter supplies it.
            if key in text or param.strip().lower() in text:
                continue
            return False
        return True


def _is_none_literal(node: ast.AST | None) -> bool:
    """True for a literal ``None`` default."""
    return isinstance(node, ast.Constant) and node.value is None


def _literal_keys(node: ast.AST) -> list[str]:
    """String constants inside any ``Literal[...]`` under *node*."""
    out: list[str] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Subscript):
            continue
        base = sub.value
        base_name = getattr(base, "id", None) or getattr(base, "attr", None)
        if base_name != "Literal":
            continue
        for item in ast.walk(sub.slice):
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                out.append(item.value)
    return out


def _name_derived_output(func_name: str) -> str | None:
    """The noun a producer-style function name yields, if any."""
    lowered = func_name.strip().lower()
    for prefix in _PRODUCER_PREFIXES:
        if lowered.startswith(prefix):
            remainder = lowered[len(prefix):]
            for extra in _PRODUCER_PREFIXES:
                if remainder.startswith(extra):
                    remainder = remainder[len(extra):]
            return remainder or None
    return None


def extract_from_python(paths: Iterable[Path]) -> dict[str, ToolSignature]:
    """Extract signatures from Python modules by AST, without importing them.

    Importing tool modules would require their runtime dependencies; the
    signature is fully available statically.
    """
    signatures: dict[str, ToolSignature] = {}

    for path in paths:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))

        # Module-level functions (ToolSandbox) and public methods of top-level
        # classes (tau2 exposes its tools as methods on a domain class).
        candidates: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for top in tree.body:
            if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
                candidates.append(top)
            elif isinstance(top, ast.ClassDef):
                candidates.extend(
                    m
                    for m in top.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                )

        for node in candidates:
            if node.name.startswith("_"):
                continue

            args = node.args
            positional = list(args.posonlyargs) + list(args.args)
            # Trailing defaults line up with the tail of the positional list.
            n_defaulted = len(args.defaults)
            n_plain = len(positional) - n_defaulted
            required = [a.arg for a in positional[:n_plain]]
            # A parameter defaulted to None is a sentinel for "not supplied",
            # not an optional parameter: the call still cannot do its job
            # without a value. A real default (days=0) does make it optional.
            required += [
                a.arg
                for a, default in zip(positional[n_plain:], args.defaults)
                if _is_none_literal(default)
            ]
            required += [
                a.arg
                for a, default in zip(args.kwonlyargs, args.kw_defaults)
                if default is None or _is_none_literal(default)
            ]
            required = [a for a in required if a not in {"self", "cls"}]

            produced: list[str] = []
            if node.returns is not None:
                produced.extend(_literal_keys(node.returns))
            derived = _name_derived_output(node.name)
            if derived:
                produced.append(derived)

            signatures[node.name] = ToolSignature(
                name=node.name,
                required_params=tuple(required),
                produced_names=tuple(dict.fromkeys(produced)),
            )

    return signatures
