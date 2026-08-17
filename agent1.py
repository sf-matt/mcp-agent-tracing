"""
the boss

Scenario:   workflow entrypoint. Asks an LLM for a plan, then fans that plan out to the other four agents, aggregates results.
Telemetry:  bare OTel auto-instrumentation only (FastAPI + httpx).
Boundary:   agent-to-LLM (the planning call) and agent-to-agent (the fan-out that plan produces).
Plan:       POST /run-task {"plan": ["process","audit","ghost"]} scripts the LLM's response directly -- same real-call/ scripted-body pattern as agent3's FAKE_LLM, just applied to a planning decision instead of a summary. Omit it and the LLM (real, or FAKE_LLM's canned default) decides; a missing/invalid response falls back to the full plan.
Faults:     POST /run-task {"fault": "tool_error"|"llm_error"|"agent_error"} breaks one leg live -- see README's "Fault tests".
"""

import asyncio
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
import httpx

from anthropic import AsyncAnthropic

from tracing_lib import setup_tracing

setup_tracing("agent1", os.environ.get("SPAN_FILE", "spans_agent1.jsonl"))

app = FastAPI()
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()  # patches httpx.AsyncClient / httpx.Client

AGENT2_URL = os.environ.get("AGENT2_URL", "http://127.0.0.1:9002/process")
AGENT3_URL = os.environ.get("AGENT3_URL", "http://127.0.0.1:9003/summarize")
AGENT3_OPENLLMETRY_URL = os.environ.get("AGENT3_OPENLLMETRY_URL", "http://127.0.0.1:9013/summarize")
AGENT4_URL = os.environ.get("AGENT4_URL", "http://127.0.0.1:9004/audit")
AGENT5_URL = os.environ.get("AGENT5_URL", "http://127.0.0.1:9005/ghost-task")

TASK_ID = "task-x"
DEFAULT_PLAN = ["process", "audit", "ghost"]

_scripted_plan = DEFAULT_PLAN 

if os.environ.get("FAKE_LLM"):
    class _FakePlannerHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.dumps({
                "id": "msg_fake_plan",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-4-5-20251001",
                "content": [{"type": "text", "text": json.dumps({"steps": _scripted_plan})}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 30, "output_tokens": 10},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    _fake_planner_server = ThreadingHTTPServer(("127.0.0.1", 9092), _FakePlannerHandler)
    threading.Thread(target=_fake_planner_server.serve_forever, daemon=True).start()
    anthropic_client = AsyncAnthropic(api_key="fake-key-for-demo", base_url="http://127.0.0.1:9092")
else:
    anthropic_client = AsyncAnthropic()


async def _plan_steps(task_id, override):
    global _scripted_plan
    _scripted_plan = override if override else DEFAULT_PLAN
    try:
        message = await anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": (
                    f'Task {task_id}. Choose which steps to run from '
                    f'["process", "audit", "ghost"]. Reply with JSON '
                    f'only: {{"steps": [...]}}.'
                ),
            }],
        )
        steps = json.loads(message.content[0].text)["steps"]
        planned = [s for s in steps if s in DEFAULT_PLAN]
        return planned or DEFAULT_PLAN
    except Exception:
        return DEFAULT_PLAN


async def _post(client, url, json_body):
    resp = await client.post(url, json=json_body)
    return resp.json()


@app.post("/run-task")
async def run_task(request: Request):
    raw = await request.body()
    body = await request.json() if raw else {}
    fault = body.get("fault")
    logging.info("run_task started, fault=%s plan_override=%s", fault, body.get("plan"))

    plan = await _plan_steps(TASK_ID, body.get("plan"))
    logging.info("plan decided: %s", plan)

    async with httpx.AsyncClient() as client:
        agent2_result = agent4_result = agent5_result = None
        phase1 = []
        if "process" in plan:
            phase1.append(("agent2", _post(client, AGENT2_URL, {"query": f"process {TASK_ID}", "task_id": TASK_ID, "fault": fault})))
        if "audit" in plan:
            phase1.append(("agent4", _post(client, AGENT4_URL, {"task_id": TASK_ID, "fault": fault})))
        if "ghost" in plan:
            phase1.append(("agent5", _post(client, AGENT5_URL, {"task_id": TASK_ID})))

        if phase1:
            names, coros = zip(*phase1)
            phase1_results = dict(zip(names, await asyncio.gather(*coros)))
            agent2_result = phase1_results.get("agent2")
            agent4_result = phase1_results.get("agent4")
            agent5_result = phase1_results.get("agent5")
        logging.info("phase 1 complete: agent2=%s agent4=%s agent5=%s", agent2_result, agent4_result, agent5_result)

        agent3_result = agent3_oll_result = None
        if agent2_result is not None:
            summarize_text = f"tool result for {TASK_ID}: {agent2_result.get('tool_result')}"
            agent3_result, agent3_oll_result = await asyncio.gather(
                _post(client, AGENT3_URL, {"text": summarize_text, "fault": fault}),
                _post(client, AGENT3_OPENLLMETRY_URL, {"text": summarize_text, "fault": fault}),
            )
            logging.info("phase 2 complete: agent3=%s agent3-openllmetry=%s", agent3_result, agent3_oll_result)

    results = {
        "plan": plan,
        "agent2_call": agent2_result,
        "agent3_call": agent3_result,
        "agent3_openllmetry_call": agent3_oll_result,
        "agent4_call": agent4_result,
        "agent5_call": agent5_result,
    }
    logging.info("run_task complete")
    return results


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9001"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
