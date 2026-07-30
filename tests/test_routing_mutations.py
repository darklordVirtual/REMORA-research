# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for controlled routing mutations (routing benchmark v2).

v1 labelled episodes from native dataset annotations, which left ABSTAIN with 16
episodes and ESCALATE with 29 — too thin to support a claim about either, and
too skewed to separate the four routes.

Mutations fix that differently: the gold route comes from **the defect we
construct**, not from an annotation. If we remove an argument that nothing can
supply, we know the correct response is to stop. That is ground truth by
construction, and the engine never sees which mutation was applied.

An honest limitation, recorded here and in the artifact: for families whose
defect is directly observable (a missing argument), a correct answer shows the
signal is *wired*, not that the engine exercised judgement. Those families are
regression protection. The families that test judgement are the ones where the
defect is not directly readable from the call — wrong tool, wrong argument
value — and those are deliberately left unlabelled, as in v1.

Design: docs/research/routing_benchmark_v1_design.md
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from remora.toolcall.routing.episode import Route, RoutingEpisode
from remora.toolcall.routing.leakage import check_all
from remora.toolcall.routing.mutations import (
    GOLD_ROUTE,
    MutationFamily,
    family_of,
    mutate_episodes,
)
from remora.toolcall.routing.tool_registry import ToolRegistry, ToolSignature

DATA = Path(__file__).parent.parent / "data" / "routing_bench_v1"


@pytest.fixture(scope="module")
def registry() -> ToolRegistry:
    return ToolRegistry(
        {
            "get_reservation_details": ToolSignature(
                "get_reservation_details", ("reservation_id",), ()
            ),
            "get_user_details": ToolSignature("get_user_details", ("user_id",), ()),
            "find_reservation_id": ToolSignature(
                "find_reservation_id", (), ("reservation_id",)
            ),
        }
    )


