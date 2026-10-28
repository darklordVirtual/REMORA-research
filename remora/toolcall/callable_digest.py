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
import sys
from pathlib import Path
from typing import Any, Callable

from remora.toolcall.toolspec import ToolSpec

__all__ = ["CLOSURE_PREFIX", "callable_digest_for", "closure_digest",
           "closure_members", "source_digest"]


def _canonical_json(value: object) -> str:
    # Identical to remora.toolcall.runtime_surface.canonical_json; the
    # closure digests already signed into bundles depend on these bytes.
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def source_digest(fn: Callable[..., Any]) -> str:
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
        members[name] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
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
