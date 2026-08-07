# MCP Tracing Demo

Three real services, wired with genuine network calls, demonstrating what
OTel tracing does and doesn't give you automatically across an
agent-to-agent and agent-to-tool boundary:

- `agent1` -- the hero agent. Calls the MCP tool server (agent-to-tool)
  and agent2 (agent-to-agent) on `/run-task`.
- `agent2` -- delegation target, plain FastAPI, bare OTel auto-instrumentation.
- `mcp-tool-server` -- real MCP server on streamable-HTTP transport (not
  stdio), one tool (`lookup_price`), bare OTel, zero manual spans.

All three currently use only base OTel auto-instrumentation (FastAPI +
httpx instrumentors) -- no OpenLLMetry yet. That's the next layer to add.

## 1. Test locally first

```bash
docker compose up --build
# in another terminal:
curl -X POST http://localhost:9001/run-task
```

You should get back a real tool result and a real agent2 response.

## 2. Build and push to Docker Hub

```bash
DOCKERHUB_USERNAME=yourname ./build_and_push.sh
```

This builds and pushes all three images: `yourname/agent1:latest`,
`yourname/agent2:latest`, `yourname/mcp-tool-server:latest`.

## 3. Deploy to your cluster

Edit `k8s/manifests.yaml` and replace every `<YOUR_DOCKERHUB_USERNAME>`
with your actual Docker Hub username, then:

```bash
kubectl apply -f k8s/manifests.yaml
kubectl get pods    # wait for all three to be Running
```

## 4. Trigger the flow

```bash
kubectl port-forward svc/agent1 9001:9001
# in another terminal:
curl -X POST http://localhost:9001/run-task
```

## What to check afterward

Each service currently writes its own spans to a local JSON-lines file
inside its container (`spans_agent1.jsonl` etc.) rather than exporting
anywhere -- fine for this stage of the build, but before the real talk
you'll want to point `tracing_lib.py`'s exporter at an OTLP endpoint
(Jaeger, Tempo, or groundcover) instead of a local file, so you can see
the trace in a real UI rather than by `kubectl exec`-ing in to read a
file. Flagging this now since it's a small change but easy to forget
until the night before.

## Known gaps, on purpose, for the talk

- MCP's client transport uses a separate library (`httpx2`, not `httpx`)
  internally, so standard `opentelemetry-instrumentation-httpx` produces
  ZERO generic HTTP spans for the agent-to-tool leg -- confirmed by
  running this. The MCP-specific spans still connect correctly (via the
  SDK's own internal tracing), they just don't carry generic HTTP
  attributes (status code, latency at the transport level, etc.)
- No real LLM call yet in `agent1` -- add one (Anthropic API) to test
  whether bare OTel vs. OpenLLMetry differ on model/token/cost capture.
- No OpenLLMetry yet -- that's the next tier to layer in.
