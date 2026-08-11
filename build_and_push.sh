#!/usr/bin/env bash
# Usage: DOCKERHUB_USERNAME=yourname ./build_and_push.sh
set -euo pipefail

if [ -z "${DOCKERHUB_USERNAME:-}" ]; then
  echo "Set DOCKERHUB_USERNAME first: DOCKERHUB_USERNAME=yourname ./build_and_push.sh"
  exit 1
fi

for svc in agent1 agent2 agent3 agent4 agent5 agent6 mcp-tool-server; do
  echo "=== building + pushing $svc (linux/amd64,linux/arm64) ==="
  docker buildx build --platform linux/amd64,linux/arm64 \
    -f "Dockerfile.$svc" -t "$DOCKERHUB_USERNAME/$svc:latest" --push .
done

echo
echo "Done. Now update k8s/manifests.yaml: replace <YOUR_DOCKERHUB_USERNAME> with $DOCKERHUB_USERNAME"
echo "Then: kubectl apply -f k8s/manifests.yaml"
