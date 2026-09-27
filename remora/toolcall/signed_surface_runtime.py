# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Opt-in REMORA reference runtime backed by a verified signed ToolSpec bundle.

Source-span hashes follow the v1 ToolSpec contract. They do not measure closure
state, transitive imports, credentials or host integrity. Authority descriptors
must come from the deployment provider independently of the signed expectation.
"""
from __future__ import annotations

import hashlib
import inspect
from typing import Any, Callable, Mapping, Sequence

from remora.enforcement.lease import GovernedToolDispatcher
from remora.toolcall.runtime_surface import RuntimeTool, canonical_json
from remora.toolcall.surface_runtime import SurfaceRuntime
from remora.toolcall.toolspec import ToolSpec, ToolSpecBundle


def source_digest(fn: Callable[..., Any]) -> str:
    return "sha256:" + hashlib.sha256(inspect.getsource(fn).encode("utf-8")).hexdigest()


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
                 trusted_verifiers: Mapping[str, str] | None = None) -> None:
        self._bundle = ToolSpecBundle.load(bundle, key=key, trusted_identities=trusted_identities)
        expected = {raw["tool_id"]: expected_surface_tool(self._bundle.get(raw["tool_id"]))
                    for raw in bundle["tool_specs"]}
        super().__init__(dispatcher, {name: t.toolspec_hash or "" for name, t in expected.items()},
                         mode=mode, governed_authority=expected, inventory_complete=inventory_complete,
                         trusted_verifiers=trusted_verifiers)
        self._bound_versions: dict[str, int] = {}
        dispatcher.bind_toolspec_identity(self._resolve_identity)

    def _resolve_identity(self, name: str) -> tuple[str, int]:
        spec = self._bundle.get(name)
        if self.dispatcher.registration_versions().get(name) != self._bound_versions.get(name):
            raise ValueError("unverified_callable_replacement")
        return spec.toolspec_hash, spec.version

    def register(self, tool: RuntimeTool, fn: Callable[[Any], Any]) -> None:
        with self._lock, self.dispatcher.registry_guard():
            spec = self._bundle.get(tool.tool_id)
            self._bundle.verify_callable(tool.tool_id, source_digest(fn))
            if (tool.toolspec_hash != spec.toolspec_hash
                    or tool.implementation_identity != spec.implementation_identity
                    or tool.argument_schema_json != canonical_json(dict(spec.argument_schema))):
                raise ValueError("observed_toolspec_metadata_mismatch")
            if tool.credential_scope is not None:
                self._bundle.verify_credential_scope(tool.tool_id, tool.credential_scope)
            super().register(tool, fn)
            self._bound_versions[tool.tool_id] = self.dispatcher.registration_versions()[tool.tool_id]

    def assess(self, tool_name: str, arguments: Any, *, tenant: str,
               principal: str, target: str, postcondition=None):
        self._bundle.validate_arguments(tool_name, arguments)
        self._bundle.verify_target(tool_name, target)
        if postcondition is not None and postcondition.reader != self._bundle.get(tool_name).postcondition_reader:
            raise ValueError("toolspec_reader_mismatch")
        return super().assess(tool_name, arguments, tenant=tenant, principal=principal,
                              target=target, postcondition=postcondition)
