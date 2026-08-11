"""
mcp-tool-server -- the tool

Scenario:    the system agent2 calls -- a database/API stand-in, via
             the execute_task tool.
Telemetry:   bare OTel only -- no manual spans, no OpenLLMetry.
Boundary:    agent-to-tool, real MCP over streamable-HTTP transport
             (not stdio), for more realism.
"""

import logging
import os
from mcp.server.mcpserver import MCPServer

from tracing_lib import setup_tracing

setup_tracing("mcp-tool-server", os.environ.get("SERVER_SPAN_FILE", "spans_tool_server.jsonl"))

mcp = MCPServer("generic-tool-server")


@mcp.tool()
def execute_task(task_id: str, fail: bool = False) -> dict:
    """Execute a task by ID. Pure business logic, no manual tracing.

    fail=True is the tool_error fault hook -- raises to show what an
    MCP tool-execution error looks like on the wire (this leg carries
    no generic http.* attributes at all -- it's MCP, not HTTP).
    """
    logging.info("execute_task called for task_id=%s fail=%s", task_id, fail)
    if fail:
        raise ValueError(f"deliberate failure for task_id={task_id}")
    return {"task_id": task_id, "status": "completed", "output": 42}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9000"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
