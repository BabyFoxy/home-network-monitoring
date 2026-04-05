# Deployment notes

## Prerequisites

- Synology NAS with Docker and Docker Compose installed (Container Manager)
- AdGuard Home already running at `/volume1/docker/adguard/`
- SSH access to the NAS

## First deployment

### 1. Copy files to Synology

From your Mac:
```bash
rsync -av /Volumes/AI_Drive/Projects/home-network-monitoring/ \
  fox@192.168.1.NAS_IP:/volume1/docker/log-viz/ \
  --exclude='.git' --exclude='.DS_Store'
```

Or clone the GitHub repo directly on the NAS:
```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/home-network-monitoring.git \
  /volume1/docker/log-viz
```

### 2. Create the .env file

```bash
cd /volume1/docker/log-viz
cp .env.example .env
nano .env    # set GRAFANA_ADMIN_PASSWORD and NAS_IP
```

### 3. Fix permissions for bind mount directories

```bash
mkdir -p /volume1/docker/log-viz/loki/data
mkdir -p /volume1/docker/log-viz/grafana/data
chmod 777 /volume1/docker/log-viz/loki/data
chmod 777 /volume1/docker/log-viz/grafana/data
```

### 4. Start the stack

```bash
cd /volume1/docker/log-viz
docker compose up -d
```

### 5. Check everything is running

```bash
docker compose ps
bash scripts/validate-stack.sh
```

---

## Day-to-day operations

### Restart one service
```bash
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

### Pull latest images and redeploy
```bash
docker compose pull
docker compose up -d
```

### Validate AdGuard ingestion

1. Open Grafana at `http://NAS_IP:3300`
2. Go to Explore → select Loki datasource
3. Run: `{job="adguard"}`
4. You should see lines like:
   `192.168.1.136 (Home Assistant) -> firmware.nanoleaf.me [A] status=NOERROR ...`

### Test UDM syslog arrival

Point the UDM SE syslog to `NAS_IP:5514` (UDP), then:
```bash
# Watch Alloy receive syslog in real time
docker compose logs -f alloy

# Or query in Grafana Explore:
# {job="udm"}
```

### Test with netcat (simulate a UDM syslog message)
```bash
echo "Apr  5 10:00:01 udm kernel: test message" | \
  nc -u -w1 127.0.0.1 5514
```
Then check Grafana Explore for `{job="udm"}`.

---

## Where to paste a real UDM sample

Once you have a real UDM syslog line, paste it into:
`/volume1/docker/log-viz/alloy/samples/udm-syslog-sample.txt`

Then follow `docs/next-steps-udm-parser.md` to build a proper parser.
