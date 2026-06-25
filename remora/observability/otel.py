"""OpenTelemetry-ready distributed tracing for the REMORA cascade pipeline.

Architecture Goal
-----------------
Enterprise deployments running fleets of Claude agents need real-time
observability into the "thermodynamic health" of the AI layer — not just
request latency or error rates, but:

- Which phase (ordered / critical / disordered) queries are landing in.
- How H, D, and F evolve across the cascade stages.
- Which oracle is contributing most uncertainty (bandit attribution).

This module provides ``RemoraTracer``, a lightweight wrapper around the
OpenTelemetry Python API that:

1. Emits one **trace** per incoming query.
2. Emits one **span** per cascade stage (FastGate, Consensus, Verifier,
   CritiqueRevision, SelfConsistency).
3. Attaches H, D, phase, trust_score, and action as **custom span
   attributes** so a Grafana / Datadog / Honeycomb dashboard can visualise
   the thermodynamic state of the entire fleet in real time.

Dependency strategy
-------------------
``opentelemetry-api`` is an optional dependency.  If it is not installed
(the common case for lightweight REMORA deployments), the tracer silently
becomes a no-op.  No import error, no crash.

Install the optional dependency::

    pip install opentelemetry-api opentelemetry-sdk
    # For OTLP export:
    pip install opentelemetry-exporter-otlp

Usage
-----
::

    from remora.observability import get_remora_tracer

    tracer = get_remora_tracer("remora-cascade")

    with tracer.query_span("Is §9-6 of the HSE Act applicable here?") as span:
        # Stage 1
        with tracer.stage_span("fast_gate") as s:
            result = fast_gate(prompt)
            s.set_thermodynamic(H=result.H, D=result.D, phase=result.phase)
            s.set_outcome(trust_score=result.trust, action="accept")

        # Stage 2
        with tracer.stage_span("consensus_gate") as s:
            result = consensus_gate(prompt)
            s.set_thermodynamic(H=result.H, D=result.D, phase=result.phase)

Grafana OTLP dashboard
----------------------
Point the OTLP exporter at your collector::

    export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
    export OTEL_SERVICE_NAME=remora-cascade

Custom span attributes to add as Grafana panels:

- ``remora.phase`` (label values: ordered/critical/disordered)
- ``remora.trust_score`` (histogram, p50/p95/p99)
- ``remora.entropy`` (time series)
- ``remora.dissensus`` (time series)
- ``remora.action`` (pie: accept/verify/abstain/escalate)
"""
from __future__ import annotations

import contextlib
from types import TracebackType
from typing import Any, Iterator

# ---------------------------------------------------------------------------
# Optional OpenTelemetry import — graceful no-op if not installed
# ---------------------------------------------------------------------------

try:
    from opentelemetry import trace as _ot_trace
    _OTEL_AVAILABLE = True
except ImportError:
    _ot_trace = None  # type: ignore[assignment]
    _OTEL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Span interfaces
# ---------------------------------------------------------------------------

class RemoraSpan:
    """A live REMORA span (wraps an OpenTelemetry Span if available)."""

    ATTR_PREFIX = "remora."

    def __init__(self, span: Any) -> None:
        self._span = span

    def set_thermodynamic(
        self,
        H: float | None = None,
        D: float | None = None,
        F: float | None = None,
        phase: str | None = None,
        temperature: float | None = None,
    ) -> None:
        """Attach thermodynamic state as custom span attributes."""
        attrs: dict[str, float | str] = {}
        if H is not None:
            attrs[self.ATTR_PREFIX + "entropy"] = H
        if D is not None:
            attrs[self.ATTR_PREFIX + "dissensus"] = D
        if F is not None:
            attrs[self.ATTR_PREFIX + "free_energy"] = F
        if phase is not None:
            attrs[self.ATTR_PREFIX + "phase"] = phase
        if temperature is not None:
            attrs[self.ATTR_PREFIX + "temperature"] = temperature
        self._set_attrs(attrs)

    def set_outcome(
        self,
        action: str | None = None,
        trust_score: float | None = None,
        confidence: float | None = None,
        risk_estimate: float | None = None,
    ) -> None:
        """Attach decision outcome as custom span attributes."""
        attrs: dict[str, float | str] = {}
        if action is not None:
            attrs[self.ATTR_PREFIX + "action"] = action
        if trust_score is not None:
            attrs[self.ATTR_PREFIX + "trust_score"] = trust_score
        if confidence is not None:
            attrs[self.ATTR_PREFIX + "confidence"] = confidence
        if risk_estimate is not None:
            attrs[self.ATTR_PREFIX + "risk_estimate"] = risk_estimate
        self._set_attrs(attrs)

    def set_attribute(self, key: str, value: Any) -> None:
        """Set an arbitrary span attribute."""
        if _OTEL_AVAILABLE and hasattr(self._span, "set_attribute"):
            self._span.set_attribute(key, value)

    def record_exception(self, exc: Exception) -> None:
        if _OTEL_AVAILABLE and hasattr(self._span, "record_exception"):
            self._span.record_exception(exc)

    def _set_attrs(self, attrs: dict[str, Any]) -> None:
        if _OTEL_AVAILABLE and hasattr(self._span, "set_attributes"):
            self._span.set_attributes(attrs)

    def __enter__(self) -> RemoraSpan:
        if _OTEL_AVAILABLE and hasattr(self._span, "__enter__"):
            self._span.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if _OTEL_AVAILABLE and hasattr(self._span, "__exit__"):
            self._span.__exit__(exc_type, exc_val, exc_tb)


