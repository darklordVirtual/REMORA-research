# SPDX-License-Identifier: BUSL-1.1
"""Generate typed Python stubs from signed ToolSpec objects (RF-11 / GPTC).

Each generated stub looks like:

    def set_valve(valve: str, position: int) -> ProposedCall:
        \"\"\"Set the target valve to the specified position. [risk: HIGH]\"\"\"
        return remora.propose(
            tool_id="set_valve",
            arguments={"valve": valve, "position": position},
            toolspec_hash="<hex>",
        )

The stubs have zero direct authority. They return :class:`ProposedCall` data
objects; the caller must pass those through REMORA governance before any
execution takes place. The generated module never contains ``import requests``,
``import subprocess``, or similar network/process primitives — that is enforced
by :func:`_assert_no_dangerous_imports` at render time.

The implementation deliberately does not use ``exec`` or ``eval`` to construct
stubs: the output is a plain Python source string that a human or the CI system
can read and review before loading.
"""
from __future__ import annotations

import ast
import keyword
import re
import textwrap
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

__all__ = [
    "PythonStub",
    "StubGenerationError",
    "generate_stubs",
    "render_stub_module",
]

# Imports that must never appear in a generated stub module — the list is
# conservative: if the stub generator somehow produces them it is a bug, not a
# feature.  Checked at render time before the string is returned.
_FORBIDDEN_IMPORT_NAMES = frozenset({
    "requests", "urllib", "urllib2", "urllib3", "httpx", "aiohttp",
    "subprocess", "os.system", "socket", "ftplib", "smtplib",
    "paramiko", "boto3", "azure", "google.cloud",
})

# JSON-Schema type → Python annotation mapping (best-effort; unknown types fall
# back to ``Any``).
_JSON_TYPE_MAP: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
    "null": "None",
}

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class StubGenerationError(Exception):
    """Raised when a ToolSpec cannot be converted to a safe Python stub."""


@dataclass(frozen=True)
class PythonStub:
    """The generated stub for a single tool."""

    tool_id: str
    toolspec_hash: str
    risk_tier: str
    action_type: str
    source: str  # the Python function source text


def _safe_identifier(name: str, context: str) -> str:
    """Validate that *name* is a safe Python identifier."""
    if keyword.iskeyword(name) or not _IDENTIFIER_RE.match(name):
        raise StubGenerationError(
            f"Unsafe identifier {name!r} in {context}: "
            "tool_id and argument names must be valid Python identifiers."
        )
    return name


def _python_type(schema_property: Mapping[str, Any]) -> str:
    """Return the Python type annotation for a JSON-Schema property."""
    t = schema_property.get("type", "")
    if isinstance(t, list):
        types = [_JSON_TYPE_MAP.get(x, "Any") for x in t if x != "null"]
        nullable = "null" in t
        base = " | ".join(types) if types else "Any"
        return f"{base} | None" if nullable else base
    return _JSON_TYPE_MAP.get(str(t), "Any")


