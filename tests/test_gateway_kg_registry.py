# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The governed knowledge-graph tools.

The network is never touched: what is under test is the boundary this module
holds on its own, before any policy decision is made.

Two properties matter more than the rest. The tenant is not something a
caller can name, and there is no free-text SQL surface — a tool that accepts
SQL is not a governed tool, whatever the policy engine says about it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy.gateway import kg_registry as kg  # noqa: E402

TENANT = "luftfiber"


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setenv("REMORA_KG_TENANT", TENANT)


@pytest.fixture()
def captured(monkeypatch):
    """Record every statement instead of executing it."""
    calls: list[tuple[str, list]] = []

    def fake_query(sql, params):
        calls.append((sql, params))
        return []

    monkeypatch.setattr(kg, "_query", fake_query)
    return calls


# ── the tenant boundary ─────────────────────────────────────────────────────

def test_every_statement_binds_the_tenant(captured, monkeypatch):
    """Not one query may reach the database without a tenant clause."""
    monkeypatch.setattr(kg, "_query", lambda sql, params: (
        captured.append((sql, params)) or
        [{"id": "f1", "graph": "g", "subject": "s", "predicate": "p"}]))

    kg.kg_list_graphs({})
    kg.kg_query_facts({"graph": "g", "subject": "s"})
    kg.kg_find_subjects({"graph": "g", "predicate": "p"})
    kg.kg_assert_fact({"graph": "g", "subject": "s", "predicate": "p",
                       "object": 1, "source": "test"})
    kg.kg_retract_fact({"id": "f1"})

    assert captured, "nothing was executed"
    for sql, params in captured:
        assert "tenant_id = ?" in sql, f"no tenant clause: {sql[:80]}"
        assert TENANT in params, f"tenant not bound: {sql[:80]}"


def test_a_caller_cannot_name_a_tenant(captured):
    """A tenant_id in the arguments must be ignored, not honoured."""
    kg.kg_query_facts({"graph": "g", "subject": "s", "tenant_id": "someone-else"})
    _, params = captured[0]
    assert "someone-else" not in params
    assert TENANT in params


def test_a_missing_tenant_is_a_refusal_not_a_wildcard(monkeypatch):
    monkeypatch.delenv("REMORA_KG_TENANT", raising=False)
    with pytest.raises(kg.GraphUnavailable) as exc:
        kg.kg_list_graphs({})
    assert "REMORA_KG_TENANT" in str(exc.value)


def test_retracting_a_fact_outside_the_tenant_is_refused(monkeypatch):
    monkeypatch.setattr(kg, "_query", lambda sql, params: [])
    with pytest.raises(kg.GraphUnavailable) as exc:
        kg.kg_retract_fact({"id": "someone-elses-fact"})
    assert "belongs to this tenant" in str(exc.value)


def test_a_retraction_checks_ownership_before_deleting(captured, monkeypatch):
    seen: list[str] = []

    def fake_query(sql, params):
        seen.append(sql.strip().split()[0].upper())
        return [{"id": "f1", "graph": "g", "subject": "s", "predicate": "p"}]

    monkeypatch.setattr(kg, "_query", fake_query)
    kg.kg_retract_fact({"id": "f1"})
    assert seen[0] == "SELECT", "ownership must be established before deleting"
    assert "DELETE" in seen


# ── no query surface ────────────────────────────────────────────────────────

def test_no_tool_accepts_free_text_sql(captured):
    """Arguments choose values; they never compose the statement."""
    kg.kg_query_facts({
        "graph": "g",
        "subject": "s'; DROP TABLE knowledge_facts; --",
    })
    sql, params = captured[0]
    assert "DROP TABLE" not in sql
    assert "s'; DROP TABLE knowledge_facts; --" in params


def test_the_limit_is_clamped(captured):
    kg.kg_query_facts({"graph": "g", "subject": "s", "limit": 100000})
    assert 200 in captured[0][1]
    captured.clear()
    kg.kg_query_facts({"graph": "g", "subject": "s", "limit": 0})
    assert 1 in captured[0][1]


# ── what may be asserted ────────────────────────────────────────────────────

def test_a_fact_without_a_source_is_refused(captured):
    with pytest.raises(kg.GraphUnavailable) as exc:
        kg.kg_assert_fact({"graph": "g", "subject": "s", "predicate": "p",
                           "object": 1})
    assert "audited" in str(exc.value)


def test_an_unknown_object_kind_is_refused(captured):
    with pytest.raises(kg.GraphUnavailable):
        kg.kg_assert_fact({"graph": "g", "subject": "s", "predicate": "p",
                           "object": 1, "source": "x", "object_kind": "blob"})


@pytest.mark.parametrize("missing", ["graph", "subject", "predicate"])
def test_the_triple_must_be_complete(captured, missing):
    args = {"graph": "g", "subject": "s", "predicate": "p",
            "object": 1, "source": "x"}
    args[missing] = ""
    with pytest.raises(kg.GraphUnavailable):
        kg.kg_assert_fact(args)


@pytest.mark.parametrize("bad", [-0.1, 1.1, 42])
def test_confidence_must_be_a_probability(captured, bad):
    with pytest.raises(kg.GraphUnavailable):
        kg.kg_assert_fact({"graph": "g", "subject": "s", "predicate": "p",
                           "object": 1, "source": "x", "confidence": bad})


