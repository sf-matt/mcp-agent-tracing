"""
Shared tracing setup for every service in this demo.

Default export target is OTLP (OTEL_EXPORTER_OTLP_ENDPOINT), pointed at
the otel-collector. If unset, falls back to writing spans to a
JSON-lines file per process -- useful for local debugging without a
collector, and for comparing trace_ids across processes by hand.

ENABLE_OPENLLMETRY layers OpenLLMetry (traceloop-sdk) onto the SAME
TracerProvider set up below: Traceloop.init() attaches its own span
processor to the existing provider instead of creating a new one, and
passing our own OTLPSpanExporter into it stops it from defaulting to
Traceloop's SaaS endpoint.

Logs (when OTLP is set) go through the OTel SDK's LoggingHandler,
bridging stdlib logging to an OTLP log exporter -- log lines auto-
correlate with the active span's trace_id, no extra wiring needed.
"""

import json
import logging
import os
from opentelemetry import _logs, trace
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
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

    if os.environ.get("ENABLE_OPENLLMETRY") and otlp_endpoint:
        from traceloop.sdk import Traceloop
        Traceloop.init(
            app_name=service_name,
            exporter=OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces"),
            telemetry_enabled=False,
        )

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        logger_provider = LoggerProvider(resource=Resource.create({"service.name": service_name}))
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{otlp_endpoint}/v1/logs"))
        )
        _logs.set_logger_provider(logger_provider)
        logging.getLogger().addHandler(LoggingHandler(logger_provider=logger_provider))
        logging.getLogger().setLevel(logging.INFO)

    return tracer
