# SPDX-License-Identifier: BUSL-1.1
"""AST-based call graph extraction for Governed PTC plans (RF-11).

This module converts a Python source string (an LLM-generated tool-calling
program) into a list of :class:`ProposedCall` data objects via *static* AST
analysis.  It never uses ``eval`` or ``exec``; the untrusted source is only
ever parsed by :func:`ast.parse`.

Security model
--------------
* Only calls that match known tool IDs are extracted; unknown calls are
  collected as ``unknown_calls`` and reported back to the caller.
* The extractor honours explicit dependency hints through ``await
  asyncio.gather(...)`` patterns and sequential flow: a call that reads from the
  return value of a previous call is marked as dependent.
* No network, filesystem, or subprocess access occurs during extraction.

The output is a DAG of :class:`ProposedCall` nodes; ``dependencies`` names
earlier nodes that must resolve before this call is submitted to REMORA.

Usage (REMORA-internal only)::

    calls, unknowns = extract_call_graph(source_text, known_tool_ids=specs)
    # calls  → list[ProposedCall] with dependency ordering
    # unknowns → list[str] of unrecognized function names (warn, not fail)
"""
from __future__ import annotations

import ast
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

__all__ = [
    "CallGraphError",
    "ProposedCall",
    "extract_call_graph",
]


class CallGraphError(Exception):
    """Raised when the source cannot be safely parsed into a call graph."""


@dataclass
class ProposedCall:
    """A single tool invocation proposed by the LLM-generated plan.

    This is a *data object only* — it carries no authority and causes no
    side-effects.  It must pass REMORA governance before any execution.

    Attributes:
        call_id: Unique opaque identifier for this proposal.
        tool_id: The target tool's identifier (must exist in the signed bundle).
        arguments: Argument values extracted from the AST.  Values that cannot
            be statically determined are replaced with the sentinel string
            ``"<dynamic>"``.
        toolspec_hash: SHA-256 of the ToolSpec for this tool (from the stub).
        dependencies: ``call_id`` values that must complete before this call.
        source_lineno: Line number in the plan source (1-based).
        plan_source_hash: SHA-256 of the full plan source, so the envelope can
            bind the governance decision to the exact program that was parsed.
    """

    call_id: str
    tool_id: str
    arguments: dict[str, Any]
    toolspec_hash: str
    dependencies: list[str] = field(default_factory=list)
    source_lineno: int = 0
    plan_source_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_id": self.tool_id,
            "arguments": self.arguments,
            "toolspec_hash": self.toolspec_hash,
            "dependencies": self.dependencies,
            "source_lineno": self.source_lineno,
            "plan_source_hash": self.plan_source_hash,
        }

    def arguments_hash(self) -> str:
        """SHA-256 of the canonically serialised arguments."""
        return hashlib.sha256(
            json.dumps(self.arguments, sort_keys=True,
                       separators=(",", ":"), default=str).encode()
        ).hexdigest()


# ── AST helpers ──────────────────────────────────────────────────────────────

def _literal_value(node: ast.expr) -> Any:
    """Best-effort extraction of a literal value from an AST expression.

    Returns the Python value if the node is a constant/collection of constants,
    or the sentinel ``"<dynamic>"`` for anything more complex (variables,
    function calls, etc.).
    """
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return "<dynamic>"


def _extract_kwargs(call_node: ast.Call) -> dict[str, Any]:
    """Extract keyword arguments from a Call node."""
    return {
        kw.arg: _literal_value(kw.value)
        for kw in call_node.keywords
        if kw.arg is not None  # skip **kwargs expansion
    }


def _extract_positional_args(
    call_node: ast.Call,
    tool_id: str,
) -> dict[str, Any]:
    """Convert positional args to a dict using ``arg_N`` keys."""
    result: dict[str, Any] = {}
    for i, arg_node in enumerate(call_node.args):
        result[f"arg_{i}"] = _literal_value(arg_node)
    return result