class NoOpSpan(RemoraSpan):
    """A span that does nothing — used when OpenTelemetry is not installed."""

    def __init__(self) -> None:
        super().__init__(None)

    def _set_attrs(self, attrs: dict[str, Any]) -> None:
        pass

    def __enter__(self) -> NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

class RemoraTracer:
    """Wraps OpenTelemetry tracing for the REMORA cascade pipeline.

    Obtain via ``get_remora_tracer()``; do not instantiate directly unless
    you need to pass a specific OTel tracer instance.

    Parameters
    ----------
    service_name:
        OTel service name (appears in Grafana / Tempo traces).
    tracer:
        Pre-built OTel tracer.  If ``None``, constructed from the global
        OTel TracerProvider via ``opentelemetry.trace.get_tracer()``.
    """

    def __init__(self, service_name: str = "remora", tracer: Any = None) -> None:
        self.service_name = service_name
        if tracer is not None:
            self._tracer = tracer
        elif _OTEL_AVAILABLE:
            self._tracer = _ot_trace.get_tracer(service_name)
        else:
            self._tracer = None

    @contextlib.contextmanager
    def query_span(self, prompt: str, **attributes: Any) -> Iterator[RemoraSpan]:
        """Context manager that wraps a full query through the cascade.

        Parameters
        ----------
        prompt:
            The raw query text.  Stored as ``remora.prompt_length`` (length
            only — never the full text, to avoid PII leakage into telemetry).
        attributes:
            Additional span attributes to set.
        """
        span = self._start_span("remora.query", {"remora.prompt_length": len(prompt), **attributes})
        with span:
            yield span

    @contextlib.contextmanager
    def stage_span(self, stage: str, **attributes: Any) -> Iterator[RemoraSpan]:
        """Context manager for a single cascade stage span.

        Parameters
        ----------
        stage:
            Stage name: ``"fast_gate"``, ``"consensus_gate"``,
            ``"verifier_gate"``, ``"critique_revision"``,
            ``"self_consistency"``.
        attributes:
            Initial span attributes.
        """
        span = self._start_span(
            f"remora.cascade.{stage}",
            {RemoraSpan.ATTR_PREFIX + "stage": stage, **attributes},
        )
        with span:
            yield span

    def _start_span(self, name: str, attributes: dict[str, Any] | None = None) -> RemoraSpan:
        if self._tracer is None:
            return NoOpSpan()
        raw_span = self._tracer.start_span(name, attributes=attributes or {})
        return RemoraSpan(raw_span)


class NoOpTracer(RemoraTracer):
    """A tracer that emits no spans — default when OTel is not installed."""

    def __init__(self) -> None:
        super().__init__(tracer=None)
        self._tracer = None

    def _start_span(self, name: str, attributes: dict[str, Any] | None = None) -> NoOpSpan:
        return NoOpSpan()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_remora_tracer(service_name: str = "remora") -> RemoraTracer:
    """Return a RemoraTracer, falling back to NoOpTracer if OTel is absent.

    This is the recommended entry point::

        tracer = get_remora_tracer()

        with tracer.stage_span("fast_gate") as span:
            result = fast_gate(obs)
            span.set_thermodynamic(H=result.H, D=result.D, phase=result.phase)
            span.set_outcome(action=result.action, trust_score=result.trust)
    """
    if _OTEL_AVAILABLE:
        return RemoraTracer(service_name=service_name)
    return NoOpTracer()


def otel_available() -> bool:
    """Return True if the opentelemetry-api package is installed."""
    return _OTEL_AVAILABLE
