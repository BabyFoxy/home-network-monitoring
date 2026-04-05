# home-network-monitoring — DNS log visualisation

Self-hosted DNS and network log visualisation on Synology NAS using Docker Compose, Grafana, Loki, and Grafana Alloy.

**Primary goal:** given a device, show which domains it accessed over time, with blocked queries clearly visible.

---

## Stack

| Service | Port | Purpose |
|---|---|---|
| Grafana | 3300 | Visualisation UI |
| Loki | 3100 | Log storage and querying |
| Alloy | 12345 (UI), 5514/UDP | Log ingestion and parsing |

---

## Quick start

```bash
# On the Synology NAS (SSH)
cd /volume1/docker/log-viz

# Create .env
cp .env.example .env
nano .env   # set GRAFANA_ADMIN_PASSWORD and NAS_IP

# Create data dirs
mkdir -p loki/data grafana/data
chmod 777 loki/data grafana/data

# Start
docker compose up -d

# Check
docker compose ps
curl http://127.0.0.1:3100/ready
curl http://127.0.0.1:12345/-/ready || true
```

Open Grafana at `http://NAS_IP:3300` (replace `NAS_IP` with your NAS IP address).

---

## Core operations

```bash
# Service status
docker compose ps

# Follow logs
docker compose logs -f alloy
docker compose logs -f loki
docker compose logs -f grafana

# Restart one service
docker compose restart alloy

# Pull latest images and redeploy
docker compose pull && docker compose up -d

# Loki health check
curl http://127.0.0.1:3100/ready

# Alloy health check
curl http://127.0.0.1:12345/-/ready || true
```

---

## Validation queries (Grafana Explore → Loki)

```logql
# All AdGuard DNS events
{job="adguard"}

# Filter by device IP
{job="adguard", client="192.168.1.136"}

# Blocked queries only
{job="adguard", disallowed="true"}

# Search for a domain across all devices
{job="adguard"} |= "youtube.com"

# Raw UDM syslog (after pointing UDM at NAS:5514)
{job="udm"}
```

---

## Scripts

| Script | Purpose |
|---|---|
| `scripts/validate-stack.sh` | Health check all services |
| `scripts/tail-useful-logs.sh` | Print recent logs from all containers |
| `scripts/backup-log-viz.sh` | Backup configs and Grafana DB |

```bash
bash scripts/validate-stack.sh
bash scripts/tail-useful-logs.sh
bash scripts/backup-log-viz.sh
```

---

## Updating from GitHub

```bash
cd /volume1/docker/log-viz
git pull
docker compose pull
docker compose up -d
```

---

## Directory layout

```
/volume1/docker/log-viz/
├── docker-compose.yml
├── .env                    ← not in git, created from .env.example
├── loki/config.yml
├── alloy/config.alloy
├── grafana/provisioning/datasources/loki.yml
├── scripts/
└── docs/
```

---

## Further reading

- `docs/deployment-notes.md` — step-by-step first deployment
- `docs/validation-checklist.md` — full acceptance checklist
- `docs/next-steps-udm-parser.md` — how to build a UDM parser after capturing real samples
