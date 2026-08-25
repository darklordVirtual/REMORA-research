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

import logging
import os
import re
from typing import Any

from remora.toolcall.routing.compatibility import CoverageScope, StateIndex
from remora.toolcall.routing.tool_contract import ToolContract, ToolContractRegistry
from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature
from remora.toolcall.semantic_bundle import (
    ArgumentScopeResult,
    IntentResolution,
    SemanticBundle,
)

from deploy.gateway import gh_bundle, kg_intent
from deploy.gateway.registry import enabled_sets

_log = logging.getLogger("remora.gateway.bundle")

def resolve_intent_detailed(intent_ref: str) -> IntentResolution:
    """Resolve authority, from whichever source this deployment has.

    A reference like ``owner/repo#123`` is a GitHub issue; anything else is a
    task subject in the graph's intent namespace. Both are written by a person
    and neither can be manufactured by the agent proposing the call — that is
    the property that matters, not which system holds it.

    Trying GitHub first and falling through is deliberate: a deployment with
    both sets live should not need the caller to know which resolver it is
    talking to.
    """
    sets = enabled_sets()
    if "github" in sets:
        result = gh_bundle.resolve_intent_detailed(intent_ref)
        if result.resolved is not None or result.status == "intent_resolution_failed":
            return result
    if "graph" in sets:
        return kg_intent.resolve_intent_detailed(intent_ref)
    return IntentResolution(None, "intent_not_authorized")


def resolve_intent(intent_ref: str):  # -> ResolvedIntent | None
    """Backward-compatible public resolver used by older deployments/tests."""
    sets = enabled_sets()
    if "github" in sets:
        resolved = gh_bundle.resolve_intent(intent_ref)
        if resolved is not None:
            return resolved
    if "graph" in sets:
        return kg_intent.resolve_intent(intent_ref)
    return None


_TENANT_URN = re.compile(r"^urn:exeqta:tenant:(?P<tenant>[^:]+):")


def validate_argument_scope(
    tool_name: str, arguments: dict[str, Any], tenant: str
) -> ArgumentScopeResult:
    """Hard boundary for tenant-qualified graph values.

    Grounding asks where a value came from. This check asks a different,
    deployment-owned question: whether the value can address the tenant whose
    graph binding this executor is configured to reach. A reviewer cannot
    widen that binding.
    """
    if tool_name not in _GRAPH_SIGNATURES:
        return ArgumentScopeResult(None)
    expected = os.getenv("REMORA_KG_TENANT", "").strip() or tenant.strip()
    if not expected:
        return ArgumentScopeResult(None)

    violating: set[str] = set()
    for name, raw in arguments.items():
        values = raw if isinstance(raw, (list, tuple)) else (raw,)
        for value in values:
            if not isinstance(value, str):
                continue
            match = _TENANT_URN.match(value.strip())
            if match and match.group("tenant") != expected:
                violating.add(str(name))
    if violating:
        return ArgumentScopeResult(False, tuple(sorted(violating)))
    return ArgumentScopeResult(True)

_GRAPH_SIGNATURES = {
    "kg_list_graphs": ToolSignature(
        name="kg_list_graphs", effect="read", required_params=()),
    "kg_list_predicates": ToolSignature(
        name="kg_list_predicates", effect="read", required_params=("graph",)),
    "kg_sample_subjects": ToolSignature(
        name="kg_sample_subjects", effect="read", required_params=("graph",)),
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
    # All three discovery tools aggregate over knowledge_facts rows, so the
    # resource they read is "fact" — the same as the query tools. Declaring
    # them "graph" positively contradicted every task (whose resource is
    # "fact") and refused legitimate discovery calls as wrong-tool.
    ToolContract(tool="kg_list_graphs", capability="graph_read",
                 effect="read", resource_type="fact", mutation=False,
                 argument_roles={}),
    ToolContract(tool="kg_list_predicates", capability="graph_read",
                 effect="read", resource_type="fact", mutation=False,
                 argument_roles={"graph": "target_resource"}),
    ToolContract(tool="kg_sample_subjects", capability="graph_read",
                 effect="read", resource_type="fact", mutation=False,
                 argument_roles={"graph": "target_resource"}),
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
    # A coverage scope is matched by DOMAIN, and the domain is the one the
    # tool metadata declares — not a name chosen here. A scope whose domain
    # matches nothing is never consulted, every value comes back UNKNOWN, and
    # every call is ungrounded. That is how this was found: the scope was
    # called "gateway" while the tools declared "knowledge_graph".
    scopes: list[CoverageScope] = []

    if "github" in sets:
        github = gh_bundle.build_semantic_bundle()
        signatures.update(github.registry.signatures)
        contracts.extend(github.contracts.contracts.values())
        scopes.append(CoverageScope(
            "github",
            frozenset({"repo", "number", "label", "title", "body", "state"}),
            closed_world=False))

    if "graph" in sets:
        signatures.update(_GRAPH_SIGNATURES)
        contracts.extend(_GRAPH_CONTRACTS)
        scopes.append(CoverageScope(
            "knowledge_graph",
            frozenset({"graph", "subject", "predicate", "object", "source",
                       "object_kind", "id", "contains"}),
            closed_world=False))

    if "graph" in sets:
        # The graph is the system of record, so what exists in it is what the
        # state index can confirm. Without this every argument value looks
        # like it came from nowhere and every read waits for a person — the
        # engine cannot tell a real subject from an invented one, so it
        # correctly refuses to tell them apart.
        #
        # Failure here is not fatal: an empty index leaves values ungrounded,
        # which sends calls to review. A bundle that refused to build because
        # the graph was briefly unreachable would be worse.
        # Imported outside the try on purpose: an import that fails is a
        # programming error and must propagate, not be reported as a briefly
        # unreachable graph. Catching it in the same clause also left
        # GraphUnavailable unbound there, so the handler would have raised
        # NameError instead of warning.
        from deploy.gateway.kg_registry import known_values

        try:
            entities |= known_values()
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "could not load known values from the graph (%s); argument "
                "values will be ungrounded and every call will go to review",
                exc)

    # Open world: a value outside the index is ungrounded, not refused. The
    # boundary that actually holds is in the registry modules — the tenant
    # clause that is not a parameter, and the intent graph an agent cannot
    # write — not here.
    state = StateIndex.from_values(entities or {"__unbounded__"},
                                   tuple(scopes))
    return SemanticBundle.build(
        registry=ToolRegistry(signatures=signatures),
        contracts=ToolContractRegistry(contracts),
        validators=None,
        state=state,
    )
