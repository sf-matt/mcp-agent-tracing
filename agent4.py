"""
agent-4: the auditor. On /audit it records an audit span for the
incoming request -- no LLM call, no tool call, independent of the other
three agents in the fan-out (safe to run concurrently with them).

This is the third instrumentation tier for the talk: bare auto-instrument
gets you nothing beyond generic HTTP shape; OpenLLMetry gets you a
comprehensive vendor-standard attribute set for free; this file shows the
middle ground -- a few lines of tracer.start_as_current_span() with
hand-picked attributes, no SDK, exactly what you decided mattered and
nothing else. Uses the same tracing_lib.setup_tracing() as every other
service; the "custom" part is entirely in what happens below, not in any
special setup.
"""

import logging
import os
import uuid

from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from tracing_lib import setup_tracing

SERVICE_NAME = os.environ.get("SERVICE_NAME", "agent-4")
tracer = setup_tracing(SERVICE_NAME, os.environ.get("SPAN_FILE", "spans_agent4.jsonl"))

app = FastAPI()
FastAPIInstrumentor.instrument_app(app)


@app.post("/audit")
async def audit(request: Request):
    body = await request.json()
    task_id = body.get("task_id", "unknown")

    with tracer.start_as_current_span("audit.record_decision") as span:
        audit_id = str(uuid.uuid4())
        span.set_attribute("audit.id", audit_id)
        span.set_attribute("audit.task_id", task_id)
        span.set_attribute("audit.decision", "approved")
        span.set_attribute("audit.reviewer", "agent-4-automated")
        logging.info("audit recorded: %s for task_id=%s", audit_id, task_id)

    return {"agent": SERVICE_NAME, "audit_id": audit_id, "decision": "approved"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9004"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
