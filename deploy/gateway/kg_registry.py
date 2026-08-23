# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Governed knowledge-graph tools for the MCP gateway (exeQta).

The graph is a triple store with provenance: every fact carries a ``source``,
a ``confidence`` and an ``assertion_kind``. That is what makes writing to it
worth governing. A fact asserted here does not stay here — everything that
reads the graph afterwards inherits it, and a wrong fact with a confident
source is worse than no fact at all.

Two properties are enforced in this module rather than left to policy:

**The tenant is not a parameter.** It comes from deployment configuration and
is written into every statement. A caller cannot name a tenant, so no
proposal, however well-formed, can read or write across the boundary.

**Reads and writes take different paths.** Reads are parameterised queries
over a fixed set of shapes; there is no free-text SQL surface for an agent to
reach, because a tool that accepts SQL is not a governed tool.

The database is reached through the Worker that owns this container, not over
the public API with a token. The container makes a plain HTTP request to an
internal hostname; the Worker intercepts it and uses its D1 binding. There is
therefore no database credential inside the container at all — a binding
cannot be read out of a process and reused somewhere else, which a token can.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable

#: Intercepted by the Worker's outbound handler, which holds the D1 binding.
#: Nothing resolves this name on the public internet; if the interception is
#: not configured the request fails rather than escaping.
_GRAPH_ENDPOINT = "http://graph.internal/query"
_TIMEOUT = 20

#: Object kinds the graph recognises. A fact whose kind is not one of these
#: cannot be read back correctly by anything downstream.
_OBJECT_KINDS = frozenset({"literal", "iri", "json", "number", "date"})

#: The graph a human writes tasks into, and the one place an agent may never
#: write. Authority has to come from somewhere the agent cannot manufacture;
#: if a proposal could assert its own work order first and then act on it, the
#: work order would be worth nothing.
INTENT_GRAPH = "urn:remora:intents"

#: Only ASSERTED is available to an agent. RETRACTED and INFERRED are produced
#: by the graph's own machinery, and letting a proposal claim either would be
#: letting it forge provenance.
_AGENT_ASSERTION_KIND = "ASSERTED"


class GraphUnavailable(RuntimeError):
    """The graph could not be reached or the request was refused."""


