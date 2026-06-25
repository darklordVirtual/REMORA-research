# Author: Stian Skogbrott
# License: Apache-2.0
"""Topological data analysis — legacy fingerprint clustering.

DEPRECATED for research claims. Use `remora.graph.claim_graph.SemanticClaimGraph`
for rigorous Betti numbers over semantic relations. This module remains for
operational use cases (cheap β0 sanity checks on exact-fingerprint clusters)
but should not be cited as topological analysis in papers.
"""
import warnings
from typing import Dict, List, Set, Tuple

from remora.stability import EXPERIMENTAL
__stability__ = EXPERIMENTAL


def _warn_legacy() -> None:
    warnings.warn(
        "remora.topology.compute_betti_numbers operates on fingerprint clusters; "
        "use remora.graph.claim_graph.SemanticClaimGraph for rigorous β1."
        " Will be removed in v0.7.0.",
        DeprecationWarning,
        stacklevel=2,
    )


def compute_betti_numbers(oracle_verdicts: List[Tuple[str, str]]) -> Dict[str, int]:
    """
    Computes Betti-0 and Betti-1 on the agreement graph of oracles.
    oracle_verdicts: list of (oracle_id, fingerprint)
    """
    _warn_legacy()
    if not oracle_verdicts:
        return {"betti_0": 0, "betti_1": 0}

    # Build graph where nodes are oracles, edges are agreements (same fingerprint)
    oracles = list(set(provider for provider, _ in oracle_verdicts))
    clusters: Dict[str, Set[str]] = {}

    for provider, fp in oracle_verdicts:
        if fp not in clusters:
            clusters[fp] = set()
        clusters[fp].add(provider)

    betti_0 = len(clusters)

    # In a simple exact-match consensus space, exact agreements form fully connected cliques.
    # A true topological hole (β1 > 0) in pure logic occurs if we evaluate partial overlaps
    # (e.g., semantic similarity graph). For exact fingerprints, if an oracle belongs to multiple
    # conflicting clusters (due to fuzzy logic or multi-claim extraction), a cycle can form.
    # Here we simulate β1 by detecting if an oracle is participating in multiple disconnected
    # logical manifolds simultaneously (cognitive dissonance/hallucination cycle).

    oracle_memberships = {o: 0 for o in oracles}
    for cluster in clusters.values():
        for o in cluster:
            oracle_memberships[o] += 1

    # If any oracle is in >1 distinct logical cluster, they bridge an unnatural hole.
    betti_1 = sum(1 for overlaps in oracle_memberships.values() if overlaps > 1)

    return {
        "betti_0": betti_0,
        "betti_1": betti_1,
        "topological_collapse": betti_0 >= 1 and betti_1 > 0
    }


def compute_semantic_betti_numbers(*args, **kwargs):
    """Forwarder to SemanticClaimGraph for callers migrating from this module."""
    from remora.graph.claim_graph import SemanticClaimGraph  # noqa: F401
    raise NotImplementedError(
        "Wire claims into SemanticClaimGraph at the call site; this stub "
        "exists only to point migrators at remora/graph/claim_graph.py"
    )
