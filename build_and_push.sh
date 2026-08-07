#!/usr/bin/env bash
# Usage: DOCKERHUB_USERNAME=yourname ./build_and_push.sh
set -euo pipefail

if [ -z "${DOCKERHUB_USERNAME:-}" ]; then
  echo "Set DOCKERHUB_USERNAME first: DOCKERHUB_USERNAME=yourname ./build_and_push.sh"
  exit 1
fi

for svc in agent1 agent2 mcp-tool-server; do
  echo "=== building $svc ==="
  docker build -f "Dockerfile.$svc" -t "$DOCKERHUB_USERNAME/$svc:latest" .
  echo "=== pushing $svc ==="
  docker push "$DOCKERHUB_USERNAME/$svc:latest"
done

echo
echo "Done. Now update k8s/manifests.yaml: replace <YOUR_DOCKERHUB_USERNAME> with $DOCKERHUB_USERNAME"
echo "Then: kubectl apply -f k8s/manifests.yaml"
