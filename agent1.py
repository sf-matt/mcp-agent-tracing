"""
agent-1: the hero agent. On /run-task it does two real network hops:
  1. agent-to-tool: calls the MCP tool server over streamable HTTP
  2. agent-to-agent: calls agent-2 over plain HTTP (httpx)

STEP 1 of the build: bare OTel auto-instrumentation only.
- FastAPIInstrumentor: instruments the inbound /run-task request
- HTTPXClientInstrumentor: instruments OUR OWN outbound httpx calls
  (the agent-to-agent leg)

Deliberately NO manual spans anywhere in this file. We want to see
exactly what "turn on auto-instrumentation and do nothing else" gets you
across a real agent-to-agent and agent-to-tool flow.
"""

import os
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
import httpx

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tracing_lib import setup_tracing

setup_tracing("agent-1", os.environ.get("SPAN_FILE", "spans_agent1.jsonl"))

app = FastAPI()
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()  # patches httpx.AsyncClient / httpx.Client

TOOL_SERVER_URL = os.environ.get("TOOL_SERVER_URL", "http://127.0.0.1:9000/mcp")
AGENT2_URL = os.environ.get("AGENT2_URL", "http://127.0.0.1:9002/lookup")


@app.post("/run-task")
async def run_task():
    results = {}

    # --- agent-to-tool: real MCP call over streamable HTTP ---
    async with streamable_http_client(TOOL_SERVER_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_result = await session.call_tool("lookup_price", arguments={"sku": "SKU-4471"})
            results["tool_call"] = str(tool_result.content)

    # --- agent-to-agent: plain HTTP call to agent-2 ---
    async with httpx.AsyncClient() as client:
        resp = await client.post(AGENT2_URL, json={"query": "SKU-4471 in stock?"})
        results["agent2_call"] = resp.json()

    return results


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9001"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
