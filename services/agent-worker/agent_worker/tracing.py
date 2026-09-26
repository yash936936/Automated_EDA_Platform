"""
OpenTelemetry setup for the Python agent worker. Manual spans, same reasoning
as services/api/src/tracing.ts: no framework here to auto-instrument (this
isn't Flask/FastAPI, it's a bare BullMQ job-processing loop), so spans are
created explicitly around job handling instead.

Trace context does not cross the Redis/BullMQ boundary on its own -- the API
gateway and this worker are separate processes in separate languages. The
Node side injects a W3C traceparent into the job payload itself
(`_traceCarrier`, see services/api/src/queue.ts's addTracedJob); this module
extracts it so the worker's span becomes a child of the span that enqueued
the job, giving one continuous trace across the whole round trip instead of
two disconnected ones.
"""
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")

_provider = TracerProvider(resource=Resource.create({"service.name": "eda-clean-worker"}))
_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{_otlp_endpoint}/v1/traces"))
)
# Same belt-and-suspenders console option as the Node side, for sanity
# checking without a Jaeger UI open.
if os.environ.get("OTEL_DEBUG") == "true":
    _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

trace.set_tracer_provider(_provider)
tracer = trace.get_tracer("eda-clean-worker")

print(
    f"OpenTelemetry tracing initialized (service=eda-clean-worker, "
    f"exporting to {_otlp_endpoint}/v1/traces)"
)


def extract_context(job_data: dict):
    """Pull the W3C traceparent the API injected into job_data (if any) and
    return an OTel context to start the worker's span as a child of it.
    Falls back to a fresh/empty context if the job wasn't traced (e.g. a job
    enqueued by an older API build, or manually via redis-cli) -- the worker
    span still gets created and exported, just as its own root trace."""
    carrier = job_data.get("_traceCarrier") or {}
    return extract(carrier)
