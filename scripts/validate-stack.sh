#!/usr/bin/env bash
set -euo pipefail

STACK_DIR="/volume1/docker/log-viz"
PASS=0
FAIL=0

ok()   { echo "  [OK]  $1"; ((PASS++)); }
fail() { echo "  [FAIL] $1"; ((FAIL++)); }
info() { echo "  [--]  $1"; }

echo ""
echo "=== DNS Log-Viz stack validation ==="
echo ""

# --- Docker Compose services ---
echo ">> Docker Compose service health"
cd "$STACK_DIR"

for svc in log-viz-grafana log-viz-loki log-viz-alloy; do
  state=$(docker inspect --format '{{.State.Status}}' "$svc" 2>/dev/null || echo "missing")
  if [ "$state" = "running" ]; then
    ok "$svc is running"
  else
    fail "$svc is $state"
  fi
done

echo ""

# --- Grafana ---
echo ">> Grafana (port 3300)"
if curl -sf -o /dev/null -w "%{http_code}" http://127.0.0.1:3300/api/health | grep -q "200"; then
  ok "Grafana /api/health returns 200"
else
  fail "Grafana did not respond on port 3300"
fi

echo ""

# --- Loki ---
echo ">> Loki (port 3100)"
loki_ready=$(curl -sf http://127.0.0.1:3100/ready 2>/dev/null || echo "")
if echo "$loki_ready" | grep -qi "ready"; then
  ok "Loki /ready reports ready"
else
  fail "Loki /ready did not return ready (got: $loki_ready)"
fi

echo ""

# --- Alloy ---
echo ">> Alloy (port 12345)"
alloy_resp=$(curl -sf http://127.0.0.1:12345/-/ready 2>/dev/null || echo "")
if [ -n "$alloy_resp" ]; then
  ok "Alloy responded on port 12345"
else
  fail "Alloy did not respond on port 12345"
fi

echo ""

# --- Loki label check (needs some data ingested first) ---
echo ">> Loki label existence (best-effort, may be empty on first run)"
labels=$(curl -sf "http://127.0.0.1:3100/loki/api/v1/labels" 2>/dev/null || echo "")
if echo "$labels" | grep -q "adguard"; then
  ok "Loki has 'adguard' job label — AdGuard ingestion is working"
else
  info "No 'adguard' label yet — either no data ingested or Alloy still starting"
fi

echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo "One or more checks failed. Run scripts/tail-useful-logs.sh for details."
  exit 1
fi
