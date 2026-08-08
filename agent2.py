"""
agent-2: the tool-caller. agent-1 calls this over real HTTP as its
agent-to-agent leg; agent-2 in turn makes the real agent-to-tool call
(MCP over streamable HTTP) to mcp-tool-server. Purpose shift from the
original design: this used to be a trivial delegate that just echoed a
canned answer; now it actually owns tool access, which is also why it
moved into the platform namespace alongside mcp-tool-server rather than
staying with the other agents.

Bare OTel auto-instrumentation only (FastAPI + httpx instrumentors) --
no manual spans, no OpenLLMetry.
"""

import logging
import os
from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tracing_lib import setup_tracing

setup_tracing("agent-2", os.environ.get("SPAN_FILE", "spans_agent2.jsonl"))

app = FastAPI()
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()

TOOL_SERVER_URL = os.environ.get("TOOL_SERVER_URL", "http://127.0.0.1:9000/mcp")


@app.post("/process")
async def process(request: Request):
    body = await request.json()
    query = body.get("query", "")
    task_id = body.get("task_id", "task-x")
    logging.info("process received query: %s", query)

    async with streamable_http_client(TOOL_SERVER_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_result = await session.call_tool("execute_task", arguments={"task_id": task_id})
            result_text = str(tool_result.content)

    logging.info("process complete: %s", result_text)
    return {"agent": "agent-2", "query": query, "tool_result": result_text}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9002"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
