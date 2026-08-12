#!/usr/bin/env bash
# Call ONE agent directly, bypassing agent1's fan-out entirely -- an
# isolated trace with just that agent's own hop. Manages its own
# port-forward (starts it, calls, tears it down), so spotlighting one
# tier during the code walkthrough is a single command.
#
# Usage:
#   ./single.sh agent2
#   ./single.sh agent3-openllmetry
#   ./single.sh agent5 my-task-id
set -uo pipefail

NAME="${1:-}"
TASK_ID="${2:-task-x}"

pp() { python3 -m json.tool 2>/dev/null || cat; }

case "$NAME" in
  agent2)
    NS=mcp-agent-tracing-platform; SVC=agent2; PORT=9002; ROUTE=/process
    BODY="{\"query\":\"process $TASK_ID\",\"task_id\":\"$TASK_ID\"}"
    ;;
  agent3)
    NS=mcp-agent-tracing; SVC=agent3; PORT=9003; ROUTE=/summarize
    BODY="{\"text\":\"tool result for $TASK_ID: completed with output 42\"}"
    ;;
  agent3-openllmetry)
    NS=mcp-agent-tracing; SVC=agent3-openllmetry; PORT=9003; ROUTE=/summarize
    BODY="{\"text\":\"tool result for $TASK_ID: completed with output 42\"}"
    ;;
  agent4)
    NS=mcp-agent-tracing; SVC=agent4; PORT=9004; ROUTE=/audit
    BODY="{\"task_id\":\"$TASK_ID\"}"
    ;;
  agent5)
    NS=mcp-agent-tracing; SVC=agent5; PORT=9005; ROUTE=/ghost-task
    BODY="{\"task_id\":\"$TASK_ID\"}"
    ;;
  agent6)
    NS=mcp-agent-tracing; SVC=agent6; PORT=9006; ROUTE=/subprocess-task
    BODY="{\"task_id\":\"$TASK_ID\"}"
    ;;
  *)
    echo "Usage: $0 <agent2|agent3|agent3-openllmetry|agent4|agent5|agent6> [task_id]"
    exit 1
    ;;
esac

LOCAL_PORT=$((10000 + RANDOM % 9000))
kubectl port-forward "svc/$SVC" "$LOCAL_PORT:$PORT" -n "$NS" > "/tmp/pf-single-$SVC.log" 2>&1 &
PF_PID=$!
trap 'kill $PF_PID 2>/dev/null' EXIT
sleep 2

date -u +"%Y-%m-%dT%H:%M:%SZ (UTC) -- workload:$SVC"
curl -s -X POST "http://127.0.0.1:$LOCAL_PORT$ROUTE" -H 'Content-Type: application/json' -d "$BODY" | pp
echo
