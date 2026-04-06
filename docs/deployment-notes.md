# Deployment Notes

## Prerequisites

- Synology NAS with Docker and Docker Compose installed (Container Manager)
- AdGuard Home already running at `/volume1/docker/adguard/`
- SSH access to the NAS: `ssh -i ~/.ssh/id_nas -p 223 root@192.168.1.5`

---

## First deployment

### 1. Clone repo onto the NAS

```bash
ssh -i ~/.ssh/id_nas -p 223 root@192.168.1.5
git clone https://github.com/BabyFoxy/home-network-monitoring.git \
  /volume1/docker/home-network-monitoring
```

### 2. Create the .env file

```bash
cd /volume1/docker/home-network-monitoring
cp .env.example .env
vi .env
```

Fill in all values — the minimum required set:

```bash
# Grafana
GRAFANA_ADMIN_PASSWORD=<your-password>

# Loki (do not change)
LOKI_URL=http://192.168.1.5:3100

# Child device names — pipe-separated regex, must match client_name in DNS logs
# Check exact names in Grafana dashboard variable dropdown
CHILD_DEVICES=Ethan PC|EthanR-PC|MBP-S26226

# Timezone (IANA)
REPORT_TIMEZONE=Australia/Sydney

# SMTP (Gmail example)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=you@gmail.com
SMTP_TO=recipient@example.com
SMTP_USE_TLS=true
```

### 3. Start the stack

```bash
cd /volume1/docker/home-network-monitoring
docker compose up -d
```

### 4. Verify everything is running

```bash
docker compose ps
# All three services (loki, alloy, grafana) should show "Up"

curl -s http://localhost:3100/loki/api/v1/ready   # loki
curl -s http://localhost:12345/-/ready             # alloy
```

Open Grafana at `http://192.168.1.5:3300` and go to Explore → Loki, run:
```
{job="adguard"}
```
You should see lines like:
```
EthanR-PC → roblox.com [A]
```

### 5. Install the daily report cron

```bash
echo '0	7	*	*	*	root	cd /volume1/docker/home-network-monitoring && python3 scripts/send_daily_report.py >> /volume1/docker/home-network-monitoring/logs/report.log 2>&1' >> /etc/crontab
mkdir -p /volume1/docker/home-network-monitoring/logs
kill -HUP $(ps | grep crond | grep -v grep | awk '{print $1}')
```

---

## Day-to-day operations

### Restart one service
```bash
cd /volume1/docker/home-network-monitoring
docker compose restart alloy
docker compose restart loki
docker compose restart grafana
```

### Follow live logs
```bash
docker compose logs -f alloy
docker compose logs -f loki
docker compose logs -f grafana
```

### Pull latest config from GitHub and restart
```bash
cd /volume1/docker/home-network-monitoring
git pull
docker compose up -d
```

Named volumes (Loki data, Grafana state) are never touched by `up -d`.

### Update device enrichment (IP → name map)

After adding a new device to the network:
```bash
cd /volume1/docker/home-network-monitoring
bash scripts/update-enrichment.sh
```

This reads `enrichment/udm-hosts.json`, regenerates the IP→name dict in `alloy/config.alloy`, and reloads Alloy.

### Test daily report manually
```bash
cd /volume1/docker/home-network-monitoring
python3 scripts/send_daily_report.py
```

Leave `SMTP_HOST` empty in `.env` to print to stdout instead of sending email.

### View report log
```bash
tail -f /volume1/docker/home-network-monitoring/logs/report.log
```
