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
    monkeypatch.setenv("REMORA_CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("REMORA_KG_DATABASE_ID", "db")
    monkeypatch.setenv("REMORA_CF_API_TOKEN", "tok")


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
