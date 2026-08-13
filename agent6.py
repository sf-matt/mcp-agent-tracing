"""
agent-6 -- the subprocess

Scenario:    a real agentic loop via the Claude Agent SDK -- the same
             harness Claude Code runs on. Standalone: not wired into
             agent1's fan-out plan.
Telemetry:   bare OTel on this process's own FastAPI/httpx layer, same
             tier as agent1-4. The LLM call itself happens inside a
             spawned `claude` CLI subprocess, not in this process.
Boundary:    agent-to-subprocess-to-LLM. The Agent SDK doesn't call the
             `anthropic` package in this process at all -- it pipes a
             prompt to a child process over stdio, and that subprocess
             makes the real HTTPS call. Bare OTel and OpenLLMetry are
             both structurally blind to this: there's no in-process
             httpx call, and no anthropic-package method, for either to
             see. eBPF doesn't care -- same socket, same pod, regardless
             of which process opened it.
Toggle:      ENABLE_SDK_TELEMETRY=1 turns on the CLI's own native OTel
             export (beta) pointed at OTEL_EXPORTER_OTLP_ENDPOINT, with
             shortened export intervals so a short-lived call actually
             flushes. Off by default -- matches what most real
             deployments run, and is the case bare OTel/OpenLLMetry
             can't see into at all.
"""

import asyncio
import logging
import os

from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, query

from tracing_lib import setup_tracing

setup_tracing("agent-6", os.environ.get("SPAN_FILE", "spans_agent6.jsonl"))

app = FastAPI()
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()


def _sdk_env():
    env = {}
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        # No credential at all makes the CLI fail client-side ("Not
        # logged in") before ever reaching the wire -- confirmed by
        # testing. An invalid-but-present key still makes a real
        # network call, same reliability pattern as agent5. Only
        # inject this fallback if neither a real API key NOR a real
        # CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`) is set --
        # otherwise this would clobber a real credential.
        env["ANTHROPIC_API_KEY"] = "sk-ant-invalid-demo-key-for-ebpf-test"
    if not os.environ.get("ENABLE_SDK_TELEMETRY"):
        return env
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    env.update({
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
        "OTEL_TRACES_EXPORTER": "otlp",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        "OTEL_TRACES_EXPORT_INTERVAL": "1000",
        "OTEL_LOGS_EXPORT_INTERVAL": "1000",
    })
    return env


@app.post("/subprocess-task")
async def subprocess_task(request: Request):
    body = await request.json()
    task_id = body.get("task_id", "unknown")
    logging.info("subprocess_task started for task_id=%s", task_id)

    text_parts = []
    result_meta = {}

    async def _run():
        options = ClaudeAgentOptions(allowed_tools=[], env=_sdk_env())
        async for message in query(
            prompt=f"Task {task_id}. Reply with one short word: are you operational?",
            options=options,
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if hasattr(block, "text"):
                        text_parts.append(block.text)
            elif isinstance(message, ResultMessage):
                # subtype=="success" means the CLI process completed
                # normally -- NOT that the task succeeded. is_error and
                # api_error_status carry the real outcome; confirmed by
                # testing with a deliberately invalid key, which still
                # returns subtype="success" alongside is_error=True.
                result_meta["is_error"] = message.is_error
                result_meta["api_error_status"] = message.api_error_status

    try:
        # The CLI retries auth failures up to 10x with exponential
        # backoff (585ms doubling past 30s by attempt 7) -- confirmed
        # by testing. A hard timeout here means a bad credential fails
        # fast and predictably instead of hanging for minutes on stage.
        await asyncio.wait_for(_run(), timeout=20)
    except asyncio.TimeoutError:
        if not text_parts:
            text_parts = ["TimeoutError: no response within 20s (likely an auth retry loop)"]
    except Exception as e:
        # query() raises a trailing exception even after a well-formed
        # result stream, on a low-level "error: success" quirk in the
        # raw wire protocol -- confirmed by testing. Only fall back to
        # the exception string if we never got real assistant text.
        if not text_parts:
            text_parts = [f"{type(e).__name__}: {e}"]

    result = " ".join(text_parts) if text_parts else None
    logging.info("subprocess_task complete: result=%s meta=%s", result, result_meta)
    return {
        "agent": "agent-6",
        "task_id": task_id,
        "result": result,
        **result_meta,
        "telemetry_enabled": bool(os.environ.get("ENABLE_SDK_TELEMETRY")),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9006"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
