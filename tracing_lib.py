"""
Shared tracing setup for agent1, agent2, and the MCP tool server.

Default export target is OTLP (OTEL_EXPORTER_OTLP_ENDPOINT), pointed at
the in-cluster/in-compose otel-collector, which forwards to groundcover.
If that env var isn't set, falls back to writing spans to a JSON-lines
file per process -- useful for local debugging without a collector
running, and for comparing trace_ids across processes by hand.
"""

import json
import os
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult


class JsonFileExporter(SpanExporter):
    def __init__(self, path):
        self.path = path

    def export(self, spans):
        with open(self.path, "a") as f:
            for span in spans:
                ctx = span.get_span_context()
                parent = span.parent
                f.write(json.dumps({
                    "name": span.name,
                    "trace_id": format(ctx.trace_id, "032x"),
                    "span_id": format(ctx.span_id, "016x"),
                    "parent_span_id": format(parent.span_id, "016x") if parent else None,
                    "service": span.resource.attributes.get("service.name"),
                    "attributes": dict(span.attributes) if span.attributes else {},
                }) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass


def setup_tracing(service_name: str, output_path: str):
    """Call once per process. Returns a tracer."""
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))

    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")))
    else:
        provider.add_span_processor(SimpleSpanProcessor(JsonFileExporter(output_path)))

    if otlp_endpoint and os.environ.get("SPAN_FILE_DEBUG"):
        provider.add_span_processor(SimpleSpanProcessor(JsonFileExporter(output_path)))

    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(service_name)
    return tracer
