# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Issue #45 gap 6: tracing is structural, not decorative.

The audit found spans that never became current (every nested stage span was
born a sibling root), a governance span API called only from tests, and a
custody hop that carried no trace context. These tests pin the three
mechanisms with a real in-memory exporter -- a no-op tracer would pass
vacuously, which is exactly the defect being fixed.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

otel_sdk = pytest.importorskip("opentelemetry.sdk")
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from remora.observability.otel import RemoraTracer  # noqa: E402


@pytest.fixture()
def exporter_and_tracer():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = RemoraTracer(tracer=provider.get_tracer("test"))
    return exporter, tracer


def test_a_stage_span_is_a_child_of_the_query_span(exporter_and_tracer) -> None:
    """The core defect: start_span never attached to context, so this exact
    shape produced two ROOT spans with unrelated traces."""
    exporter, tracer = exporter_and_tracer
    with tracer.query_span("q") as outer:
        outer.set_attribute("remora.domain", "test")
        with tracer.stage_span("fast_gate"):
            pass
    spans = {s.name: s for s in exporter.get_finished_spans()}
    stage, query = spans["remora.cascade.fast_gate"], spans["remora.query"]
    assert stage.context.trace_id == query.context.trace_id, "sibling roots"
    assert stage.parent is not None
    assert stage.parent.span_id == query.context.span_id


def test_the_governed_dispatch_emits_the_genai_span(
    exporter_and_tracer, monkeypatch
) -> None:
    """tool_governance_span gains its first production caller: the shared
    dispatch wrapper. The span joins the audit chain on the proposal id."""
    exporter, tracer = exporter_and_tracer
    from servers import execution_api as exec_mod

    monkeypatch.setattr(exec_mod, "_EXEC_TRACER", tracer)
    monkeypatch.setattr(
        exec_mod, "_dispatch_under_lease_impl",
        lambda **kw: {"executed": True},
    )
    result = exec_mod._dispatch_under_lease(
        tenant="acme", principal="agent-1",
        tool_call=SimpleNamespace(tool_name="wo_close", arguments={},
                                  target_environment="staging"),
        semantic={}, now=datetime.now(UTC), proposal_id="prop-42",
    )
    assert result == {"executed": True}
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "execute_tool wo_close"
    assert span.attributes["gen_ai.tool.call.id"] == "prop-42"
    assert span.attributes["remora.executed"] is True


def test_a_refusal_is_stamped_on_the_dispatch_span(
    exporter_and_tracer, monkeypatch
) -> None:
    exporter, tracer = exporter_and_tracer
    from servers import execution_api as exec_mod

    monkeypatch.setattr(exec_mod, "_EXEC_TRACER", tracer)
    monkeypatch.setattr(
        exec_mod, "_dispatch_under_lease_impl",
        lambda **kw: {"executed": False, "refusal_reason": "pep_denied"},
    )
    exec_mod._dispatch_under_lease(
        tenant="acme", principal="agent-1",
        tool_call=SimpleNamespace(tool_name="wo_close", arguments={},
                                  target_environment="staging"),
        semantic={}, now=datetime.now(UTC), proposal_id="prop-43",
    )
    span = exporter.get_finished_spans()[0]
    assert span.attributes["remora.executed"] is False
    assert span.attributes["remora.refusal_reason"] == "pep_denied"


def test_the_custody_hop_carries_traceparent(
    exporter_and_tracer, monkeypatch
) -> None:
    """W3C context on the authority->executor hop, so the two processes'
    spans join into one trace instead of two unrelated ones."""
    import urllib.request

    from remora.execution import remote_dispatch as rd

    exporter, tracer = exporter_and_tracer
    captured: dict = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout=None):
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with tracer.query_span("authority decision"):
        rd._post("http://executor.internal/x", {"a": 1}, timeout=5)
    assert "traceparent" in captured["headers"], captured["headers"]


def test_no_active_span_means_no_header_and_no_failure(monkeypatch) -> None:
    """Tracing absent or idle must never block a dispatch."""
    import urllib.request

    from remora.execution import remote_dispatch as rd

    captured: dict = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout=None):
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert rd._post("http://executor.internal/x", {"a": 1}, timeout=5) == {}
