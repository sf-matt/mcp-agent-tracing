"""
agent-4 -- the auditor

Scenario:    compliance/audit-log step, independent of whether the
             "real" work succeeded.
Telemetry:   hand-rolled custom spans -- no vendor SDK, no
             auto-instrumentation beyond bare FastAPI for the inbound
             request.
Boundary:    none -- no outbound call.
Note:        third instrumentation tier -- bare gets generic HTTP
             shape, OpenLLMetry gets a full attribute set for free,
             this shows the hand-rolled middle ground.
"""

import logging
import os
import uuid

from fastapi import FastAPI, HTTPException, Request
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
    fault = body.get("fault")

    # agent_error fault: unhandled 500 on purpose. agent1's _post() calls
    # resp.json() with no status check, so this doesn't fail agent1's own
    # request -- it's silently absorbed into agent4_call and /run-task
    # still returns 200. The finding: a real error invisible unless you
    # look at the content, not the status code.
    if fault == "agent_error":
        raise HTTPException(status_code=500, detail="deliberate agent4 failure for fault test")

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
