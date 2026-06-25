"""Tests for OpenTelemetry-ready observability (no-op mode)."""
from __future__ import annotations


from remora.observability.otel import (
    NoOpSpan,
    NoOpTracer,
    RemoraSpan,
    RemoraTracer,
    get_remora_tracer,
    otel_available,
)


class TestOtelAvailability:
    def test_otel_available_returns_bool(self) -> None:
        assert isinstance(otel_available(), bool)

    def test_get_remora_tracer_returns_tracer(self) -> None:
        tracer = get_remora_tracer()
        assert isinstance(tracer, (RemoraTracer, NoOpTracer))


class TestNoOpSpan:
    def test_context_manager_noop(self) -> None:
        span = NoOpSpan()
        with span as s:
            s.set_thermodynamic(H=0.5, D=0.3, phase="ordered")
            s.set_outcome(action="accept", trust_score=0.87)

    def test_set_attribute_noop(self) -> None:
        span = NoOpSpan()
        span.set_attribute("custom.key", "value")

    def test_record_exception_noop(self) -> None:
        span = NoOpSpan()
        span.record_exception(ValueError("test"))

    def test_all_set_thermodynamic_fields(self) -> None:
        span = NoOpSpan()
        span.set_thermodynamic(
            H=0.5,
            D=0.3,
            F=-0.2,
            phase="critical",
            temperature=0.6,
        )

    def test_all_set_outcome_fields(self) -> None:
        span = NoOpSpan()
        span.set_outcome(
            action="verify",
            trust_score=0.55,
            confidence=0.55,
            risk_estimate=0.45,
        )


class TestNoOpTracer:
    def test_query_span_context_manager(self) -> None:
        tracer = NoOpTracer()
        with tracer.query_span("Is the contract enforceable?") as span:
            assert isinstance(span, NoOpSpan)
            span.set_thermodynamic(H=0.4, D=0.2, phase="ordered")

    def test_stage_span_context_manager(self) -> None:
        tracer = NoOpTracer()
        with tracer.stage_span("fast_gate") as span:
            assert isinstance(span, NoOpSpan)
            span.set_outcome(action="accept", trust_score=0.9)

    def test_all_cascade_stages(self) -> None:
        tracer = NoOpTracer()
        stages = ["fast_gate", "consensus_gate", "verifier_gate", "critique_revision", "self_consistency"]
        for stage in stages:
            with tracer.stage_span(stage) as span:
                assert span is not None

    def test_nested_spans_allowed(self) -> None:
        tracer = NoOpTracer()
        with tracer.query_span("test") as query_span:
            with tracer.stage_span("fast_gate") as stage_span:
                stage_span.set_thermodynamic(H=0.3)
            query_span.set_outcome(action="accept")

    def test_no_exception_on_arbitrary_attributes(self) -> None:
        tracer = NoOpTracer()
        with tracer.stage_span("custom_stage", custom_attr="value") as _:
            pass


class TestRemoraTracerInterface:
    def test_remora_tracer_uses_noop_when_no_otel(self) -> None:
        tracer = get_remora_tracer("test-service")
        if not otel_available():
            assert isinstance(tracer, NoOpTracer)

    def test_tracer_service_name_stored(self) -> None:
        tracer = RemoraTracer(service_name="remora-test")
        assert tracer.service_name == "remora-test"

    def test_span_returns_remora_span(self) -> None:
        tracer = NoOpTracer()
        span = tracer._start_span("test.span")
        assert isinstance(span, RemoraSpan)
