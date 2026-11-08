# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""What a signed ToolSpec's ``callable_digest`` measures, computed from the callable.

Two kinds, as the spec attests:

- ``sha256:``: the source of the function body (the v1 contract). It does not
  measure closure state, transitive imports, credentials or host integrity;
- ``closure-sha256:`` (quality program Q3.4): the defining module file and
  every module file it transitively imports from the same top-level package,
  plus the name and installed version of each third-party distribution it
  imports. A changed dependency then fails verification at registration.

Both measure what runs (AACP-CY-11). A digest is taken from source text, and
the code that runs is a code object compiled earlier, possibly from other
bytes: a file rewritten after import, or put back after a different version
was imported, would otherwise attest the bytes on disk while the swapped code
dispatches. Before measuring, the source text that is hashed is compiled and
the result must contain the callable's own code object (and, for the closure
digest, that of every function the followed modules define in that file);
otherwise :class:`CallableSourceMismatch` is raised and registration refuses.
The digest values are unchanged, so bundles already signed still verify.

Split out of ``signed_surface_runtime`` (2026-10-13) so the CORE registration
path in ``remora.execution.authorization`` can measure a callable without
importing the EXPERIMENTAL reference runtime. Neither digest measures an
external process or binary the callable starts.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
import linecache
import sys
import types
from pathlib import Path
from typing import Any, Callable

from remora.toolcall.toolspec import ToolSpec, ToolSpecRefused

__all__ = ["CLOSURE_PREFIX", "CallableSourceMismatch", "callable_digest_for",
           "closure_digest", "closure_members", "source_digest"]


def _canonical_json(value: object) -> str:
    # Identical to remora.toolcall.runtime_surface.canonical_json; the
    # closure digests already signed into bundles depend on these bytes.
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


class CallableSourceMismatch(ToolSpecRefused):
    """The code that runs was not compiled from the source being measured."""

    def __init__(self, message: str) -> None:
        super().__init__("toolspec_callable_source_mismatch", message)


def _code_objects(code: types.CodeType):
    yield code
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from _code_objects(const)


def _function_code(obj: Any) -> types.CodeType | None:
    obj = getattr(obj, "__func__", obj)  # bound and class methods
    obj = inspect.unwrap(obj) if callable(obj) else obj
    code = getattr(obj, "__code__", None)
    return code if isinstance(code, types.CodeType) else None


def _require_compiled_from(codes: list[types.CodeType], source: str, filename: str) -> None:
    """Every code object in ``codes`` must be one ``source`` compiles to."""
    if not codes:
        return
    try:
        compiled = compile(source, filename, "exec", dont_inherit=True)
    except (SyntaxError, ValueError) as exc:
        raise CallableSourceMismatch(f"{filename} does not compile ({exc})") from exc
    # Code-object equality compares bytecode, constants (nested code
    # included), names and line tables; marshal output is not used because it
    # depends on reference counts.
    available = list(_code_objects(compiled))
    for code in codes:
        if not any(code == candidate for candidate in available):
            raise CallableSourceMismatch(
                f"{code.co_qualname} in {filename} is not the code that source "
                "compiles to; the file changed after it was loaded")


def _defined_in(module: Any, filename: str) -> list[types.CodeType]:
    """Code of the functions (and one level of methods) ``module`` defines in ``filename``."""
    codes: list[types.CodeType] = []
    for value in list(vars(module).values()):
        members = [value]
        if inspect.isclass(value) and getattr(value, "__module__", None) == module.__name__:
            members += list(vars(value).values())
        for member in members:
            code = _function_code(member)
            if code is not None and code.co_filename == filename:
                codes.append(code)
    return codes


def source_digest(fn: Callable[..., Any]) -> str:
    # inspect.getsource unwraps decorators, so the code checked is the
    # unwrapped function's, read from that function's own file.
    code = _function_code(fn)
    filename = code.co_filename if code is not None else ""
    if code is not None and filename and not filename.startswith("<"):
        # Read the file now, not a cached copy, and check that what runs is
        # what this text compiles to; the digest is then of that same text.
        linecache.checkcache(filename)
        module = sys.modules.get(getattr(inspect.unwrap(getattr(fn, "__func__", fn)), "__module__", "") or "")
        lines = linecache.getlines(filename, vars(module) if module else None)
        _require_compiled_from([code], "".join(lines), filename)
    return "sha256:" + hashlib.sha256(inspect.getsource(fn).encode("utf-8")).hexdigest()


