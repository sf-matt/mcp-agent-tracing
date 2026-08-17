"""
the tool-caller

Scenario:    calls a real system on agent1's behalf -- a database/API
             lookup, standing in for execute_task.
Telemetry:   bare OTel auto-instrumentation only.
Boundary:    agent-to-agent (from agent1, cross-namespace) and
             agent-to-tool (to mcp-tool-server, via MCP).
Namespace:   mcp-agent-tracing-platform, with mcp-tool-server.
"""

import logging
import os
from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tracing_lib import setup_tracing

setup_tracing("agent2", os.environ.get("SPAN_FILE", "spans_agent2.jsonl"))

app = FastAPI()
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()

TOOL_SERVER_URL = os.environ.get("TOOL_SERVER_URL", "http://127.0.0.1:9000/mcp")


@app.post("/process")
async def process(request: Request):
    body = await request.json()
    query = body.get("query", "")
    task_id = body.get("task_id", "task-x")
    fault = body.get("fault")
    logging.info("process received query: %s fault=%s", query, fault)

    tool_error = False
    async with streamable_http_client(TOOL_SERVER_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                tool_result = await session.call_tool(
                    "execute_task", arguments={"task_id": task_id, "fail": fault == "tool_error"}
                )
                result_text = str(tool_result.content)
                # is_error=True means the tool ran and returned an error
                # (not a raised exception) -- this SDK uses snake_case,
                # unlike the wire protocol's camelCase isError.
                tool_error = bool(getattr(tool_result, "is_error", False))
            except Exception as e:
                result_text = f"tool call raised: {e}"
                tool_error = True

    logging.info("process complete: %s (tool_error=%s)", result_text, tool_error)
    return {"agent": "agent2", "query": query, "tool_result": result_text, "tool_error": tool_error}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9002"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
