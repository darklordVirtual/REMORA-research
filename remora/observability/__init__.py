"""OpenTelemetry-ready observability for the REMORA cascade pipeline."""

from remora.observability.otel import (
    NoOpSpan,
    NoOpTracer,
    RemoraSpan,
    RemoraTracer,
    get_remora_tracer,
)

__all__ = [
    "NoOpSpan",
    "NoOpTracer",
    "RemoraSpan",
    "RemoraTracer",
    "get_remora_tracer",
]
