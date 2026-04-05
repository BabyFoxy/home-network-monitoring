#!/usr/bin/env bash
set -euo pipefail

STACK_DIR="/volume1/docker/log-viz"
cd "$STACK_DIR"

echo ""
echo "=== Container status ==="
docker compose ps

echo ""
echo "=== Grafana (last 20 lines) ==="
docker compose logs --tail=20 grafana

echo ""
echo "=== Loki (last 20 lines) ==="
docker compose logs --tail=20 loki

echo ""
echo "=== Alloy (last 30 lines) ==="
docker compose logs --tail=30 alloy

echo ""
echo "Tip: follow a single service with:"
echo "  docker compose logs -f alloy"
