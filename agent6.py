"""
the sdk agent

Scenario:   five real, unscripted agentic loops via the Claude Agent SDK, chained telephone-game style -- reporter writes an absurd status update, and it passes through supervisor, manager, legal, and support-rep, each reacting only to the previous one's actual words. Content genuinely varies every run, unlike everything else in this demo.
Telemetry:  bare OTel on this process's own FastAPI/httpx layer, same tier as agent1-4. Each LLM call happens inside its own spawned `claude` CLI subprocess, not in this process.
Boundary:   agent-to-subprocess-to-LLM, twice. The Agent SDK doesn't call the `anthropic` package in this process at all -- it pipes a prompt to a child process over stdio, and that subprocess makes the real HTTPS call.
Toggle:     ENABLE_SDK_TELEMETRY=1 turns on the CLI's own native OTel export (beta) pointed at OTEL_EXPORTER_OTLP_ENDPOINT, with shortened export intervals so a short-lived call actually flushes. On by default; unset to see the eBPF-only floor instead.
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
        "OTEL_LOG_USER_PROMPTS": "1",
        "OTEL_LOG_RAW_API_BODIES": "1",
        "OTEL_LOG_TOOL_DETAILS": "1",
        "OTEL_LOG_TOOL_CONTENT": "1",
    })
    return env


ASK_TIMEOUT = 15  # per call -- five real subprocess-backed LLM calls happen
# per request now, so this bounds each one independently rather than the
# whole exchange, same "fail fast and predictably" reasoning as before.

PERSONAS = ["reporter", "supervisor", "manager", "legal", "support-rep"]


def _persona_prompt(name, task_id, prev_text):
    if name == "reporter":
        return (
            f"You are a slightly unhinged AI agent reporting on task '{task_id}'. "
            f"Write ONE short, weird, absurd status update about it -- silly and "
            f"harmless, one sentence, no more than 20 words."
        )
    if name == "supervisor":
        return (
            f"You are a skeptical human supervisor reviewing agent handoff notes. "
            f"Another agent just reported this: \"{prev_text}\". React to it in ONE "
            f"short, deadpan sentence, no more than 20 words."
        )
    if name == "manager":
        return (
            f"You are an overly enthusiastic project manager. Your supervisor just "
            f"said this: \"{prev_text}\". Spin it into a win in ONE short sentence, "
            f"no more than 20 words."
        )
    if name == "legal":
        return (
            f"You are a nervous legal/compliance officer. A manager just said this: "
            f"\"{prev_text}\". React with concern about liability in ONE short "
            f"sentence, no more than 20 words."
        )
    if name == "support-rep":
        return (
            f"You are a customer support rep who has to explain this to a confused "
            f"customer. Legal just said this internally: \"{prev_text}\". Summarize "
            f"it for the customer in ONE short, reassuring sentence, no more than "
            f"20 words."
        )
    raise ValueError(name)


async def _ask(prompt):
    text_parts = []
    meta = {}

    async def _run():
        options = ClaudeAgentOptions(allowed_tools=[], env=_sdk_env())
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if hasattr(block, "text"):
                        text_parts.append(block.text)
            elif isinstance(message, ResultMessage):
                meta["is_error"] = message.is_error
                meta["api_error_status"] = message.api_error_status

    try:
        await asyncio.wait_for(_run(), timeout=ASK_TIMEOUT)
    except asyncio.TimeoutError:
        if not text_parts:
            text_parts = [f"TimeoutError: no response within {ASK_TIMEOUT}s (likely an auth retry loop)"]
    except Exception as e:
        if not text_parts:
            text_parts = [f"{type(e).__name__}: {e}"]

    return " ".join(text_parts) if text_parts else None, meta


@app.post("/subprocess-task")
async def subprocess_task(request: Request):
    body = await request.json()
    task_id = body.get("task_id", "unknown")
    logging.info("subprocess_task started for task_id=%s", task_id)

    # Five real, unscripted agent calls, chained telephone-game style --
    # each persona reacts only to the previous one's actual words.
    # Content genuinely varies every run -- this is the "show it live
    # and let it be random" case, deliberately, unlike everything else
    # in this demo that's built for reproducibility. Stops early if any
    # step fails to produce text -- nothing to react to otherwise.
    chain = []
    prev_text = None
    for name in PERSONAS:
        prompt = _persona_prompt(name, task_id, prev_text)
        text, meta = await _ask(prompt)
        chain.append({"agent": name, "text": text, **meta})
        if not text:
            break
        prev_text = text

    logging.info("subprocess_task complete: %s", [c["text"] for c in chain])
    return {
        "agent": "agent-6",
        "task_id": task_id,
        "chain": chain,
        "telemetry_enabled": bool(os.environ.get("ENABLE_SDK_TELEMETRY")),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9006"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