def _build_signature(
    tool_id: str, argument_schema: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    """Return (parameter list, argument-dict entries) for the stub body."""
    properties: dict[str, Any] = argument_schema.get("properties", {})
    required: set[str] = set(argument_schema.get("required", []))

    params: list[str] = []
    arg_entries: list[str] = []
    for prop_name, prop_schema in properties.items():
        safe_name = _safe_identifier(prop_name, f"argument of {tool_id!r}")
        py_type = _python_type(prop_schema)
        if prop_name in required:
            params.append(f"{safe_name}: {py_type}")
        else:
            # Optional parameter with None default; type is already nullable
            if "None" not in py_type:
                py_type = f"{py_type} | None"
            params.append(f"{safe_name}: {py_type} = None")
        arg_entries.append(f'"{prop_name}": {safe_name}')

    return params, arg_entries


def _render_stub_function(spec_raw: Mapping[str, Any]) -> PythonStub:
    """Render one ToolSpec → one PythonStub."""
    tool_id = _safe_identifier(str(spec_raw["tool_id"]), "tool_id")
    toolspec_hash = str(spec_raw.get("toolspec_hash", ""))
    risk_tier = str(spec_raw.get("risk_tier", "UNKNOWN"))
    action_type = str(spec_raw.get("action_type", "UNKNOWN"))
    description = str(spec_raw.get("description", ""))
    argument_schema: Mapping[str, Any] = spec_raw.get("argument_schema", {})

    params, arg_entries = _build_signature(tool_id, argument_schema)
    param_str = ", ".join(params)
    args_body = (
        "        {" + ", ".join(arg_entries) + "}"
        if arg_entries
        else "        {}"
    )

    # One-line description in the docstring; cap length to avoid unwieldy output.
    safe_desc = description.replace('"""', "'''")[:200]

    source = textwrap.dedent(f'''\
        def {tool_id}({param_str}) -> "ProposedCall":
            """[{risk_tier}/{action_type}] {safe_desc}"""
            return _remora_propose(
                tool_id="{tool_id}",
                arguments={args_body},
                toolspec_hash="{toolspec_hash}",
            )
    ''')
    return PythonStub(
        tool_id=tool_id,
        toolspec_hash=toolspec_hash,
        risk_tier=risk_tier,
        action_type=action_type,
        source=source,
    )


def generate_stubs(tool_specs: Sequence[Mapping[str, Any]]) -> list[PythonStub]:
    """Convert a sequence of raw ToolSpec dicts to :class:`PythonStub` objects.

    Args:
        tool_specs: Raw ToolSpec mappings (as loaded from a signed bundle).

    Returns:
        One :class:`PythonStub` per spec.

    Raises:
        :class:`StubGenerationError` if any spec is unsafe or malformed.
    """
    stubs = []
    seen: set[str] = set()
    for raw in tool_specs:
        stub = _render_stub_function(raw)
        if stub.tool_id in seen:
            raise StubGenerationError(
                f"Duplicate tool_id {stub.tool_id!r} in bundle."
            )
        seen.add(stub.tool_id)
        stubs.append(stub)
    return stubs


def render_stub_module(stubs: Sequence[PythonStub], module_name: str = "remora_tools") -> str:
    """Render a complete Python module source from a list of stubs.

    The module is importable as a read-only planning surface: calling any
    function returns a :class:`~remora.toolcall.ptc.call_graph.ProposedCall`
    data object.  No network, credentials, or side-effects are ever triggered
    by importing or calling the stubs.

    Args:
        stubs: Output of :func:`generate_stubs`.
        module_name: Used only in the module docstring.

    Returns:
        A Python source string.  Safe to write to disk or pass to
        :func:`ast.parse` for static analysis.

    Raises:
        :class:`StubGenerationError` if the rendered source contains any
        forbidden import.
    """
    header = textwrap.dedent(f'''\
        # AUTO-GENERATED by remora.toolcall.ptc.stub_generator — DO NOT EDIT.
        # This module is a planning surface only. Every function returns a
        # ProposedCall data object; no function executes real API operations.
        #
        # Generated tool stubs for: {module_name}
        # Stubs: {len(stubs)}
        """Auto-generated REMORA planning API — stubs only, no real authority."""
        from __future__ import annotations
        from remora.toolcall.ptc.call_graph import ProposedCall as _ProposedCall
        from remora.toolcall.ptc._broker import remora_propose as _remora_propose

        # Re-export so callers can type-hint return values without a separate import.
        ProposedCall = _ProposedCall

    ''')

    body = "\n\n".join(stub.source for stub in stubs)
    source = header + body + "\n"

    _assert_no_dangerous_imports(source)
    return source


def _assert_no_dangerous_imports(source: str) -> None:
    """Parse *source* and refuse if any forbidden module is imported."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise StubGenerationError(f"Generated stub has syntax error: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = (
                node.module if isinstance(node, ast.ImportFrom) else None
            )
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([module] if module else [])
            )
            for name in names:
                if name and any(
                    name == f or name.startswith(f + ".")
                    for f in _FORBIDDEN_IMPORT_NAMES
                ):
                    raise StubGenerationError(
                        f"Generated stub imports forbidden module {name!r}. "
                        "Stubs must never have direct network or process access."
                    )