def _config(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise GraphUnavailable(
            f"{name} is not set. The governed graph tools hold the "
            "credential and the tenant; without them there is nothing to "
            "govern."
        )
    return value


def _tenant() -> str:
    """The tenant this deployment speaks for.

    Deliberately not an argument. A tool that accepted a tenant id would make
    cross-tenant access a matter of what the agent proposed, which is exactly
    the boundary this exists to hold.
    """
    return _config("REMORA_KG_TENANT")


def _query(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    """Run one parameterised statement against the graph database.

    Goes to the Worker rather than to Cloudflare's API: the Worker holds the
    D1 binding, so this process never holds a credential for the graph.
    """
    body = json.dumps({"sql": sql, "params": params}).encode()
    req = urllib.request.Request(_GRAPH_ENDPOINT, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            payload = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise GraphUnavailable(f"graph returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GraphUnavailable(f"graph unreachable: {exc.reason}") from exc

    if not payload.get("success"):
        raise GraphUnavailable(f"graph refused: {str(payload.get('errors'))[:300]}")
    rows: list[dict[str, Any]] = []
    for result in payload.get("result", []):
        rows.extend(result.get("results", []))
    return rows


def _clamped_limit(value: Any) -> int:
    """A row limit between 1 and 200, defaulting to 50 when unset.

    An explicit 0 clamps to 1 rather than falling back to the default: a
    caller that names a value should get that value bounded, not silently
    replaced by one it did not ask for.
    """
    if value is None or value == "":
        return 50
    try:
        return max(1, min(int(value), 200))
    except (TypeError, ValueError):
        return 50


# ── reads ───────────────────────────────────────────────────────────────────

def kg_list_graphs(_a: dict[str, Any]) -> dict[str, Any]:
    rows = _query(
        "SELECT graph_uri, class FROM knowledge_namespaces "
        "WHERE tenant_id = ? ORDER BY graph_uri",
        [_tenant()])
    return {"tenant": _tenant(), "graphs": rows}


def kg_query_facts(a: dict[str, Any]) -> dict[str, Any]:
    """Facts matching a subject and optionally a predicate.

    A fixed shape rather than a query language: the agent chooses values, not
    the statement.
    """
    graph = str(a.get("graph", ""))
    subject = str(a.get("subject", ""))
    predicate = str(a.get("predicate", "") or "")
    limit = _clamped_limit(a.get("limit"))

    sql = ("SELECT id, subject, predicate, object_json, object_kind, source, "
           "confidence, assertion_kind, observed_at FROM knowledge_facts "
           "WHERE tenant_id = ? AND graph = ? AND subject = ?")
    params: list[Any] = [_tenant(), graph, subject]
    if predicate:
        sql += " AND predicate = ?"
        params.append(predicate)
    sql += " ORDER BY kg_seq DESC LIMIT ?"
    params.append(limit)

    return {"tenant": _tenant(), "graph": graph, "subject": subject,
            "facts": _query(sql, params)}


def kg_find_subjects(a: dict[str, Any]) -> dict[str, Any]:
    """Subjects that carry a given predicate/object pair — the reverse lookup."""
    graph = str(a.get("graph", ""))
    predicate = str(a.get("predicate", ""))
    contains = str(a.get("contains", "") or "")
    limit = _clamped_limit(a.get("limit"))

    sql = ("SELECT DISTINCT subject, predicate, object_json FROM knowledge_facts "
           "WHERE tenant_id = ? AND graph = ? AND predicate = ?")
    params: list[Any] = [_tenant(), graph, predicate]
    if contains:
        sql += " AND object_json LIKE ?"
        params.append(f"%{contains}%")
    sql += " ORDER BY kg_seq DESC LIMIT ?"
    params.append(limit)

    return {"tenant": _tenant(), "graph": graph, "predicate": predicate,
            "subjects": _query(sql, params)}


# ── writes ──────────────────────────────────────────────────────────────────

def kg_assert_fact(a: dict[str, Any]) -> dict[str, Any]:
    """Assert one fact into the graph.

    The declared delta is returned rather than the whole row, so a
    postcondition reader has something small and explicit to compare against.

    ``source`` is required and records where the claim came from. It is the
    difference between a graph that can be audited and one that merely
    contains things.
    """
    graph = str(a.get("graph", ""))
    subject = str(a.get("subject", ""))
    predicate = str(a.get("predicate", ""))
    object_kind = str(a.get("object_kind", "literal")).lower()
    source = str(a.get("source", ""))

    if graph == INTENT_GRAPH:
        raise GraphUnavailable(
            f"{INTENT_GRAPH} is the intent graph and is not writable here. "
            "An agent that could assert its own work order and then act on it "
            "would make the work order worth nothing."
        )
    if object_kind not in _OBJECT_KINDS:
        raise GraphUnavailable(
            f"object_kind {object_kind!r} is not one of {sorted(_OBJECT_KINDS)}"
        )
    if not source:
        raise GraphUnavailable(
            "source is required: a fact with no recorded origin cannot be "
            "audited, and an unauditable graph is not a governed one"
        )
    for name, value in (("graph", graph), ("subject", subject),
                        ("predicate", predicate)):
        if not value:
            raise GraphUnavailable(f"{name} is required")

    try:
        confidence = float(a.get("confidence", 1.0))
    except (TypeError, ValueError) as exc:
        raise GraphUnavailable("confidence must be a number") from exc
    if not 0.0 <= confidence <= 1.0:
        raise GraphUnavailable("confidence must be between 0 and 1")

    object_json = json.dumps(a.get("object"))
    fact_id = str(uuid.uuid4())
    now = int(time.time())

    _query(
        "INSERT INTO knowledge_facts (id, tenant_id, graph, subject, "
        "predicate, object_json, object_kind, source, confidence, "
        "assertion_kind, observed_at, kg_seq, created_at) VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,"
        # kg_seq is unique per TENANT, not per graph: the graph carries one
        # sequence across all of its namespaces. Scoping this to the graph
        # produced a UNIQUE constraint violation on the first write, which is
        # how the mistake was found.
        "(SELECT COALESCE(MAX(kg_seq),0)+1 FROM knowledge_facts "
        " WHERE tenant_id = ?),?)",
        [fact_id, _tenant(), graph, subject, predicate, object_json,
         object_kind, source, confidence, _AGENT_ASSERTION_KIND, now,
         _tenant(), now])

    return {"tenant": _tenant(), "graph": graph, "id": fact_id,
            "subject": subject, "predicate": predicate,
            "object_json": object_json, "object_kind": object_kind,
            "source": source, "confidence": confidence,
            "assertion_kind": _AGENT_ASSERTION_KIND}


def kg_retract_fact(a: dict[str, Any]) -> dict[str, Any]:
    """Retract a fact this tenant owns.

    A retraction is a delete rather than a tombstone here because the graph
    keeps its own history; what matters for the boundary is that the tenant
    clause is not optional, so a proposal cannot retract someone else's fact
    by guessing an id.
    """
    fact_id = str(a.get("id", ""))
    if not fact_id:
        raise GraphUnavailable("id is required")

    existing = _query(
        "SELECT id, graph, subject, predicate FROM knowledge_facts "
        "WHERE tenant_id = ? AND id = ? AND graph != ?",
        [_tenant(), fact_id, INTENT_GRAPH])
    if not existing:
        raise GraphUnavailable(
            f"no retractable fact {fact_id!r} belongs to this tenant. Facts "
            f"in {INTENT_GRAPH} are excluded: retracting the authority a call "
            "was made under is not something the call may do."
        )

    _query("DELETE FROM knowledge_facts WHERE tenant_id = ? AND id = ? "
           "AND graph != ?", [_tenant(), fact_id, INTENT_GRAPH])
    return {"tenant": _tenant(), "retracted": existing[0]}


TOOLS: tuple[tuple[str, Callable[[dict[str, Any]], Any]], ...] = (
    ("kg_list_graphs", kg_list_graphs),
    ("kg_query_facts", kg_query_facts),
    ("kg_find_subjects", kg_find_subjects),
    ("kg_assert_fact", kg_assert_fact),
    ("kg_retract_fact", kg_retract_fact),
)


def register_tools(register: Callable[[str, Callable[[Any], Any]], None]) -> None:
    for name, fn in TOOLS:
        register(name, fn)


def read_intent(subject: str) -> dict[str, Any]:
    """The task a call claims to act under, from the intent graph.

    Used by the semantic bundle, not exposed as a tool. Returns an empty dict
    when the subject carries no intent: unresolvable authority means UNKNOWN,
    which sends the call to review rather than letting it through.
    """
    rows = _query(
        "SELECT predicate, object_json FROM knowledge_facts "
        "WHERE tenant_id = ? AND graph = ? AND subject = ? "
        "ORDER BY kg_seq ASC",
        [_tenant(), INTENT_GRAPH, subject])
    if not rows:
        return {}
    out: dict[str, Any] = {}
    for row in rows:
        try:
            out[str(row["predicate"])] = json.loads(row["object_json"])
        except (KeyError, ValueError):
            continue
    return out
