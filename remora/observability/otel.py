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

OpenTelemetry GenAI semantic conventions
----------------------------------------
Governance spans additionally carry the standard ``gen_ai.*`` attributes
(OTel GenAI semantic conventions) so REMORA traces correlate with any other
GenAI-instrumented component in the same trace — agent frameworks, model
gateways, tool runtimes — without a REMORA-specific dashboard:

===============================  =============================================
GenAI semconv attribute          Source
===============================  =============================================
``gen_ai.operation.name``        ``"execute_tool"`` for governed tool calls
``gen_ai.tool.name``             tool name from the governed call
``gen_ai.tool.call.id``          unique per-invocation id (auto-generated if
                                 not supplied — NOT the argument hash, so
                                 replays of identical calls stay distinct)
``gen_ai.agent.id``              caller-provided acting agent id
``gen_ai.conversation.id``       ``PolicyObservation.session_id``
``remora.tool_call_hash``        deterministic canonical argument hash
                                 (``PolicyObservation.tool_call_hash``) —
                                 joins the trace to the DecisionEnvelope
``remora.decision_envelope.id``  evidence-record reference
===============================  =============================================

Spans are created against a pinned OTel schema URL (``OTEL_SCHEMA_URL``) so
attribute interpretation is versioned; bump it deliberately together with
semconv updates.

The REMORA-specific signals (phase, entropy, dissensus, decision, policy
version) remain under the ``remora.*`` namespace — they are governance
attributes with no semconv equivalent, attached to the same span. Use
``tool_governance_span()`` to get both families with semconv-compliant span
naming (``execute_tool {tool.name}``).
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

# Pinned telemetry schema URL — versions the meaning of emitted attributes.
# The GenAI semantic conventions are still evolving; bump this deliberately
# alongside attribute changes, never implicitly.
OTEL_SCHEMA_URL = "https://opentelemetry.io/schemas/1.36.0"


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

    def set_genai_context(
        self,
        operation_name: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        agent_id: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        """Attach OTel GenAI semantic-convention attributes (``gen_ai.*``).

        Emitting the standard attribute names lets REMORA governance spans
        join distributed traces produced by any other GenAI-instrumented
        component (agent framework, model gateway, tool runtime) without
        custom correlation config. Only provided values are set.
        """
        attrs: dict[str, str] = {}
        if operation_name is not None:
            attrs["gen_ai.operation.name"] = operation_name
        if tool_name is not None:
            attrs["gen_ai.tool.name"] = tool_name
        if tool_call_id is not None:
            attrs["gen_ai.tool.call.id"] = tool_call_id
        if agent_id is not None:
            attrs["gen_ai.agent.id"] = agent_id
        if conversation_id is not None:
            attrs["gen_ai.conversation.id"] = conversation_id
        self._set_attrs(attrs)

    def set_governance_outcome(
        self,
        action: str | None = None,
        policy_version: str | None = None,
        source_of_decision: str | None = None,
        human_review_required: bool | None = None,
        decision_envelope_id: str | None = None,
    ) -> None:
        """Attach the governance decision to the span (``remora.*`` family).

        Complements ``set_outcome()`` with the policy-provenance fields audit
        consumers need to correlate a trace with a DecisionEnvelope —
        including the envelope id itself, so the trace links directly to the
        evidentiary record.
        """
        attrs: dict[str, Any] = {}
        if action is not None:
            attrs[self.ATTR_PREFIX + "action"] = action
        if policy_version is not None:
            attrs[self.ATTR_PREFIX + "policy_version"] = policy_version
        if source_of_decision is not None:
            attrs[self.ATTR_PREFIX + "decision_source"] = source_of_decision
        if human_review_required is not None:
            attrs[self.ATTR_PREFIX + "human_review_required"] = human_review_required
        if decision_envelope_id is not None:
            attrs[self.ATTR_PREFIX + "decision_envelope.id"] = decision_envelope_id
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
            # schema_url pins the versioned meaning of emitted attributes.
            self._tracer = _ot_trace.get_tracer(
                service_name, schema_url=OTEL_SCHEMA_URL
            )
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

    @contextlib.contextmanager
    def tool_governance_span(
        self,
        tool_name: str,
        *,
        invocation_id: str | None = None,
        tool_call_hash: str | None = None,
        agent_id: str | None = None,
        conversation_id: str | None = None,
        **attributes: Any,
    ) -> Iterator[RemoraSpan]:
        """Span for one governed tool call, named per the OTel GenAI
        semantic conventions (``execute_tool {tool_name}``) and stamped with
        the ``gen_ai.*`` attribute family plus any ``remora.*`` extras.

        ``invocation_id`` becomes ``gen_ai.tool.call.id`` and must be unique
        per invocation (auto-generated when omitted) — two replays of the
        identical call get distinct ids. The deterministic canonical argument
        hash goes to ``remora.tool_call_hash`` instead, where it joins the
        trace to the DecisionEnvelope and the enforcement gate's binding.

        Usage::

            with tracer.tool_governance_span(
                "update_work_order",
                tool_call_hash=obs.tool_call_hash,
                agent_id="agent://maintenance-planner/07",
                conversation_id=obs.session_id,
            ) as span:
                report = engine.decide(obs)
                span.set_governance_outcome(
                    action=report.action.value,
                    policy_version=report.policy_version,
                    source_of_decision=report.source_of_decision,
                    human_review_required=report.human_review_required,
                )
        """
        import uuid as _uuid

        span = self._start_span(f"execute_tool {tool_name}", dict(attributes))
        span.set_genai_context(
            operation_name="execute_tool",
            tool_name=tool_name,
            tool_call_id=invocation_id or str(_uuid.uuid4()),
            agent_id=agent_id,
            conversation_id=conversation_id,
        )
        if tool_call_hash is not None:
            span._set_attrs({RemoraSpan.ATTR_PREFIX + "tool_call_hash": tool_call_hash})
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
