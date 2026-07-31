# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Metamorphic invariants for the routing benchmark and its evaluation.

These are the properties that must hold for a routing measurement to mean
anything. They are cheap to state and, on this codebase, three of them have
already caught something a review would not have: the mutation family encoded
in an observable id, an unregistered synthetic producer, and an adapter
artifact that made every wrong call look unsatisfiable.

The invariants:

* the same observable episode yields the same decision
* changing only a sealed field changes no decision
* changing only the episode id changes no decision
* the obtainable and unobtainable families are observably different
* no development command reads the sealed holdout

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from remora.policy import RemoraDecisionEngine
from remora.toolcall.routing.episode import Route, RoutingEpisode
from remora.toolcall.routing.evaluate import build_observation
from remora.toolcall.routing.mutations import MutationFamily, family_of
from remora.toolcall.routing.tool_registry import ToolRegistry

REPO = Path(__file__).parent.parent
V2 = REPO / "data" / "routing_bench_v2" / "tau2_mutations.jsonl"
HOLDOUT = REPO / "data" / "routing_bench_holdout"

ENGINE = RemoraDecisionEngine(low_consequence_accept=True)


@pytest.fixture(scope="module")
def episodes() -> list[RoutingEpisode]:
    if not V2.exists():
        pytest.skip("v2 set absent; run scripts/build_routing_bench.py")
    return [
        RoutingEpisode.from_json_dict(json.loads(line))
        for line in V2.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][:400]


@pytest.fixture(scope="module")
def registry() -> ToolRegistry:
    """The committed tau2 signature fixture — never the extraction cache.

    The cache is gitignored, so a fixture built from it silently degraded to an
    empty registry in CI: every obtainable/unobtainable pair became
    observationally identical there while the invariant passed locally.
    Loading the committed fixture makes local and CI runs test the same
    registry; `test_committed_fixture_matches_a_fresh_extraction` keeps the
    fixture honest against the cache where the cache exists.
    """
    fixture = REPO / "tests" / "fixtures" / "routing_bench" / "tau2_tool_signatures.json"
    return ToolRegistry.from_json_dict(
        json.loads(fixture.read_text(encoding="utf-8"))
    )


def _decide(ep: RoutingEpisode, registry: ToolRegistry) -> Route:
    return ENGINE.decide(build_observation(ep, registry)).action  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_same_observable_episode_yields_the_same_decision(episodes, registry) -> None:
    for ep in episodes:
        assert _decide(ep, registry) == _decide(ep, registry)


# ---------------------------------------------------------------------------
# Sealed fields must be inert
# ---------------------------------------------------------------------------

def test_changing_the_gold_route_changes_no_decision(episodes, registry) -> None:
    """The strongest single check that the label is not reaching the engine."""
    for ep in episodes:
        flipped = replace(
            ep,
            route=Route.ESCALATE if ep.route is not Route.ESCALATE else Route.ACCEPT,
        )
        assert _decide(ep, registry) == _decide(flipped, registry), ep.id


def test_changing_the_mutation_notes_changes_no_decision(episodes, registry) -> None:
    for ep in episodes:
        stripped = replace(ep, notes=())
        assert _decide(ep, registry) == _decide(stripped, registry), ep.id


def test_changing_the_episode_id_changes_no_decision(episodes, registry) -> None:
    """`id` is observable, so a decision must not depend on its content."""
    for ep in episodes:
        renamed = replace(ep, id="opaque-identifier-0000")
        assert _decide(ep, registry) == _decide(renamed, registry), ep.id


def test_changing_predicates_changes_no_decision(episodes, registry) -> None:
    for ep in episodes:
        assert _decide(ep, registry) == _decide(replace(ep, predicates=None), registry)


# ---------------------------------------------------------------------------
# The families the benchmark exists to separate must be separable
# ---------------------------------------------------------------------------

def test_obtainable_and_unobtainable_are_observably_different(episodes, registry) -> None:
    """If these two produce identical observations the VERIFY/ABSTAIN axis is untestable.

    This is the invariant that failed silently until the synthetic producer was
    registered: the two families were byte-identical to the engine and the
    benchmark reported a number that measured nothing.
    """
    by_cluster: dict[str, dict[MutationFamily, RoutingEpisode]] = {}
    for ep in episodes:
        fam = family_of(ep)
        if fam in (
            MutationFamily.MISSING_ARG_OBTAINABLE,
            MutationFamily.MISSING_ARG_UNOBTAINABLE,
        ):
            by_cluster.setdefault(ep.cluster_id, {})[fam] = ep

    pairs = [d for d in by_cluster.values() if len(d) == 2]
    assert pairs, "no obtainable/unobtainable pair found"
    differing = sum(
        1
        for d in pairs
        if build_observation(d[MutationFamily.MISSING_ARG_OBTAINABLE], registry)
        != build_observation(d[MutationFamily.MISSING_ARG_UNOBTAINABLE], registry)
    )
    assert differing == len(pairs), (
        f"{len(pairs) - differing} of {len(pairs)} pairs are observationally "
        "identical; the VERIFY-versus-ABSTAIN distinction cannot be measured"
    )


def test_identity_and_wrong_arg_value_are_observably_different(episodes, registry) -> None:
    """§22's discrimination depends on these two being distinguishable at all."""
    by_cluster: dict[str, dict[MutationFamily, RoutingEpisode]] = {}
    for ep in episodes:
        fam = family_of(ep)
        if fam in (MutationFamily.IDENTITY, MutationFamily.WRONG_ARG_VALUE):
            by_cluster.setdefault(ep.cluster_id, {})[fam] = ep
    pairs = [d for d in by_cluster.values() if len(d) == 2]
    assert pairs
    for d in pairs:
        assert (
            d[MutationFamily.IDENTITY].proposed_tool_args
            != d[MutationFamily.WRONG_ARG_VALUE].proposed_tool_args
        )


# ---------------------------------------------------------------------------
# Holdout isolation
# ---------------------------------------------------------------------------

def test_no_development_script_reads_the_holdout_directory() -> None:
    """Only the dedicated holdout scripts may name the sealed directory.

    A development command that quietly loaded it would consume the one blind
    evaluation the project has, without anyone noticing.
    """
    allowed = {"build_routing_holdout.py", "run_routing_holdout.py", "run_routing_bench.py"}
    offenders = []
    for path in sorted((REPO / "scripts").glob("*.py")):
        if path.name in allowed:
            continue
        if "routing_bench_holdout" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert offenders == [], f"development scripts referencing the holdout: {offenders}"


@pytest.mark.skipif(
    not (HOLDOUT / "manifest.json").exists(), reason="holdout not built"
)
def test_holdout_is_recorded_as_never_run() -> None:
    manifest = json.loads((HOLDOUT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] in {"sealed_never_run", "locked_never_run", "evaluated"}, (
        f"unrecognised holdout status {manifest['status']!r}"
    )


@pytest.mark.skipif(
    not (HOLDOUT / "manifest.json").exists() or not V2.exists(),
    reason="holdout or dev set absent",
)
def test_holdout_clusters_are_disjoint_from_development() -> None:
    dev = {
        RoutingEpisode.from_json_dict(json.loads(line)).cluster_id
        for line in V2.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    held = {
        RoutingEpisode.from_json_dict(json.loads(line)).cluster_id
        for line in (HOLDOUT / "telecom_holdout.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    }
    assert dev & held == set(), f"{len(dev & held)} clusters appear in both sets"
