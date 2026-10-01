# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The nested effects of one execution, as bounded evidence (NTA-2 phase 2).

A parent execution is not one opaque effect: each mediated child is recorded
with what was asked, under which authority, and what became of it. The graph
is bounded, and an unknown child keeps the whole execution from reading as
settled.
"""
from __future__ import annotations

from datetime import UTC, datetime

from remora.capabilities import CapabilityRefusal
from remora.enforcement.capability_mediator import CapabilityMediator, EffectState
from remora.enforcement.effect_capability import derive_effect_authority
from remora.enforcement.effect_graph import MAX_NESTED_EFFECTS, ResolvedEffectGraph
from remora.enforcement.execution_context import ExecutionContext
from tests.capabilities.test_capability_mediation import CEILING, _parent


def _mediator(executors=None, max_effects=MAX_NESTED_EFFECTS):
    parent = _parent()
    authority = derive_effect_authority(parent, tool_name="report.generate",
                                        ceiling=CEILING, now=datetime.now(UTC))
    context = ExecutionContext.for_dispatch(
        tool_name="report.generate", capability_set=parent, proposal_id="p-1",
        policy_bundle_hash="b1", toolspec_hash="ts-1", lease_digest="lease-1")
    return CapabilityMediator(context, authority, max_effects=max_effects,
                              executors=executors or {
                                  "filesystem.read": lambda r, a: "ok",
                                  "database.read": lambda r, a: "rows"})


def test_an_execution_without_effects_is_settled():
    graph = ResolvedEffectGraph.from_mediator(_mediator(), root_effect_digest=None)
    assert graph.children == () and graph.settled and not graph.truncated
    assert graph.summary()["count"] == 0


def test_every_request_becomes_a_node_in_order():
    m = _mediator()
    m.invoke("database.read", "database://reporting-eu/monthly")
    m.invoke("network.http.post", "https://billing.example/api")
    m.invoke("filesystem.read", "workspace://reports/a.pdf")
    graph = ResolvedEffectGraph.from_mediator(m, root_effect_digest="re-1")
    assert [(n.index, n.capability, n.state) for n in graph.children] == [
        (0, "database.read", "EXECUTED"), (1, "network.http.post", "REFUSED"),
        (2, "filesystem.read", "EXECUTED")]
    assert graph.children[1].refusal == CapabilityRefusal.NOT_ALLOWED.value
    assert graph.root_effect_digest == "re-1" and graph.tool_name == "report.generate"
    assert graph.settled
    assert graph.summary()["by_state"] == {"EXECUTED": 2, "REFUSED": 1}


def test_an_unknown_child_leaves_the_execution_unsettled():
    def boom(resource, args):
        raise TimeoutError("no answer")

    m = _mediator(executors={"filesystem.read": boom})
    m.invoke("filesystem.read", "workspace://reports/a.pdf")
    graph = ResolvedEffectGraph.from_mediator(m, root_effect_digest=None)
    assert graph.children[0].state == EffectState.UNKNOWN.value
    assert graph.settled is False
    assert graph.summary()["settled"] is False


def test_the_graph_is_bounded_and_says_so():
    m = _mediator(max_effects=2)
    for _ in range(5):
        m.invoke("filesystem.read", "workspace://reports/a.pdf")
    assert len(m.records) == 2 and m.overflow == 3
    graph = ResolvedEffectGraph.from_mediator(m, root_effect_digest=None)
    assert len(graph.children) == 2 and graph.truncated and not graph.settled
    assert graph.summary()["overflow"] == 3


def test_requests_past_the_budget_are_refused_not_run():
    calls = []
    m = _mediator(executors={"filesystem.read": lambda r, a: calls.append(r)}, max_effects=1)
    m.invoke("filesystem.read", "workspace://reports/a.pdf")
    effect = m.invoke("filesystem.read", "workspace://reports/b.pdf")
    assert effect.refusal == CapabilityRefusal.EFFECT_BUDGET_EXHAUSTED.value
    assert calls == ["workspace://reports/a.pdf"]


def test_the_digest_covers_every_node_and_the_bound():
    a = _mediator()
    a.invoke("filesystem.read", "workspace://reports/a.pdf")
    b = _mediator()
    b.invoke("filesystem.read", "workspace://reports/b.pdf")
    ga = ResolvedEffectGraph.from_mediator(a, root_effect_digest=None)
    gb = ResolvedEffectGraph.from_mediator(b, root_effect_digest=None)
    assert ga.digest() != gb.digest()
    assert ga.summary()["graph_sha256"] == ga.digest()


def test_results_are_not_part_of_the_graph():
    m = _mediator(executors={"filesystem.read": lambda r, a: "secret body"})
    m.invoke("filesystem.read", "workspace://reports/a.pdf")
    assert "secret body" not in str(ResolvedEffectGraph.from_mediator(
        m, root_effect_digest=None).to_dict())
