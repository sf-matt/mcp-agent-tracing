#!/usr/bin/env bash
# Quick harness for plain, no-fault /run-task calls -- for narrating
# through the code live, or for firing the same call several times in
# a row to show real-key non-determinism (varying summaries, varying
# plans) once FAKE_LLM is off and a real ANTHROPIC_API_KEY is set.
#
# Assumes the port-forward from the README's Quickstart step 4:
#   kubectl port-forward svc/agent1 19001:9001 -n mcp-agent-tracing &
#
# Usage:
#   ./call.sh          # one call, prints the result, done
#   ./call.sh 5         # 5 calls, pausing between each
set -uo pipefail

AGENT1_URL="${AGENT1_URL:-http://127.0.0.1:19001}"
N="${1:-1}"

pp() { python3 -m json.tool 2>/dev/null || cat; }

for i in $(seq 1 "$N"); do
  if [ "$N" -gt 1 ]; then
    echo "=== call $i/$N ==="
  fi
  date -u +"%Y-%m-%dT%H:%M:%SZ (UTC)"
  curl -s -X POST "$AGENT1_URL/run-task" | pp
  echo
  if [ "$i" -lt "$N" ]; then
    read -rp "-- press enter for next call --" _
  fi
done
