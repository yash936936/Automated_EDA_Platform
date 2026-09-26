// OpenTelemetry setup for the API gateway. Manual instrumentation (explicit
// tracer.startActiveSpan calls in index.ts/queue.ts), not auto-instrumentation
// -- this codebase runs as pure ESM ("type": "module"), and OTel's Node
// auto-instrumentation relies on a CommonJS require-patching hook that needs
// a separate --experimental-loader wired into how the process is launched.
// Manual spans need none of that: they work identically under ESM or CJS,
// at the cost of writing the span calls ourselves rather than getting
// express/pg instrumented automatically. This file must be imported before
// anything else in the entrypoint (see the first line of index.ts) so the
// provider is registered before any span is created.
import { NodeTracerProvider } from "@opentelemetry/sdk-trace-node";
import { BatchSpanProcessor, ConsoleSpanExporter } from "@opentelemetry/sdk-trace-base";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { ATTR_SERVICE_NAME } from "@opentelemetry/semantic-conventions";
import { AsyncHooksContextManager } from "@opentelemetry/context-async-hooks";
import { W3CTraceContextPropagator } from "@opentelemetry/core";
import { trace } from "@opentelemetry/api";

const otlpEndpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT || "http://127.0.0.1:4318";

const spanProcessors = [
  new BatchSpanProcessor(new OTLPTraceExporter({ url: `${otlpEndpoint}/v1/traces` })),
];
// Belt-and-suspenders: also print spans to stdout when OTEL_DEBUG=true, so
// tracing can be sanity-checked without a Jaeger UI open (e.g. in CI logs).
if (process.env.OTEL_DEBUG === "true") {
  spanProcessors.push(new BatchSpanProcessor(new ConsoleSpanExporter()) as any);
}

const provider = new NodeTracerProvider({
  resource: resourceFromAttributes({ [ATTR_SERVICE_NAME]: "eda-api" }),
  spanProcessors,
});

provider.register({
  contextManager: new AsyncHooksContextManager().enable(),
  propagator: new W3CTraceContextPropagator(),
});

export const tracer = trace.getTracer("eda-api");

console.log(`OpenTelemetry tracing initialized (service=eda-api, exporting to ${otlpEndpoint}/v1/traces)`);
