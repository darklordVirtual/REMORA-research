# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The gateway's semantic bundle: what every governed tool *is*.

``REMORA_SEMANTIC_BUNDLE_MODULE`` points here. It declares effect, capability
and resource type per tool so risk is derived server-side, and it resolves an
``intent_ref`` into the authority a call claims to act under.

Authority is a GitHub issue for every set, not only the GitHub tools. That is
deliberate: when a developer drives Claude Code, the thing that says what
should happen is a ticket, whether the resulting call touches a repository or
a knowledge graph. Asserting a fact into the graph "because the agent thought
it followed" is exactly the case that needs a human-written reason behind it.
"""
from __future__ import annotations

from remora.toolcall.routing.compatibility import CoverageScope, StateIndex
from remora.toolcall.routing.tool_contract import ToolContract, ToolContractRegistry
from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature
from remora.toolcall.semantic_bundle import SemanticBundle

from deploy.gateway import gh_bundle
from deploy.gateway.registry import enabled_sets

# Re-exported so the deployment has one intent resolver regardless of which
# sets are live. See the module docstring for why it is the GitHub issue.
resolve_intent = gh_bundle.resolve_intent

_GRAPH_SIGNATURES = {
    "kg_list_graphs": ToolSignature(
        name="kg_list_graphs", effect="read", required_params=()),
    "kg_query_facts": ToolSignature(
        name="kg_query_facts", effect="read",
        required_params=("graph", "subject")),
    "kg_find_subjects": ToolSignature(
        name="kg_find_subjects", effect="read",
        required_params=("graph", "predicate")),
    "kg_assert_fact": ToolSignature(
        name="kg_assert_fact", effect="write",
        required_params=("graph", "subject", "predicate", "source")),
    "kg_retract_fact": ToolSignature(
        name="kg_retract_fact", effect="write", required_params=("id",)),
}

_GRAPH_CONTRACTS = [
    ToolContract(tool="kg_list_graphs", capability="graph_read",
                 effect="read", resource_type="graph", mutation=False,
                 argument_roles={}),
    ToolContract(tool="kg_query_facts", capability="graph_read",
                 effect="read", resource_type="fact", mutation=False,
                 argument_roles={"graph": "target_resource",
                                 "subject": "target_resource"}),
    ToolContract(tool="kg_find_subjects", capability="graph_read",
                 effect="read", resource_type="fact", mutation=False,
                 argument_roles={"graph": "target_resource",
                                 "predicate": "target_resource"}),
    # Asserting is a create, not an update: the fact did not exist before, and
    # everything that reads the graph afterwards inherits it.
    ToolContract(tool="kg_assert_fact", capability="graph_assert",
                 effect="create", resource_type="fact", mutation=True,
                 argument_roles={"graph": "target_resource",
                                 "subject": "target_resource",
                                 "predicate": "payload",
                                 "object": "payload",
                                 "source": "payload"}),
    ToolContract(tool="kg_retract_fact", capability="graph_retract",
                 effect="delete", resource_type="fact", mutation=True,
                 argument_roles={"id": "target_resource"}),
]


def build_semantic_bundle() -> SemanticBundle:
    """Compose the declarations for whichever sets this deployment serves."""
    sets = enabled_sets()

    signatures: dict[str, ToolSignature] = {}
    contracts: list[ToolContract] = []
    entities: set[str] = set()
    fields: set[str] = set()

    if "github" in sets:
        github = gh_bundle.build_semantic_bundle()
        signatures.update(github.registry.signatures)
        contracts.extend(github.contracts.contracts.values())
        fields |= {"repo", "number", "label", "title", "body", "state"}

    if "graph" in sets:
        signatures.update(_GRAPH_SIGNATURES)
        contracts.extend(_GRAPH_CONTRACTS)
        fields |= {"graph", "subject", "predicate", "object", "source",
                   "confidence", "object_kind", "id", "contains", "limit"}

    # Open world: subjects, predicates and issue numbers are not enumerable in
    # advance, so a closed index would refuse every real call. The boundary
    # that actually holds is in the registry modules — the repository
    # allowlist and the non-negotiable tenant clause — not here.
    state = StateIndex.from_values(
        entities or {"__unbounded__"},
        (CoverageScope("gateway", frozenset(fields), closed_world=False),),
    )
    return SemanticBundle.build(
        registry=ToolRegistry(signatures=signatures),
        contracts=ToolContractRegistry(contracts),
        validators=None,
        state=state,
    )
