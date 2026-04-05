#!/usr/bin/env bash
# update-enrichment.sh
# Reads enrichment/udm-hosts.json and regenerates the IP→name dict
# in alloy/config.alloy, then reloads Alloy.
#
# Run manually after udm-hosts.json is updated:
#   bash /volume1/docker/home-network-monitoring/scripts/update-enrichment.sh

set -euo pipefail

STACK_DIR="/volume1/docker/home-network-monitoring"
HOSTS_FILE="$STACK_DIR/enrichment/udm-hosts.json"
ALLOY_CONFIG="$STACK_DIR/alloy/config.alloy"
DOCKER=/var/packages/ContainerManager/target/usr/bin/docker

if [ ! -f "$HOSTS_FILE" ]; then
  echo "ERROR: $HOSTS_FILE not found" >&2
  exit 1
fi

echo "=== Generating enrichment dict from $HOSTS_FILE ==="

# Build the Go template dict string from udm-hosts.json
DICT=$(python3 << 'PYEOF'
import json, sys

with open("/volume1/docker/home-network-monitoring/enrichment/udm-hosts.json") as f:
    data = json.load(f)

pairs = []
for item in data.get("items", []):
    ip   = item.get("ip", "").strip()
    name = item.get("hostname_clean", "").strip()
    if ip and name:
        pairs.append(f'"{ip}" "{name}"')

print(" ".join(pairs))
PYEOF
)

echo "  Found $(echo "$DICT" | wc -w) tokens ($(python3 -c "import json; d=json.load(open('/volume1/docker/home-network-monitoring/enrichment/udm-hosts.json')); print(len(d.get('items',[])),'') " 2>/dev/null) entries)"

# Build the full template string with AdGuard CP priority, then dict lookup, then IP fallback
TEMPLATE='{{ if .client_name }}{{ .client_name }}{{ else }}{{ $m := dict '"$DICT"' }}{{ $n := get $m .client }}{{ if $n }}{{ $n }}{{ else }}{{ .client }}{{ end }}{{ end }}'

# Replace the template line in alloy/config.alloy
python3 << PYEOF
import re

with open("$ALLOY_CONFIG") as f:
    content = f.read()

new_template_line = '    template = \`'"$TEMPLATE"'\`'

# Replace the existing template line for client_name stage
content = re.sub(
    r'(  stage\.template \{\n    source\s+=\s+"client_name"\n)    template = \`[^\`]*\`',
    r'\1' + new_template_line,
    content
)

with open("$ALLOY_CONFIG", "w") as f:
    f.write(content)

print("  alloy/config.alloy updated")
PYEOF

# Reload Alloy via HTTP (no restart needed)
echo "  Reloading Alloy..."
if curl -sf -X POST "http://127.0.0.1:12345/-/reload" > /dev/null 2>&1; then
  echo "  Alloy reloaded via HTTP"
else
  echo "  HTTP reload failed, restarting container..."
  $DOCKER restart hnm-alloy
fi

echo "=== Done ==="
