"""
MCP tool server, running on real HTTP transport (not stdio out for more realism).

Bare OTel only for step 1: no manual spans, no OpenLLMetry. Whatever
telemetry we get here comes entirely from auto-instrumenting the HTTP
layer -- FastAPI/Starlette server-side, and MCP's own internal handling.
"""

import logging
import os
from mcp.server.mcpserver import MCPServer

from tracing_lib import setup_tracing

setup_tracing("mcp-tool-server", os.environ.get("SERVER_SPAN_FILE", "spans_tool_server.jsonl"))

mcp = MCPServer("pricing-tool-server")


@mcp.tool()
def lookup_price(sku: str) -> dict:
    """Look up the price for a given SKU. Pure business logic, no manual tracing code."""
    logging.info("lookup_price called for sku=%s", sku)
    return {"sku": sku, "price_usd": 42.00}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9000"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
