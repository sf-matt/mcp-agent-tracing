"""
agent-5: the ghost. Deliberately ZERO OpenTelemetry -- no tracing_lib
import, no instrumentation, no manual spans, nothing. Not even a
logging call.

This is the floor of the instrumentation spectrum the other four agents
sit above: bare auto-instrument (agent3), OpenLLMetry (agent3-openllmetry),
hand-rolled custom spans (agent4). agent5 asks what's left when an
agent does none of that at all -- the answer is whatever the platform's
own eBPF sensor sees on the wire, independent of anything the app does.
agent1's outbound call to this one still gets an httpx client span (that
instrumentation lives on the CALLER), but nothing comes back the other
way: no server-side span, no trace_id propagation, no participation in
the trace at all. From the trace's point of view this hop goes nowhere.
"""

import os
from fastapi import FastAPI, Request

app = FastAPI()


@app.post("/ghost-task")
async def ghost_task(request: Request):
    body = await request.json()
    task_id = body.get("task_id", "unknown")
    return {"agent": "agent-5", "task_id": task_id, "status": "done"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9005"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
