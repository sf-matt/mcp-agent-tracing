"""
agent-2: a small delegate agent. agent-1 calls this over real HTTP as its
agent-to-agent leg. Step 1: bare OTel auto-instrumentation only (FastAPI +
httpx instrumentors) -- no manual spans, no OpenLLMetry. We want to see
exactly what "just turn on auto-instrumentation" gets us for free.
"""

import logging
import os
from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from tracing_lib import setup_tracing

setup_tracing("agent-2", os.environ.get("SPAN_FILE", "spans_agent2.jsonl"))

app = FastAPI()
FastAPIInstrumentor.instrument_app(app)


@app.post("/lookup")
async def lookup(request: Request):
    body = await request.json()
    query = body.get("query", "")
    logging.info("lookup received query: %s", query)
    # trivial delegate logic -- the point is the hop existing, not this
    return {"agent": "agent-2", "query": query, "answer": "in_stock"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9002"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
