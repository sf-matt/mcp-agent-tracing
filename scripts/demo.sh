#!/usr/bin/env bash
# Demo harness for the talk: walks through the fault battery plus the
# plan-override reveal against a running agent1, one step at a time.
#
# Assumes the port-forward from the README's Quickstart step 4 is
# already running:
#   kubectl port-forward svc/agent1 19001:9001 -n mcp-agent-tracing &
#
# Usage:
#   ./demo.sh
#   AGENT1_URL=http://127.0.0.1:9001 ./demo.sh   # against docker-compose instead
set -uo pipefail

AGENT1_URL="${AGENT1_URL:-http://127.0.0.1:19001}"

pp() { python3 -m json.tool 2>/dev/null || cat; }

step() {
  local title="$1" body="$2" hint="$3"
  echo
  echo "=== $title ==="
  date -u +"%Y-%m-%dT%H:%M:%SZ (UTC) -- note this for groundcover"
  if [ -z "$body" ]; then
    curl -s -X POST "$AGENT1_URL/run-task" | pp
  else
    curl -s -X POST "$AGENT1_URL/run-task" -H 'Content-Type: application/json' -d "$body" | pp
  fi
  echo
  echo ">>> $hint"
}

pause() { read -rp "-- press enter for next --" _; }

step "1. Happy path" "" \
  "One trace, five agents, all healthy -- agent5 never joins it."

pause

step "2. fault: tool_error" '{"fault":"tool_error"}' \
  "Only mcp-tool-server's span goes red. agent2 catches it and reports tool_error:true -- everything above stays Unset/200."

pause

step "3. fault: llm_error" '{"fault":"llm_error"}' \
  "Bare OTel (agent3): 3 generic POST spans, no message. OpenLLMetry (agent3-openllmetry): full exception plus the exact input that failed."

pause

step "4. fault: agent_error" '{"fault":"agent_error"}' \
  "agent4's span AND agent1's client span to it both go red -- but the HTTP response is still 200. The gap: agent1 never checks the status."

pause

step "5. plan override -- skip audit" '{"plan":["process","ghost"]}' \
  "Compare this trace to step 1: zero agent-4 spans anywhere. The plan decided this before the fan-out even started."

echo
echo "=== Manual steps below -- real infra changes, not automated ==="
echo
echo "Real network failure (loud everywhere, unlike the faults above):"
echo "  kubectl scale deployment agent5 --replicas=0 -n mcp-agent-tracing"
echo "  curl -X POST $AGENT1_URL/run-task     # now returns 500"
echo "  kubectl scale deployment agent5 --replicas=1 -n mcp-agent-tracing   # restore before continuing"
echo
echo "agent6 (ENABLE_SDK_TELEMETRY is on by default -- CLI spans already join the trace):"
echo "  kubectl port-forward svc/agent6 19006:9006 -n mcp-agent-tracing &"
echo "  curl -X POST http://127.0.0.1:19006/subprocess-task -d '{\"task_id\":\"reveal\"}'"
echo "  # to see the eBPF-only floor instead, unset ENABLE_SDK_TELEMETRY in k8s/manifests.yaml and redeploy"
