"""
agent-3: the summarizer. On /summarize it makes one real network hop:
  agent-to-LLM: a real Anthropic API call summarizing whatever text it's given.

Bare OTel auto-instrumentation only in this file (FastAPIInstrumentor +
HTTPXClientInstrumentor). Whether the LLM call shows up as anything more
than a generic HTTP span depends entirely on ENABLE_OPENLLMETRY -- see
tracing_lib.py. This same file runs as both the "agent3" (bare OTel) and
"agent3-openllmetry" deployments; only that one env var differs.

FAKE_LLM=1 swaps the real Anthropic API for a local loopback HTTP server
returning a canned response -- a demo-reliability fallback for flaky
wifi/rate limits, not a code-level mock. It's a REAL local HTTP call
(genuine socket, genuine request/response), so httpx auto-instrumentation
still sees a real "POST" span exactly like it would against the real API.
A code-level mock (e.g. httpx.MockTransport) would NOT do this -- it
bypasses HTTPXClientInstrumentor entirely, since that instrumentor patches
httpx's default transport, not custom ones, silently erasing the span
bare OTel would otherwise produce. Confirmed by testing both.
"""

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from anthropic import AsyncAnthropic

from tracing_lib import setup_tracing

SERVICE_NAME = os.environ.get("SERVICE_NAME", "agent-3")
setup_tracing(SERVICE_NAME, os.environ.get("SPAN_FILE", "spans_agent3.jsonl"))

app = FastAPI()
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()  # patches httpx.AsyncClient / httpx.Client

if os.environ.get("FAKE_LLM"):
    class _FakeAnthropicHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.dumps({
                "id": "msg_fake_demo",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-4-5-20251001",
                "content": [{"type": "text", "text": "Fake summary: SKU-4471 is in stock at $42.00."}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 42, "output_tokens": 12},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    _fake_llm_server = ThreadingHTTPServer(("127.0.0.1", 9091), _FakeAnthropicHandler)
    threading.Thread(target=_fake_llm_server.serve_forever, daemon=True).start()
    anthropic_client = AsyncAnthropic(api_key="fake-key-for-demo", base_url="http://127.0.0.1:9091")
else:
    anthropic_client = AsyncAnthropic()


@app.post("/summarize")
async def summarize(request: Request):
    body = await request.json()
    text = body.get("text", "")
    logging.info("summarize started for text: %s", text)

    message = await anthropic_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{"role": "user", "content": f"In one short sentence, summarize this: {text}"}],
    )
    summary = message.content[0].text
    logging.info("summarize complete: %s", summary)

    return {"agent": SERVICE_NAME, "summary": summary}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9003"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
