# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""An unknown graph response must not read as an empty result set.

`_query` already failed closed on the transport: HTTPError, URLError and an
explicit ``success: false`` all raise ``GraphUnavailable``. One path did not:

    for result in payload.get("result", []):
        rows.extend(result.get("results", []))

A response missing ``result``, or carrying an unexpected shape, produced ``[]``
-- indistinguishable from a graph that legitimately matched nothing. The
surrounding tool then reports a successful read of no data, and a caller cannot
tell "no rows" from "no answer".

That is the same distinction REMORA's effect model insists on elsewhere:
not knowing is its own outcome, and must never be reported as a known one.

The boundary these tests defend is narrow and deliberate. An empty ``results``
list is LEGAL and must stay legal -- a query that matches nothing is not an
outage, and turning it into one would be a worse failure than the one being
fixed.

Scope note, because it matters for what this change can be said to fix: this
makes an unknown response VISIBLE. If the graph is in fact answering
``{"success": true, "result": [{"results": []}]}``, that is a well-formed empty
answer and these guards will not fire -- the cause would then be binding,
database, tenant or container generation, and this change improves the signal
rather than repairing the fault.
"""
from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy.gateway import kg_registry as kg  # noqa: E402


class _Resp:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _answers(payload: object, monkeypatch, *, raw: bytes | None = None):
    """Make the graph endpoint answer with exactly this body."""
    body = raw if raw is not None else json.dumps(payload).encode()
    monkeypatch.setattr(kg.urllib.request, "urlopen",
                        lambda *_a, **_k: _Resp(body))


def _query():
    return kg._query("SELECT 1 FROM knowledge_facts WHERE tenant_id = ?", ["t"])


# ── what must still work ────────────────────────────────────────────────────

def test_rows_are_returned(monkeypatch):
    _answers({"success": True,
              "result": [{"results": [{"predicate": "ex:x", "uses": 3}]}]},
             monkeypatch)
    assert _query() == [{"predicate": "ex:x", "uses": 3}]


def test_an_empty_result_set_is_legal(monkeypatch):
    """A query that matches nothing is not an outage.

    The single most important test in this file: the fix must not turn a
    legitimate empty answer into an error, which would be a worse failure than
    the silence it replaces.
    """
    _answers({"success": True, "result": [{"results": []}]}, monkeypatch)
    assert _query() == []


def test_several_result_sets_are_concatenated(monkeypatch):
    _answers({"success": True,
              "result": [{"results": [{"a": 1}]}, {"results": [{"a": 2}]}]},
             monkeypatch)
    assert _query() == [{"a": 1}, {"a": 2}]


# ── the silent path, now closed ─────────────────────────────────────────────

def test_a_missing_result_key_is_unavailable(monkeypatch):
    """The exact regression: success with no payload shape.

    Previously `[]`. A caller could not distinguish this from an empty graph.
    """
    _answers({"success": True}, monkeypatch)
    with pytest.raises(kg.GraphUnavailable, match="no 'result' key"):
        _query()


def test_a_missing_results_key_is_unavailable(monkeypatch):
    _answers({"success": True, "result": [{}]}, monkeypatch)
    with pytest.raises(kg.GraphUnavailable, match="no 'results' key"):
        _query()


@pytest.mark.parametrize("result", ["rows", 7, {"results": []}, None])
def test_a_non_list_result_is_unavailable(monkeypatch, result):
    _answers({"success": True, "result": result}, monkeypatch)
    with pytest.raises(kg.GraphUnavailable, match="expected a list"):
        _query()


@pytest.mark.parametrize("inner", ["rows", 7, None, []])
def test_a_non_object_result_entry_is_unavailable(monkeypatch, inner):
    _answers({"success": True, "result": [inner]}, monkeypatch)
    with pytest.raises(kg.GraphUnavailable, match="expected an object"):
        _query()


@pytest.mark.parametrize("batch", ["rows", 7, {"a": 1}, None])
def test_non_list_results_are_unavailable(monkeypatch, batch):
    _answers({"success": True, "result": [{"results": batch}]}, monkeypatch)
    with pytest.raises(kg.GraphUnavailable, match="expected a list"):
        _query()


def test_a_non_object_payload_is_unavailable(monkeypatch):
    _answers([{"results": []}], monkeypatch)
    with pytest.raises(kg.GraphUnavailable, match="expected an object"):
        _query()


def test_unparseable_json_is_unavailable(monkeypatch):
    """Previously a JSONDecodeError escaped as an unhandled exception type."""
    _answers(None, monkeypatch, raw=b"{not json")
    with pytest.raises(kg.GraphUnavailable, match="unparseable JSON"):
        _query()


# ── the paths that already failed closed, pinned so they stay closed ────────

def test_success_false_keeps_the_d1_error_detail(monkeypatch):
    """The refusal must carry what the database said, not a generic message."""
    _answers({"success": False,
              "errors": [{"message": "no such column: knowledge_facts.tenant"}]},
             monkeypatch)
    with pytest.raises(kg.GraphUnavailable, match="no such column"):
        _query()


def test_an_http_error_is_unavailable(monkeypatch):
    def raise_http(*_a, **_k):
        raise urllib.error.HTTPError(
            kg._GRAPH_ENDPOINT, 503, "Service Unavailable", {},  # type: ignore[arg-type]
            None)

    monkeypatch.setattr(kg.urllib.request, "urlopen", raise_http)
    with pytest.raises(kg.GraphUnavailable, match="503"):
        _query()


def test_an_unreachable_graph_is_unavailable(monkeypatch):
    monkeypatch.setattr(kg.urllib.request, "urlopen",
                        lambda *_a, **_k: (_ for _ in ()).throw(
                            urllib.error.URLError("no route to host")))
    with pytest.raises(kg.GraphUnavailable, match="unreachable"):
        _query()


# ── what the caller sees ────────────────────────────────────────────────────

def test_a_tool_reports_a_refusal_rather_than_an_empty_read(monkeypatch):
    """The contract that made this worth fixing.

    GraphUnavailable is a RuntimeError, so the governed dispatcher refuses the
    call: the response says executed=false with a reason. Before the fix the
    same condition produced executed=true with an empty predicate list, which
    reads as a successful survey of an empty graph.
    """
    _answers({"success": True}, monkeypatch)
    with pytest.raises(kg.GraphUnavailable):
        kg.kg_list_predicates({"graph": "urn:x:business"})

    assert issubclass(kg.GraphUnavailable, RuntimeError), (
        "the dispatcher refuses on RuntimeError; a different base class would "
        "let this escape as a server error instead of a named refusal")
