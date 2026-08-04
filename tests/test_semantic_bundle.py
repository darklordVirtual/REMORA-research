# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""SHELF-020: the semantic bundle — one hashed declaration set for the
authoritative execution path.

The bundle carries the deployment-declared task-tool semantics (tool
signatures, contracts, validator bindings, state index) plus canonical hashes
computed from the declarations themselves. The hashes are never declared by
the deployment module: a declared hash could be stale or forged, and the lease
binding built on it would then attest to the wrong contract set.
"""
from __future__ import annotations

import pytest

from remora.toolcall.routing.compatibility import CoverageScope, StateIndex
from remora.toolcall.routing.goal_match import TaskIntent
from remora.toolcall.routing.tool_contract import ToolContract, ToolContractRegistry
from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature
from remora.toolcall.routing.validators import ArgumentValidator, ValidatorRegistry
from remora.toolcall.semantic_bundle import (
    ResolvedIntent,
    SemanticBundle,
    compute_intent_authority_hash,
    load_intent_resolver,
    load_semantic_bundle,
)


def _registry() -> ToolRegistry:
    return ToolRegistry(signatures={
        "get_booking": ToolSignature(
            name="get_booking", effect="read", required_params=("booking_id",)
        ),
        "cancel_booking": ToolSignature(
            name="cancel_booking", effect="write", required_params=("booking_id",)
        ),
    })


def _contracts(effect: str = "read") -> ToolContractRegistry:
    return ToolContractRegistry([
        ToolContract(
            tool="get_booking",
            capability="booking_management",
            effect=effect,
            resource_type="booking",
            mutation=effect not in ("read", "get", "retrieve"),
            argument_roles={"booking_id": "target_resource"},
        ),
    ])


def _validators() -> ValidatorRegistry:
    return ValidatorRegistry((
        ArgumentValidator(
            argument_role="booking_id",
            tool="get_booking",
            input_argument="booking_id",
            tenant="acme",
        ),
    ))


def _state(values: set[str] | None = None) -> StateIndex:
    return StateIndex.from_values(
        values if values is not None else {"B-104"},
        (CoverageScope("booking_management", frozenset({"booking_id"})),),
    )


def _bundle(**overrides) -> SemanticBundle:
    kwargs = dict(
        registry=_registry(),
        contracts=_contracts(),
        validators=_validators(),
        state=_state(),
    )
    kwargs.update(overrides)
    return SemanticBundle.build(**kwargs)


# ---------------------------------------------------------------------------
# Bundle hash: computed, deterministic, sensitive to every declaration class
# ---------------------------------------------------------------------------

def test_bundle_hash_is_computed_and_deterministic() -> None:
    a, b = _bundle(), _bundle()
    assert a.bundle_hash == b.bundle_hash
    assert len(a.bundle_hash) == 64
    int(a.bundle_hash, 16)  # hex digest, not a label


def test_bundle_hash_changes_when_a_contract_changes() -> None:
    assert _bundle().bundle_hash != _bundle(contracts=_contracts(effect="cancel")).bundle_hash


def test_bundle_hash_changes_when_a_signature_changes() -> None:
    changed = ToolRegistry(signatures={
        "get_booking": ToolSignature(
            name="get_booking", effect="read", required_params=()
        ),
        "cancel_booking": ToolSignature(
            name="cancel_booking", effect="write", required_params=("booking_id",)
        ),
    })
    assert _bundle().bundle_hash != _bundle(registry=changed).bundle_hash


def test_bundle_hash_changes_when_validators_change() -> None:
    assert _bundle().bundle_hash != _bundle(validators=ValidatorRegistry(())).bundle_hash


def test_state_changes_move_state_hash_but_not_bundle_hash() -> None:
    """The bundle hash is the identity of the *declarations*; live state is
    data. Folding state into the bundle hash would make the lease binding
    churn on every record insert and mean nothing as a contract identity."""
    base, moved = _bundle(), _bundle(state=_state({"B-104", "B-999"}))
    assert base.bundle_hash == moved.bundle_hash
    assert base.state_hash != moved.state_hash
    assert len(base.state_hash) == 64


def test_declared_bundle_hash_is_refused() -> None:
    """A deployment module must not be able to assert a hash; only the
    computed value exists. Direct construction with a forged hash refuses."""
    good = _bundle()
    with pytest.raises(ValueError, match="hash"):
        SemanticBundle(
            registry=good.registry,
            contracts=good.contracts,
            validators=good.validators,
            state=good.state,
            bundle_hash="f" * 64,
            state_hash=good.state_hash,
        )


# ---------------------------------------------------------------------------
# Intent authority hash
# ---------------------------------------------------------------------------

def _intent() -> TaskIntent:
    return TaskIntent(
        operation="retrieve",
        resource_type="booking",
        requested_effect="read",
        target_entities=("target_resource",),
        source_spans=("booking B-104",),
        action_spans=("show me booking B-104",),
        proposed_by="workflow_template:abc123",
    )


def test_intent_authority_hash_is_deterministic_and_component_sensitive() -> None:
    resolved = ResolvedIntent(
        intent=_intent(),
        task_text="Show me booking B-104.",
        authority="workflow_template:abc123",
    )
    same = ResolvedIntent(
        intent=_intent(),
        task_text="Show me booking B-104.",
        authority="workflow_template:abc123",
    )
    other_task = ResolvedIntent(
        intent=_intent(),
        task_text="Cancel booking B-104.",
        authority="workflow_template:abc123",
    )
    other_authority = ResolvedIntent(
        intent=_intent(),
        task_text="Show me booking B-104.",
        authority="workflow_template:fff999",
    )
    h = compute_intent_authority_hash(resolved)
    assert h == compute_intent_authority_hash(same)
    assert len(h) == 64
    assert h != compute_intent_authority_hash(other_task)
    assert h != compute_intent_authority_hash(other_authority)


def test_resolved_intent_requires_an_authority() -> None:
    """An intent with no named authority is exactly the provenance gap the
    authority document closes; it must be unrepresentable here."""
    with pytest.raises(ValueError, match="authority"):
        ResolvedIntent(intent=_intent(), task_text="Show me booking B-104.", authority="")


# ---------------------------------------------------------------------------
# Deployment-module loader (REMORA_SEMANTIC_BUNDLE_MODULE)
# ---------------------------------------------------------------------------

def test_loader_returns_none_when_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    assert load_semantic_bundle() is None
    assert load_intent_resolver() is None


def test_loader_builds_bundle_from_research_template(monkeypatch) -> None:
    monkeypatch.setenv(
        "REMORA_SEMANTIC_BUNDLE_MODULE", "servers.semantic_bundle_research"
    )
    bundle = load_semantic_bundle()
    assert isinstance(bundle, SemanticBundle)
    # The research profile declares contracts for the tools it registers.
    assert bundle.contracts.get("store_artifact") is not None
    assert bundle.contracts.get("read_telemetry") is not None
    assert bundle.contracts.get("read_telemetry").is_read


def test_loader_refuses_module_without_builder(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_SEMANTIC_BUNDLE_MODULE", "json")
    with pytest.raises(RuntimeError, match="build_semantic_bundle"):
        load_semantic_bundle()