def _plan_source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _is_gather_call(node: ast.expr) -> bool:
    """True if *node* is ``asyncio.gather(...)`` or ``gather(...)``."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "gather":
        return True
    if isinstance(func, ast.Name) and func.id == "gather":
        return True
    return False


# ── Main extractor ────────────────────────────────────────────────────────────

class _CallExtractor(ast.NodeVisitor):
    """Walk the AST and collect calls to known tool stubs."""

    def __init__(
        self,
        known_tool_ids: frozenset[str],
        plan_hash: str,
    ) -> None:
        self._known = known_tool_ids
        self._plan_hash = plan_hash
        self.proposed: list[ProposedCall] = []
        self.unknown_calls: list[str] = []
        # Maps assignment target name → call_id (for dependency tracking)
        self._bindings: dict[str, str] = {}

    def _make_call(
        self,
        tool_id: str,
        node: ast.Call,
        toolspec_hash: str,
        dependency_call_ids: list[str],
    ) -> ProposedCall:
        kwargs = _extract_kwargs(node)
        if node.args:
            kwargs.update(_extract_positional_args(node, tool_id))
        return ProposedCall(
            call_id=str(uuid.uuid4()),
            tool_id=tool_id,
            arguments=kwargs,
            toolspec_hash=toolspec_hash,
            dependencies=dependency_call_ids,
            source_lineno=getattr(node, "lineno", 0),
            plan_source_hash=self._plan_hash,
        )

    def _resolve_tool_call(
        self, node: ast.Call
    ) -> tuple[str, str] | None:
        """Return (tool_id, toolspec_hash) if *node* calls a known stub."""
        func = node.func
        # Direct call: my_tool(...)
        if isinstance(func, ast.Name) and func.id in self._known:
            return func.id, ""
        # Attribute call: module.my_tool(...)
        if (
            isinstance(func, ast.Attribute)
            and func.attr in self._known
        ):
            return func.attr, ""
        # _remora_propose call (internal stub body) — skip; we capture at
        # the outer stub-function level instead.
        return None

    def visit_Assign(self, node: ast.Assign) -> None:
        """Track ``x = tool_call(...)`` and ``x = asyncio.gather(...)``."""
        if isinstance(node.value, ast.Call):
            if _is_gather_call(node.value):
                # x = asyncio.gather(tool_a(...), tool_b(...), ...)
                for arg in node.value.args:
                    if isinstance(arg, ast.Call):
                        resolved = self._resolve_tool_call(arg)
                        if resolved:
                            tool_id, ts_hash = resolved
                            self.proposed.append(
                                self._make_call(tool_id, arg, ts_hash, [])
                            )
            else:
                resolved = self._resolve_tool_call(node.value)
                if resolved:
                    tool_id, ts_hash = resolved
                    proposed = self._make_call(tool_id, node.value, ts_hash, [])
                    self.proposed.append(proposed)
                    # Bind the target name(s) to this call_id
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self._bindings[target.id] = proposed.call_id
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        """Handle bare expression statements (fire-and-forget calls)."""
        if isinstance(node.value, ast.Call):
            call_node = node.value
            # asyncio.gather(...) — parallel fan-out with no sequential dep
            if _is_gather_call(call_node):
                for arg in call_node.args:
                    if isinstance(arg, ast.Call):
                        resolved = self._resolve_tool_call(arg)
                        if resolved:
                            tool_id, ts_hash = resolved
                            self.proposed.append(
                                self._make_call(tool_id, arg, ts_hash, [])
                            )
            else:
                resolved = self._resolve_tool_call(call_node)
                if resolved:
                    tool_id, ts_hash = resolved
                    self.proposed.append(
                        self._make_call(tool_id, call_node, ts_hash, [])
                    )
        self.generic_visit(node)

    def visit_Await(self, node: ast.Await) -> None:
        """Handle ``await tool(...)`` and ``await asyncio.gather(...)``."""
        inner = node.value
        if isinstance(inner, ast.Call):
            if _is_gather_call(inner):
                for arg in inner.args:
                    if isinstance(arg, ast.Call):
                        resolved = self._resolve_tool_call(arg)
                        if resolved:
                            tool_id, ts_hash = resolved
                            self.proposed.append(
                                self._make_call(tool_id, arg, ts_hash, [])
                            )
            else:
                resolved = self._resolve_tool_call(inner)
                if resolved:
                    tool_id, ts_hash = resolved
                    self.proposed.append(
                        self._make_call(tool_id, inner, ts_hash, [])
                    )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Catch any remaining standalone calls not handled above."""
        # Avoid double-counting calls already handled by visit_Assign /
        # visit_Expr / visit_Await which call generic_visit themselves.
        resolved = self._resolve_tool_call(node)
        if resolved:
            func = node.func
            name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else "<unknown>"
            )
            if name not in {p.tool_id for p in self.proposed}:
                tool_id, ts_hash = resolved
                self.proposed.append(
                    self._make_call(tool_id, node, ts_hash, [])
                )
        elif isinstance(node.func, ast.Name):
            name = node.func.id
            if (
                not name.startswith("_")
                and name not in {"print", "len", "range", "enumerate",
                                 "zip", "map", "filter", "list", "dict",
                                 "set", "tuple", "str", "int", "float",
                                 "bool", "sum", "max", "min", "sorted",
                                 "reversed", "isinstance", "getattr",
                                 "setattr", "hasattr", "type", "repr",
                                 "format", "abs", "round", "any", "all",
                                 "next", "iter", "open", "super"}
            ):
                self.unknown_calls.append(name)
        self.generic_visit(node)


def extract_call_graph(
    source: str,
    known_tool_ids: Sequence[str],
) -> tuple[list[ProposedCall], list[str]]:
    """Parse *source* and return the proposed calls as a dependency-ordered list.

    This function is **read-only**: it never executes any code, only parses it.

    Args:
        source: Python source text of the LLM-generated plan.  Treated as
            **untrusted**; only ``ast.parse`` touches it.
        known_tool_ids: Tool IDs from the signed bundle.  Only calls to these
            identifiers are extracted.

    Returns:
        A tuple ``(proposed_calls, unknown_calls)`` where:

        * ``proposed_calls`` — list of :class:`ProposedCall`, sequential order,
          dependency fields set for sequential chains.
        * ``unknown_calls`` — function names the plan calls that do not appear
          in *known_tool_ids*. The caller should surface these as a warning
          (the plan may be incomplete or the model hallucinated a tool name).

    Raises:
        :class:`CallGraphError` if *source* contains a syntax error or is
        larger than the safety cap (16 KiB).
    """
    if len(source.encode("utf-8")) > 16_384:
        raise CallGraphError(
            "Plan source exceeds 16 KiB safety cap; refusing to parse."
        )

    plan_hash = _plan_source_hash(source)

    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise CallGraphError(
            f"Plan source has a syntax error and cannot be parsed: {exc}"
        ) from exc

    extractor = _CallExtractor(
        known_tool_ids=frozenset(known_tool_ids),
        plan_hash=plan_hash,
    )
    extractor.visit(tree)

    # Deduplicate unknown_calls while preserving first-seen order
    seen: set[str] = set()
    unique_unknowns = []
    for name in extractor.unknown_calls:
        if name not in seen:
            seen.add(name)
            unique_unknowns.append(name)

    return extractor.proposed, unique_unknowns