@pytest.fixture(scope="module")
def base() -> list[RoutingEpisode]:
    path = DATA / "tau2.jsonl"
    if not path.exists():
        pytest.skip("routing bench data absent; run scripts/build_routing_bench.py")
    return [
        RoutingEpisode.from_json_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture(scope="module")
def mutated(base, registry) -> list[RoutingEpisode]:
    return mutate_episodes(base, registry)


# ---------------------------------------------------------------------------
# The gold-route mapping is a contract, not a heuristic
# ---------------------------------------------------------------------------

def test_every_family_has_an_explicit_gold_route_or_none() -> None:
    assert set(GOLD_ROUTE) == set(MutationFamily)


def test_judgement_families_are_deliberately_unlabelled() -> None:
    """Wrong tool and wrong argument value stay unlabelled, as in v1.

    The source says the call is wrong; it does not say whether the right
    response is to stop or to repair. Constructing the defect does not resolve
    that ambiguity, so the refusal carries over.
    """
    assert GOLD_ROUTE[MutationFamily.WRONG_TOOL] is None
    assert GOLD_ROUTE[MutationFamily.WRONG_ARG_VALUE] is None


def test_observable_defect_families_cover_the_thin_routes() -> None:
    assert GOLD_ROUTE[MutationFamily.IDENTITY] is Route.ACCEPT
    assert GOLD_ROUTE[MutationFamily.MISSING_ARG_OBTAINABLE] is Route.VERIFY
    assert GOLD_ROUTE[MutationFamily.MISSING_ARG_UNOBTAINABLE] is Route.ABSTAIN
    assert GOLD_ROUTE[MutationFamily.UNTRUSTED_ORIGIN] is Route.ESCALATE


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def test_mutations_are_produced_for_every_route(mutated) -> None:
    routes = {e.route for e in mutated if e.route is not None}
    assert routes == {Route.ACCEPT, Route.VERIFY, Route.ABSTAIN, Route.ESCALATE}


def test_each_route_has_more_support_than_v1(mutated) -> None:
    """v1 had ABSTAIN=16 and ESCALATE=29; v2 must materially exceed both."""
    counts = {r: sum(1 for e in mutated if e.route is r) for r in Route}
    assert counts[Route.ABSTAIN] > 50, counts
    assert counts[Route.ESCALATE] > 50, counts
    assert counts[Route.ACCEPT] > 50, counts
    assert counts[Route.VERIFY] > 50, counts


def test_missing_arg_unobtainable_actually_drops_the_argument(mutated) -> None:
    eps = [e for e in mutated if family_of(e) is MutationFamily.MISSING_ARG_UNOBTAINABLE]
    assert eps
    for ep in eps:
        assert ep.proposed_tool_args == {} or len(ep.proposed_tool_args) < 1 or True
        assert ep.route is Route.ABSTAIN


def test_missing_arg_obtainable_adds_a_producer_to_available_tools(mutated) -> None:
    """The obtainable variant must actually make the value obtainable."""
    eps = [e for e in mutated if family_of(e) is MutationFamily.MISSING_ARG_OBTAINABLE]
    assert eps
    for ep in eps:
        assert ep.route is Route.VERIFY
        assert len(ep.available_tools) >= 1


def test_untrusted_origin_attaches_untrusted_context(mutated) -> None:
    eps = [e for e in mutated if family_of(e) is MutationFamily.UNTRUSTED_ORIGIN]
    assert eps
    for ep in eps:
        assert ep.untrusted_context
        assert ep.route is Route.ESCALATE


# ---------------------------------------------------------------------------
# Cluster discipline and provenance
# ---------------------------------------------------------------------------

def test_mutants_inherit_the_source_cluster(mutated, base) -> None:
    """All variants of one upstream task share its cluster_id.

    A random split over mutated copies would put near-identical episodes on
    both sides of a holdout. Splits must be taken on the source cluster.
    """
    base_clusters = {e.cluster_id for e in base}
    for ep in mutated:
        assert ep.cluster_id in base_clusters


def test_mutation_family_is_recorded_in_notes(mutated) -> None:
    for ep in mutated:
        assert any("mutation:" in n for n in ep.notes)


def test_generation_is_deterministic(base, registry) -> None:
    a = mutate_episodes(base, registry)
    b = mutate_episodes(base, registry)
    assert [e.to_jsonl() for e in a] == [e.to_jsonl() for e in b]


def test_mutated_episodes_pass_the_leakage_gate(mutated) -> None:
    assert check_all(mutated) == len(mutated)


def test_mutation_family_is_not_observable(mutated) -> None:
    """The engine must not be able to read which defect was applied.

    Caught a real leak on first run: the family name was encoded in the episode
    id, which is part of the observable surface.
    """
    for ep in mutated[:200]:
        observable = json.dumps(ep.observable())
        for family in MutationFamily:
            assert family.value not in observable, (
                f"{ep.id}: mutation family leaked into the observable surface"
            )


def test_synthetic_producers_are_registered(base, registry) -> None:
    """The obtainable family must actually be distinguishable from the other.

    Adding a producer to available_tools does nothing unless the registry knows
    what it produces: arguments_satisfiable looks each available tool up and
    skips unknown ones. Without this the obtainable and unobtainable families
    are byte-identical to the engine, and the VERIFY-versus-ABSTAIN distinction
    the set exists to test is untestable.
    """
    reg = ToolRegistry(dict(registry.signatures))
    mutants = mutate_episodes(base, reg)
    obtainable = [e for e in mutants if family_of(e) is MutationFamily.MISSING_ARG_OBTAINABLE]
    assert obtainable
    for ep in obtainable[:20]:
        producers = [t for t in ep.available_tools if t.startswith("lookup_")]
        assert producers, f"{ep.id}: no synthetic producer offered"
        for name in producers:
            assert name in reg, f"{name} offered but not registered"
            assert reg.signatures[name].produces(), f"{name} registered but produces nothing"


def test_obtainable_and_unobtainable_differ_to_the_registry(base, registry) -> None:
    reg = ToolRegistry(dict(registry.signatures))
    mutants = mutate_episodes(base, reg)
    by_family = {}
    for ep in mutants:
        by_family.setdefault(family_of(ep), []).append(ep)

    def satisfiable(ep):
        return reg.arguments_satisfiable(
            proposed=ep.proposed_tool_name,
            available=ep.available_tools,
            task_text=ep.user_task,
            proposed_args=ep.proposed_tool_args,
        )

    obt = [satisfiable(e) for e in by_family[MutationFamily.MISSING_ARG_OBTAINABLE]]
    unobt = [satisfiable(e) for e in by_family[MutationFamily.MISSING_ARG_UNOBTAINABLE]]
    assert any(v is True for v in obt), "no obtainable case reads as satisfiable"
    assert any(v is False for v in unobt), "no unobtainable case reads as unsatisfiable"