def test_an_agent_cannot_forge_the_assertion_kind(captured):
    """RETRACTED and INFERRED are the graph's own; claiming one is forgery."""
    kg.kg_assert_fact({"graph": "g", "subject": "s", "predicate": "p",
                       "object": 1, "source": "x",
                       "assertion_kind": "INFERRED"})
    _, params = captured[0]
    assert "INFERRED" not in params
    assert kg._AGENT_ASSERTION_KIND in params


def test_the_declared_delta_is_what_a_reader_can_check(captured):
    """The return value is the postcondition, so it stays small and explicit."""
    delta = kg.kg_assert_fact({
        "graph": "g", "subject": "acme", "predicate": "hasStatus",
        "object": "active", "source": "operator:stian", "confidence": 0.9,
    })
    assert delta["subject"] == "acme"
    assert delta["predicate"] == "hasStatus"
    assert json.loads(delta["object_json"]) == "active"
    assert delta["source"] == "operator:stian"
    assert delta["confidence"] == 0.9
    assert delta["tenant"] == TENANT
    assert "id" in delta


def test_every_registered_tool_is_callable():
    for name, fn in kg.TOOLS:
        assert callable(fn), name
    registered: list[str] = []
    kg.register_tools(lambda n, f: registered.append(n))
    assert registered == [n for n, _ in kg.TOOLS]


# ── the intent graph is not the agent's to touch ────────────────────────────

def test_an_agent_cannot_write_its_own_work_order(captured):
    """Authority has to come from somewhere the agent cannot manufacture."""
    with pytest.raises(kg.GraphUnavailable) as exc:
        kg.kg_assert_fact({"graph": kg.INTENT_GRAPH, "subject": "task:x",
                           "predicate": "task_text", "object": "do anything",
                           "source": "agent"})
    assert "worth nothing" in str(exc.value)
    assert not captured, "the refusal must happen before any statement runs"


def test_a_retraction_cannot_reach_the_intent_graph(captured, monkeypatch):
    """Retracting the authority a call was made under is not the call's to do."""
    monkeypatch.setattr(kg, "_query", lambda sql, params: (
        captured.append((sql, params)) or []))
    with pytest.raises(kg.GraphUnavailable) as exc:
        kg.kg_retract_fact({"id": "some-intent-fact"})
    assert kg.INTENT_GRAPH in str(exc.value)
    lookup_sql, lookup_params = captured[0]
    assert "graph != ?" in lookup_sql
    assert kg.INTENT_GRAPH in lookup_params


def test_reading_an_intent_binds_tenant_and_intent_graph(captured):
    kg.read_intent("task:onboard-acme")
    sql, params = captured[0]
    assert "tenant_id = ?" in sql and "graph = ?" in sql
    assert TENANT in params and kg.INTENT_GRAPH in params


def test_an_absent_task_reads_as_empty_not_permissive(captured):
    assert kg.read_intent("task:does-not-exist") == {}


def test_an_intent_is_assembled_from_its_predicates(monkeypatch):
    monkeypatch.setattr(kg, "_query", lambda sql, params: [
        {"predicate": "task_text", "object_json": '"Record Acme as active."'},
        {"predicate": "operation", "object_json": '"create"'},
    ])
    task = kg.read_intent("task:onboard-acme")
    assert task["task_text"] == "Record Acme as active."
    assert task["operation"] == "create"


# ── no credential in this process ───────────────────────────────────────────

def test_the_graph_is_reached_through_the_worker_not_the_public_api():
    """A binding cannot be read out of a process and reused; a token can."""
    assert "api.cloudflare.com" not in kg._GRAPH_ENDPOINT
    assert kg._GRAPH_ENDPOINT.startswith("http://")


def test_no_database_credential_is_read_from_the_environment(monkeypatch):
    """Only the tenant. Nothing here should be reachable with a stolen token."""
    for leaked in ("REMORA_CF_API_TOKEN", "CLOUDFLARE_API_TOKEN",
                   "REMORA_KG_DATABASE_ID"):
        monkeypatch.setenv(leaked, "should-not-be-used")
    source = (Path(kg.__file__)).read_text(encoding="utf-8")
    for leaked in ("REMORA_CF_API_TOKEN", "CLOUDFLARE_API_TOKEN"):
        assert leaked not in source, f"{leaked} is still read by the registry"


def test_the_sequence_is_scoped_to_the_tenant_not_the_graph(captured):
    """kg_seq is unique per tenant.

    idx_knowledge_facts_tenant_seq_unique is on (tenant_id, kg_seq). Scoping
    the next-value subquery to the graph as well produced a UNIQUE constraint
    violation on the very first write, which is how this was found. The graph
    carries one sequence across all of its namespaces.
    """
    kg.kg_assert_fact({"graph": "g", "subject": "s", "predicate": "p",
                       "object": 1, "source": "test"})
    sql, params = captured[0]
    assert "MAX(kg_seq)" in sql
    subquery = sql[sql.index("MAX(kg_seq)"):]
    assert "graph = ?" not in subquery, (
        "the sequence subquery must not be scoped to the graph"
    )
    assert subquery.count("tenant_id = ?") == 1


def test_the_vocabulary_can_be_discovered(captured):
    """The query tools were unusable without this.

    They take a subject or a predicate and nothing told you what either
    looked like. A governed tool that cannot be used is not a control, it is
    an obstacle.
    """
    kg.kg_list_predicates({"graph": "g"})
    kg.kg_sample_subjects({"graph": "g"})
    assert len(captured) == 2
    for sql, params in captured:
        assert "tenant_id = ?" in sql and TENANT in params
        assert "GROUP BY" in sql
