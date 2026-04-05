# Recovery Runbook — home-network-monitoring on Synology NAS

> Synology NAS IP: `192.168.1.5`, SSH port: `223`, user: `root`
> SSH key: `~/.ssh/id_nas`

---

## What's Where

| What | Location | Type |
|---|---|---|
| Live config | `/volume1/docker/home-network-monitoring/` | Bind mount (NAS filesystem) |
| Dashboard JSON | `grafana/provisioning/dashboards/dns-overview.json` | Bind mount |
| Alloy config | `alloy/config.alloy` | Bind mount |
| Loki config | `loki/config.yml` | Bind mount |
| Grafana state | Docker named volume `home-network-monitoring_grafana-data` | Docker managed |
| Loki historical data | Docker named volume `home-network-monitoring_loki-data` | Docker managed |
| Enrichment hosts | `enrichment/udm-hosts.json` | Bind mount |
| Credentials | `/volume1/docker/home-network-monitoring/.env` | File on NAS (gitignored) |
| AdGuard source | `/volume1/docker/adguard/work/data/querylog.json` | Bind mount to AdGuard volume |

---

## Scenario 1 — Delete Only Containers

**What is lost:** nothing permanent.

Configs survive (bind mounts), Loki data survives (named volume), Grafana dashboards survive (provisioned from JSON on NAS filesystem).

```bash
cd /volume1/docker/home-network-monitoring
docker compose up -d
```

Stack fully restored. All data intact.

---

## Scenario 2 — Delete Containers + Named Volumes

**What is lost:**
- All Loki historical DNS data (`loki-data` wiped — chunks, tsdb index, compaction state)
- Grafana preferences, saved views, org settings (`grafana-data` wiped)
- Manual dashboard edits done in UI (provisioned JSON dashboards reload from bind mount)

**What survives:**
- All config files (bind mounts)
- AdGuard querylog still being written

```bash
cd /volume1/docker/home-network-monitoring
docker compose up -d
```

Loki data loss is the real cost. Grafana dashboards reload from JSON automatically.

---

## Scenario 3 — Lose `/volume1/docker/home-network-monitoring/`

**What is lost:**
- All config files and dashboard JSON
- Enrichment files (`enrichment/`)
- `.env` (credentials — must be recreated)

**What survives:**
- AdGuard still running and logging
- Docker named volumes still exist

**Recovery from GitHub:**

```bash
# On the NAS:
mkdir -p /volume1/docker/home-network-monitoring
cd /volume1/docker/home-network-monitoring
git init
git remote add origin https://github.com/BabyFoxy/home-network-monitoring.git
git fetch
git checkout main

# Recreate .env (credentials are lost if not backed up)
cat > .env << 'EOF'
GRAFANA_ADMIN_PASSWORD=<your-password>
NAS_IP=192.168.1.5
EOF

# Restart
docker compose up -d
```

---

## Reset Grafana Admin Password

If `.env` is lost and Grafana won't accept the old password:

```bash
docker exec -it hnm-grafana grafana cli admin reset-admin-password <new-password>
# Then update .env with the new password
```

---

## Backup Commands

**Backup Loki data (stop Loki first to ensure consistent snapshot):**

```bash
cd /volume1/docker/home-network-monitoring
docker compose stop loki
docker run --rm \
  -v home-network-monitoring_loki-data:/data \
  -v /volume1/docker/backups:/backup \
  alpine \
  tar czf /backup/loki-data-$(date +%Y%m%d).tar.gz /data
docker compose start loki
```

**Backup `.env` (credentials — keep this separate):**

```bash
cp /volume1/docker/home-network-monitoring/.env /volume1/docker/backups/.env.hnm-$(date +%Y%m%d)
```

---

## Quick Status Check

```bash
cd /volume1/docker/home-network-monitoring
docker compose ps
```

All three services should show `Up`.

```bash
curl -s http://localhost:3100/loki/api/v1/ready  # loki health
curl -s http://localhost:12345  # alloy health
```

---

## Rebuild from Repo (Safe)

If you want to pull latest config and restart without touching data volumes:

```bash
cd /volume1/docker/home-network-monitoring
git pull
docker compose up -d
```

Named volumes are never touched by `up -d` — only containers are recreated.
