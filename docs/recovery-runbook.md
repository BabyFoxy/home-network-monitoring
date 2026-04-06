# Recovery Runbook — home-network-monitoring on Synology NAS

> Synology NAS IP: `192.168.1.5`, SSH port: `223`, user: `root`
> SSH key: `~/.ssh/id_nas`
> GitHub: `https://github.com/BabyFoxy/home-network-monitoring`

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
| Daily report cron | `/etc/crontab` (NAS system file) | System cron |
| Report logs | `/volume1/docker/home-network-monitoring/logs/report.log` | File on NAS |

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
- Cron entry in `/etc/crontab`

**What survives:**
- AdGuard still running and logging
- Docker named volumes still exist (Loki data, Grafana state)

### Recovery from GitHub

```bash
# On the NAS:
git clone https://github.com/BabyFoxy/home-network-monitoring.git \
  /volume1/docker/home-network-monitoring
cd /volume1/docker/home-network-monitoring
```

### Recreate .env

```bash
cp .env.example .env
vi .env
```

Fill in all values:

```bash
GRAFANA_ADMIN_PASSWORD=<your-password>
LOKI_URL=http://192.168.1.5:3100
CHILD_DEVICES=Ethan PC|EthanR-PC|MBP-S26226
REPORT_TIMEZONE=Australia/Sydney
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=babywindfox@gmail.com
SMTP_PASSWORD=<gmail-app-password>
SMTP_FROM=babywindfox@gmail.com
SMTP_TO=lynn.tan.88@live.com,david.ren@live.com
SMTP_USE_TLS=true
```

### Restart stack

```bash
docker compose up -d
```

### Restore cron entry

```bash
echo '0	7	*	*	*	root	cd /volume1/docker/home-network-monitoring && python3 scripts/send_daily_report.py >> /volume1/docker/home-network-monitoring/logs/report.log 2>&1' >> /etc/crontab
mkdir -p /volume1/docker/home-network-monitoring/logs
kill -HUP $(ps | grep crond | grep -v grep | awk '{print $1}')
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

**Backup Loki data (stop Loki first for a consistent snapshot):**

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

**Backup `.env` (credentials — keep separately):**

```bash
cp /volume1/docker/home-network-monitoring/.env /volume1/docker/backups/.env.hnm-$(date +%Y%m%d)
```

---

## Quick Status Check

```bash
cd /volume1/docker/home-network-monitoring
docker compose ps
# All three services (loki, alloy, grafana) should show "Up"

curl -s http://localhost:3100/loki/api/v1/ready   # loki
curl -s http://localhost:12345/-/ready             # alloy
```

**Check daily report cron is installed:**
```bash
grep send_daily /etc/crontab
```

**Check report log:**
```bash
tail -20 /volume1/docker/home-network-monitoring/logs/report.log
```

---

## Rebuild from Repo (Safe)

Pull latest config and restart without touching data volumes:

```bash
cd /volume1/docker/home-network-monitoring
git pull
docker compose up -d
```

Named volumes are never touched by `up -d` — only containers are recreated.
