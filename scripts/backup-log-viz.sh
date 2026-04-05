#!/usr/bin/env bash
set -euo pipefail

STACK_DIR="/volume1/docker/log-viz"
BACKUP_ROOT="$STACK_DIR/backups"
DATE=$(date +%Y-%m-%d_%H%M%S)
DEST="$BACKUP_ROOT/$DATE"
KEEP=7

echo "=== log-viz backup: $DATE ==="

mkdir -p "$DEST"

# Core configs
cp "$STACK_DIR/docker-compose.yml" "$DEST/"
cp "$STACK_DIR/loki/config.yml"    "$DEST/loki-config.yml"
cp "$STACK_DIR/alloy/config.alloy" "$DEST/alloy-config.alloy"

# .env if present
if [ -f "$STACK_DIR/.env" ]; then
  cp "$STACK_DIR/.env" "$DEST/env.bak"
fi

# Grafana provisioning
cp -r "$STACK_DIR/grafana/provisioning" "$DEST/grafana-provisioning"

# Grafana sqlite database (grafana.db)
GRAFANA_DB="$STACK_DIR/grafana/data/grafana.db"
if [ -f "$GRAFANA_DB" ]; then
  cp "$GRAFANA_DB" "$DEST/grafana.db"
  echo "  grafana.db backed up"
else
  echo "  grafana.db not found — skipping (first run?)"
fi

echo "  Backup written to: $DEST"

# Rotate: keep last $KEEP backups
echo "  Rotating old backups (keeping $KEEP)..."
ls -1dt "$BACKUP_ROOT"/20* 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -rf

echo "  Done."
