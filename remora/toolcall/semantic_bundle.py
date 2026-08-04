# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The semantic bundle — deployment-declared task-tool semantics, hashed (SHELF-020).

``build_full_observation`` needs four declaration sets: tool signatures, tool
contracts, validator bindings and a state index. In the benchmark path they are
assembled by the harness; in the execution path they must come from deployment
configuration, exactly like ``REMORA_TOOL_REGISTRY_MODULE`` supplies tool
callables. This module is that contract: the module named by
``REMORA_SEMANTIC_BUNDLE_MODULE`` exposes

    def build_semantic_bundle() -> SemanticBundle: ...

and optionally

    def resolve_intent(intent_ref: str) -> ResolvedIntent | None: ...

The bundle's hashes are ALWAYS computed here from the declarations themselves.
A deployment module cannot assert a hash: a declared hash could be stale or
forged, and everything downstream — the audit record at assess time, the
``tool_contract_bundle_hash`` binding in the ExecutionLease — would then attest
to a contract set that was not the one consulted.

Two hashes, deliberately separate:

``bundle_hash``
    Identity of the *declarations* (signatures + contracts + validators).
    Stable across state changes, so a lease binds to what was declared.
``state_hash``
    Snapshot of the state index consulted for this decision. Recorded in the
    audit chain; changes whenever the system of record does.

Intent provenance follows ``docs/research/task_intent_authority_v1.md``: an
intent can never ride inside a tool-call request. The request carries only an
opaque ``intent_ref``; the deployment module resolves it against a source it
controls (signed work order, approved workflow template, ...) and answers with
a :class:`ResolvedIntent` that names its authority.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from dataclasses import dataclass, fields as _dc_fields
from typing import Any, Callable, Protocol

from remora.toolcall.routing.compatibility import StateIndex
from remora.toolcall.routing.goal_match import TaskIntent
from remora.toolcall.routing.tool_contract import ToolContractRegistry
from remora.toolcall.routing.tool_registry import ToolRegistry
from remora.toolcall.routing.validators import ValidatorRegistry

ENV_BUNDLE_MODULE = "REMORA_SEMANTIC_BUNDLE_MODULE"


def _canonical(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )


def _sha256(data: Any) -> str:
    return hashlib.sha256(_canonical(data)).hexdigest()


def compute_bundle_hash(
    registry: ToolRegistry,
    contracts: ToolContractRegistry,
    validators: ValidatorRegistry | None,
) -> str:
    """Canonical identity of the declaration set. Any change to a signature,
    a contract field (including canonicalisations) or a validator binding
    moves this hash — silent weakening through omission is not silent."""
    return _sha256({
        "signatures": registry.to_json_dict(),
        "contracts": contracts.to_json_dict(),
        "validators": validators.to_json_dict() if validators is not None else None,
    })


def compute_state_hash(state: StateIndex) -> str:
    """Snapshot identity of the state index consulted for one decision."""
    return _sha256({
        "values": sorted(state.values),
        "scopes": [
            {
                "domain": scope.domain,
                "argument_names": sorted(scope.argument_names),
                "closed_world": scope.closed_world,
            }
            for scope in state.scopes
        ],
    })


@dataclass(frozen=True)
class SemanticBundle:
    """One frozen declaration set for the authoritative execution path."""

    registry: ToolRegistry
    contracts: ToolContractRegistry
    validators: ValidatorRegistry | None
    state: StateIndex
    bundle_hash: str
    state_hash: str

    def __post_init__(self) -> None:
        expected_bundle = compute_bundle_hash(
            self.registry, self.contracts, self.validators
        )
        expected_state = compute_state_hash(self.state)
        if self.bundle_hash != expected_bundle or self.state_hash != expected_state:
            raise ValueError(
                "semantic bundle hash mismatch: hashes are computed from the "
                "declarations, never declared — use SemanticBundle.build()"
            )

    @classmethod
    def build(
        cls,
        *,
        registry: ToolRegistry,
        contracts: ToolContractRegistry,
        validators: ValidatorRegistry | None = None,
        state: StateIndex | None = None,
    ) -> "SemanticBundle":
        resolved_state = state if state is not None else StateIndex(frozenset())
        return cls(
            registry=registry,
            contracts=contracts,
            validators=validators,
            state=resolved_state,
            bundle_hash=compute_bundle_hash(registry, contracts, validators),
            state_hash=compute_state_hash(resolved_state),
        )


@dataclass(frozen=True)
class ResolvedIntent:
    """A TaskIntent plus the provenance that makes it usable at runtime.

    ``authority`` names the source per the authority document — e.g.
    ``signed_work_order:<doc_hash>`` or ``workflow_template:<file_hash>``.
    An empty authority is the provenance gap itself and is unrepresentable.
    """

    intent: TaskIntent
    task_text: str
    authority: str

    def __post_init__(self) -> None:
        if not self.authority.strip():
            raise ValueError(
                "a resolved intent must name its authority; an intent with no "
                "provenance cannot be admitted to the execution path"
            )


def compute_intent_authority_hash(resolved: ResolvedIntent) -> str:
    """Identity of the frozen intent + its source, bound into lease and audit."""
    intent_dict = {
        f.name: getattr(resolved.intent, f.name) for f in _dc_fields(resolved.intent)
    }
    return _sha256({
        "intent": intent_dict,
        "task_text": resolved.task_text,
        "authority": resolved.authority,
    })


class IntentResolver(Protocol):
    def __call__(self, intent_ref: str) -> ResolvedIntent | None: ...


def _bundle_module():
    spec = os.environ.get(ENV_BUNDLE_MODULE, "").strip()
    if not spec:
        return None
    return importlib.import_module(spec)


def load_semantic_bundle() -> SemanticBundle | None:
    """Build the bundle from the deployment module; ``None`` when unconfigured.

    Import and shape errors raise: a deployment that names a bundle module is
    asserting the semantic path, and a half-loaded bundle silently falling
    back to the registry-only path would un-assert it without anyone noticing.
    """
    module = _bundle_module()
    if module is None:
        return None
    builder: Callable[[], SemanticBundle] | None = getattr(
        module, "build_semantic_bundle", None
    )
    if builder is None:
        raise RuntimeError(
            f"{module.__name__} does not expose build_semantic_bundle(); "
            f"see remora/toolcall/semantic_bundle.py for the module contract"
        )
    bundle = builder()
    if not isinstance(bundle, SemanticBundle):
        raise RuntimeError(
            f"{module.__name__}.build_semantic_bundle() must return a "
            f"SemanticBundle, got {type(bundle).__name__}"
        )
    return bundle


def load_intent_resolver() -> IntentResolver | None:
    """The deployment's intent resolver, when it declares one."""
    module = _bundle_module()
    if module is None:
        return None
    resolver = getattr(module, "resolve_intent", None)
    if resolver is not None and not callable(resolver):
        raise RuntimeError(f"{module.__name__}.resolve_intent is not callable")
    return resolver
