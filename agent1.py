"""
agent-1: the orchestrator. On /run-task it fans out to five downstream
agents and aggregates their results -- no LLM call, no tool call, no
custom spans of its own. Bare OTel auto-instrumentation only
(FastAPIInstrumentor + HTTPXClientInstrumentor).

Fan-out happens in two concurrent phases, not five fully-independent
calls, because agent3/agent3-openllmetry summarize agent2's actual tool
result -- they need it to exist first:
  phase 1 (concurrent): agent2 (tool lookup) + agent4 (audit) + agent5
    (ghost -- none of these three depend on each other's results)
  phase 2 (concurrent): agent3 + agent3-openllmetry, both summarizing
    the SAME text (agent2's real result) so their spans are directly
    comparable

One /run-task call still produces ONE trace with agent2/agent3/
agent3-openllmetry/agent4 as spans under agent1's root span -- confirmed
empirically, see README. agent5 is the deliberate exception: this call
still happens (agent1's outbound httpx span to it is real), but agent5
itself runs zero OTel, so nothing comes back the other way -- no
server-side span, no join to the trace. The bare-OTel vs. OpenLLMetry
comparison lives in agent3 vs. agent3-openllmetry (see tracing_lib.py's
ENABLE_OPENLLMETRY); agent4 carries the third instrumentation tier
(hand-rolled custom spans, no SDK, see agent4.py); agent5 carries the
fourth: nothing at all, see agent5.py.
"""

import asyncio
import logging
import os

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
import httpx

from tracing_lib import setup_tracing

setup_tracing("agent-1", os.environ.get("SPAN_FILE", "spans_agent1.jsonl"))

app = FastAPI()
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()  # patches httpx.AsyncClient / httpx.Client

AGENT2_URL = os.environ.get("AGENT2_URL", "http://127.0.0.1:9002/process")
AGENT3_URL = os.environ.get("AGENT3_URL", "http://127.0.0.1:9003/summarize")
AGENT3_OPENLLMETRY_URL = os.environ.get("AGENT3_OPENLLMETRY_URL", "http://127.0.0.1:9013/summarize")
AGENT4_URL = os.environ.get("AGENT4_URL", "http://127.0.0.1:9004/audit")
AGENT5_URL = os.environ.get("AGENT5_URL", "http://127.0.0.1:9005/ghost-task")

TASK_ID = "task-x"


async def _post(client, url, json_body):
    resp = await client.post(url, json=json_body)
    return resp.json()


@app.post("/run-task")
async def run_task():
    logging.info("run_task started")
    async with httpx.AsyncClient() as client:
        # phase 1: agent2 (needs to run first -- its result feeds phase 2),
        # agent4 (audit, independent), and agent5 (ghost, independent --
        # and instrumented with nothing, so this call never joins the
        # trace from agent5's side) concurrently.
        agent2_result, agent4_result, agent5_result = await asyncio.gather(
            _post(client, AGENT2_URL, {"query": f"process {TASK_ID}", "task_id": TASK_ID}),
            _post(client, AGENT4_URL, {"task_id": TASK_ID}),
            _post(client, AGENT5_URL, {"task_id": TASK_ID}),
        )
        logging.info("phase 1 complete: agent2=%s agent4=%s agent5=%s", agent2_result, agent4_result, agent5_result)

        # phase 2: both summarizer variants, concurrently, over the SAME
        # real tool result -- directly comparable spans on one trace.
        summarize_text = f"tool result for {TASK_ID}: {agent2_result.get('tool_result')}"
        agent3_result, agent3_oll_result = await asyncio.gather(
            _post(client, AGENT3_URL, {"text": summarize_text}),
            _post(client, AGENT3_OPENLLMETRY_URL, {"text": summarize_text}),
        )
        logging.info("phase 2 complete: agent3=%s agent3-openllmetry=%s", agent3_result, agent3_oll_result)

    results = {
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
