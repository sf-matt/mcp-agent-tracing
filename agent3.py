"""
agent-3 / agent-3-openllmetry -- the summarizer

Scenario:    turns agent2's result into a human-readable summary via a
             real LLM call.
Telemetry:   bare OTel (agent3) vs. OpenLLMetry (agent3-openllmetry) --
             same codebase, ENABLE_OPENLLMETRY is the only difference.
Boundary:    agent-to-LLM, a real Anthropic API call.
Note:        FAKE_LLM=1 swaps the real API for a local loopback server
             with a canned response -- a real socket call, so httpx
             instrumentation still sees a real span (unlike
             httpx.MockTransport, which bypasses it entirely).
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

_fail_llm_calls = False  # llm_error fault flag, read by the fake handler
# below. Held True for the whole /summarize call (reset in finally:),
# not just one hit -- the anthropic SDK retries 5xx automatically
# (max_retries=2), so a one-shot flag gets silently absorbed by the
# retry and never surfaces. Not thread-safe -- fine for one demo
# request at a time, not a general pattern.

if os.environ.get("FAKE_LLM"):
    class _FakeAnthropicHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if _fail_llm_calls:
                body = json.dumps({
                    "type": "error",
                    "error": {"type": "api_error", "message": "deliberate fault for demo (llm_error)"},
                }).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            body = json.dumps({
                "id": "msg_fake_demo",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-4-5-20251001",
                "content": [{"type": "text", "text": "Fake summary: task-x completed with output 42."}],
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
    global _fail_llm_calls
    body = await request.json()
    text = body.get("text", "")
    fault = body.get("fault")
    logging.info("summarize started for text: %s fault=%s", text, fault)

    if fault == "llm_error":
        _fail_llm_calls = True
    try:
        message = await anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": f"In one short sentence, summarize this: {text}"}],
        )
        summary = message.content[0].text
        error = None
    except Exception as e:
        summary = None
        error = f"{type(e).__name__}: {e}"
    finally:
        _fail_llm_calls = False

    logging.info("summarize complete: %s (error=%s)", summary, error)
    return {"agent": SERVICE_NAME, "summary": summary, "error": error}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9003"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
