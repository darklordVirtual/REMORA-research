# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Opt-in REMORA reference runtime backed by a verified signed ToolSpec bundle.

Source-span hashes follow the v1 ToolSpec contract. They do not measure closure
state, transitive imports, credentials or host integrity. A spec may instead
attest a ``closure-sha256:`` digest (quality program Q3.4): the defining module
file and every module file it transitively imports from the same top-level
package, plus the name and installed version of each third-party distribution
it imports. A changed dependency then fails verification at registration.
Authority descriptors must come from the deployment provider independently of
the signed expectation.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from remora.enforcement.lease import GovernedToolDispatcher
from remora.toolcall.runtime_surface import RuntimeTool, canonical_json
from remora.toolcall.surface_runtime import SurfaceRuntime
from remora.toolcall.toolspec import ToolSpec, ToolSpecBundle


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


def closure_members(fn: Callable[..., Any]) -> dict[str, str]:
    """``{module or distribution: content identity}`` for ``fn``'s import closure.

    Modules in the defining module's own top-level package are followed and
    identified by the SHA-256 of their source file. Anything else is not
    followed: a third-party module is identified by its distribution name and
    installed version, and a standard-library module by the interpreter
    version. A name that resolves to nothing is recorded as unresolved rather
    than skipped, so it still moves the digest if it later resolves.
    """
    from importlib import metadata

    root = inspect.getmodule(fn)
    if root is None or not getattr(root, "__file__", None):
        raise ValueError("closure_unavailable: the callable has no module file")
    top = root.__name__.split(".")[0]
    members: dict[str, str] = {}
    pending = [root.__name__]
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    distributions = metadata.packages_distributions()
    while pending:
        name = pending.pop()
        if name in members:
            continue
        head = name.split(".")[0]
        if head != top:
            # Not followed: one entry per top-level name, identified by what
            # is installed rather than by what the tool happened to import.
            if head in members or head == "__future__":
                continue
            if head in stdlib:
                members[head] = "stdlib:" + ".".join(map(str, sys.version_info[:2]))
            else:
                dist = (distributions.get(head) or [head])[0]
                try:
                    members[head] = f"dist:{dist}=={metadata.version(dist)}"
                except metadata.PackageNotFoundError:
                    members[head] = "unresolved"
            continue
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
    canonical = canonical_json(closure_members(fn))
    return CLOSURE_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def callable_digest_for(spec: ToolSpec, fn: Callable[..., Any]) -> str:
    """The digest of the kind the signed spec attests."""
    if spec.callable_digest.startswith(CLOSURE_PREFIX):
        return closure_digest(fn)
    return source_digest(fn)


def expected_surface_tool(spec: ToolSpec) -> RuntimeTool:
    egress = spec.network_policy.get("egress")
    network = () if egress == "none" else tuple(egress) if isinstance(egress, list) else None
    effect = spec.semantic_contract.get("effect")
    return RuntimeTool(
        spec.tool_id, "signed-spec", True, True, spec.toolspec_hash,
        implementation_identity=spec.implementation_identity,
        argument_schema_json=canonical_json(dict(spec.argument_schema)),
        credential_scope=spec.credential_scope, allowed_targets=spec.allowed_targets,
        network_scope=network, operations=(spec.action_type,),
        effect_classes=(effect,) if isinstance(effect, str) and effect else None,
        authority_provenance=f"signed:{spec.signing_identity}")


class SignedSurfaceRuntime(SurfaceRuntime):
    """Signed spec, observed inventory and execution lease are independent checks."""

    def __init__(self, dispatcher: GovernedToolDispatcher, bundle: Mapping[str, Any], *,
                 key: str, trusted_identities: Sequence[str],
                 mode: str = "shadow", inventory_complete: bool = False,
                 trusted_verifiers: Mapping[str, str] | None = None,
                 chain: Any = None, credential_issuer: Any = None) -> None:
        """``credential_issuer`` (Q3.3) issues each registered tool a scoped
        credential; the scope checked against the signed spec is then the one
        the issuer reports, at registration and again before every dispatch,
        not the one the provider declares."""
        self._issuer = credential_issuer
        self._credentials: dict[str, Any] = {}
        self._bundle = ToolSpecBundle.load(bundle, key=key, trusted_identities=trusted_identities)
        expected = {raw["tool_id"]: expected_surface_tool(self._bundle.get(raw["tool_id"]))
                    for raw in bundle["tool_specs"]}
        super().__init__(dispatcher, {name: t.toolspec_hash or "" for name, t in expected.items()},
                         mode=mode, governed_authority=expected, inventory_complete=inventory_complete,
                         trusted_verifiers=trusted_verifiers, chain=chain)
        self._bound_versions: dict[str, int] = {}
        dispatcher.bind_toolspec_identity(self._resolve_identity)

    def _resolve_identity(self, name: str) -> tuple[str, int]:
        spec = self._bundle.get(name)
        if self.dispatcher.registration_versions().get(name) != self._bound_versions.get(name):
            raise ValueError("unverified_callable_replacement")
        return spec.toolspec_hash, spec.version

    def register(self, tool: RuntimeTool, fn: Callable[..., Any], *,
                 pass_credential: bool = False) -> None:
        """Verify and register ``fn``. With an issuer bound, the tool is given
        an issuer-scoped credential; ``pass_credential`` hands it to ``fn`` as
        a second argument."""
        with self._lock, self.dispatcher.registry_guard():
            spec = self._bundle.get(tool.tool_id)
            self._bundle.verify_callable(tool.tool_id, callable_digest_for(spec, fn))
            if self._issuer is not None:
                credential = self._issuer.issue(tool.tool_id, spec.credential_scope)
                # The issuer's answer, not the provider's claim.
                self._bundle.verify_credential_scope(
                    tool.tool_id, self._issuer.introspect(credential))
                self._credentials[tool.tool_id] = credential
                if pass_credential:
                    original = fn
                    fn = lambda args: original(args, self._credentials[tool.tool_id])  # noqa: E731
            if (tool.toolspec_hash != spec.toolspec_hash
                    or tool.implementation_identity != spec.implementation_identity
                    or tool.argument_schema_json != canonical_json(dict(spec.argument_schema))):
                raise ValueError("observed_toolspec_metadata_mismatch")
            if tool.credential_scope is not None:
                self._bundle.verify_credential_scope(tool.tool_id, tool.credential_scope)
            super().register(tool, fn)
            self._bound_versions[tool.tool_id] = self.dispatcher.registration_versions()[tool.tool_id]

    def dispatch(self, assessment_id: str, lease: Any, tool_name: str, arguments: Any, *,
                 tenant: str, principal: str, target: str) -> Any:
        if self._issuer is not None and tool_name in self._credentials:
            # Asked again immediately before the effect: a grant widened
            # after registration, or a credential the issuer no longer
            # vouches for, refuses here.
            self._bundle.verify_credential_scope(
                tool_name, self._issuer.introspect(self._credentials[tool_name]))
        return super().dispatch(assessment_id, lease, tool_name, arguments,
                                tenant=tenant, principal=principal, target=target)

    def assess(self, tool_name: str, arguments: Any, *, tenant: str,
               principal: str, target: str, postcondition=None):
        self._bundle.validate_arguments(tool_name, arguments)
        self._bundle.verify_target(tool_name, target)
        if postcondition is not None and postcondition.reader != self._bundle.get(tool_name).postcondition_reader:
            raise ValueError("toolspec_reader_mismatch")
        return super().assess(tool_name, arguments, tenant=tenant, principal=principal,
                              target=target, postcondition=postcondition)
