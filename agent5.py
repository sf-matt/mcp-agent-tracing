"""
the ghost

Scenario:    legacy/third-party service that predates the tracing effort, never instrumented.
Telemetry:   none. No SDK, no spans, no tracing_lib.
Boundary:    agent-to-agent (from agent1) and agent-to-LLM (to Anthropic).
Visibility:  eBPF only.
Note:        uses a deliberately invalid API key, and discards the result either way.
"""

import os
from fastapi import FastAPI, Request
from anthropic import AsyncAnthropic

app = FastAPI()

anthropic_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", "sk-ant-invalid-demo-key-for-ebpf-test"))


@app.post("/ghost-task")
async def ghost_task(request: Request):
    body = await request.json()
    task_id = body.get("task_id", "unknown")
    try:
        await anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{"role": "user", "content": f"Reply with one short word: is task {task_id} done?"}],
        )
    except Exception:
        pass
    return {"agent": "agent-5", "task_id": task_id, "status": "done"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9005"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