CLOSURE_PREFIX = "closure-sha256:"


def _imported_names(path: Path, package: str | None) -> set[str]:
    """Absolute module names a file imports, relative imports resolved."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = (package or "").split(".")
                anchor = ".".join(parts[: len(parts) - node.level + 1])
                base = f"{anchor}.{base}" if base else anchor
            names.add(base)
            # ``from pkg import module`` may name a submodule, not an attribute.
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return {n for n in names if n}


def _is_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _is_source_module(name: str) -> bool:
    """Whether ``name`` resolves to Python source this process can read."""
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return False
    return bool(spec is not None and spec.origin and spec.origin.endswith(".py"))


def closure_members(fn: Callable[..., Any]) -> dict[str, str]:
    """``{module or distribution: content identity}`` for ``fn``'s import closure.

    Modules in the defining module's own top-level package are followed and
    identified by the SHA-256 of their source file, and so is any other
    top-level module or package that resolves to source but belongs to no
    installed distribution: it is part of the deployment, and only its
    content can identify it. A third-party module is not followed; it is
    identified by its distribution name and installed version, and a
    standard-library module by the interpreter version. A name that resolves
    to nothing is recorded as unresolved rather than skipped, so it still
    moves the digest if it later resolves.
    """
    from importlib import metadata

    root = inspect.getmodule(fn)
    if root is None or not getattr(root, "__file__", None):
        raise ValueError("closure_unavailable: the callable has no module file")
    top = root.__name__.split(".")[0]
    followed: set[str] = set()
    members: dict[str, str] = {}
    pending = [root.__name__]
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    distributions = metadata.packages_distributions()
    while pending:
        name = pending.pop()
        if name in members:
            continue
        head = name.split(".")[0]
        if head != top and head not in followed:
            # Not followed: one entry per top-level name, identified by what
            # is installed rather than by what the tool happened to import.
            if head in members or head == "__future__":
                continue
            if head in stdlib:
                members[head] = "stdlib:" + ".".join(map(str, sys.version_info[:2]))
                continue
            dist = (distributions.get(head) or [head])[0]
            try:
                members[head] = f"dist:{dist}=={metadata.version(dist)}"
                continue
            except metadata.PackageNotFoundError:
                pass
            if not _is_source_module(head):
                members[head] = "unresolved"
                continue
            # Part of the deployment but outside the root's package, such as
            # the local package a registry module calls to perform its
            # effect. No distribution version names it, so only its content
            # can: follow it like the root's own package.
            followed.add(head)
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            parent = name.rpartition(".")[0]
            if parent and _is_module(parent):
                continue  # ``from module import attribute``: the module is followed
            members[name] = "unresolved"
            continue
        origin = spec.origin
        if not origin or not origin.endswith(".py"):
            members[name] = "no-source"
            continue
        path = Path(origin)
        raw = path.read_bytes()
        loaded = sys.modules.get(name)
        loaded_file = getattr(loaded, "__file__", None) if loaded is not None else None
        if loaded is not None and loaded_file:
            # The bytes hashed here are the bytes the loaded functions must
            # have been compiled from (AACP-CY-11).
            codes = _defined_in(loaded, str(Path(loaded_file)))
            if name == root.__name__:
                own = _function_code(fn)
                if own is not None:
                    codes.append(own)
            _require_compiled_from(codes, importlib.util.decode_source(raw),
                                   codes[0].co_filename if codes else str(path))
        members[name] = "sha256:" + hashlib.sha256(raw).hexdigest()
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        pending.extend(_imported_names(path, package))
    return members


def closure_digest(fn: Callable[..., Any]) -> str:
    """One digest over :func:`closure_members`, for a ToolSpec to attest."""
    canonical = _canonical_json(closure_members(fn))
    return CLOSURE_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def callable_digest_for(spec: ToolSpec, fn: Callable[..., Any]) -> str:
    """The digest of the kind the signed spec attests."""
    if spec.callable_digest.startswith(CLOSURE_PREFIX):
        return closure_digest(fn)
    return source_digest(fn)
