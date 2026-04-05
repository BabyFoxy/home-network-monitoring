# Daily Gaming Report — Setup Guide

## Overview

A daily HTML email report summarising gaming-related DNS activity from the home network, sent automatically via Synology Task Scheduler.

**What it sends:** one email per day to configured recipients.
**What it is based on:** Loki DNS query log data (same source as the dashboard).
**What it is not:** a gameplay duration estimate — wording is conservative throughout.

---

## Prerequisites

1. `.env` configured with SMTP credentials and child device names
2. Loki running and accessible at `LOKI_URL`
3. Python 3.8+ on the NAS (available by default on Synology)

---

## Setup

### 1. Configure `.env`

Copy the relevant section from `.env.example` into your `.env`:

```bash
cd /volume1/docker/home-network-monitoring
cp .env.example .env
# Then edit .env and fill in:
#   CHILD_DEVICES=Ethan PC,EthanR-PC
#   SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD
#   SMTP_FROM, SMTP_TO
#   REPORT_TIMEZONE
```

### 2. Child device names

The `CHILD_DEVICES` variable is a regex pattern matched against the `client_name` field in DNS logs. Use exact names or `|`-separated alternatives:

```
# Single child
CHILD_DEVICES=Ethan PC

# Multiple children
CHILD_DEVICES=Ethan PC|EthanR-PC|Elissa
```

Check exact names in the Grafana dashboard variable dropdown.

### 3. Test the report manually

```bash
cd /volume1/docker/home-network-monitoring

# Run once without sending (prints to stdout if SMTP not set)
python3 scripts/send_daily_report.py

# Or with SMTP configured:
SMTP_HOST=smtp.example.com \
SMTP_PORT=587 \
SMTP_USERNAME=user \
SMTP_PASSWORD=pass \
SMTP_FROM=sender@example.com \
SMTP_TO=parent@example.com \
SMTP_USE_TLS=true \
LOKI_URL=http://192.168.1.5:3100 \
CHILD_DEVICES="Ethan PC|EthanR-PC" \
REPORT_TIMEZONE=Australia/Sydney \
python3 scripts/send_daily_report.py
```

### 4. Schedule via Synology Task Scheduler

1. Open **Control Panel → Task Scheduler**
2. **Create → Scheduled Task → User-defined script**
3. Configure:
   - Task name: `Daily Gaming Report`
   - User: `root`
   - Schedule: daily at `07:00` (or your preferred time)
4. Event: **Boot-up**
5. Script:

```bash
cd /volume1/docker/home-network-monitoring && \
python3 scripts/send_daily_report.py >> /volume1/docker/home-network-monitoring/logs/report.log 2>&1
```

Create the log directory first:
```bash
mkdir -p /volume1/docker/home-network-monitoring/logs
```

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | `LOKI_URL` not set |
| 2 | Cannot connect to Loki |
| 3 | Data fetch/query failed |
| 4 | SMTP send failed |

Task Scheduler should flag any non-zero exit code as a failure.

---

## What the report contains

1. **Summary** — device count, total gaming hits, blocked hits, top domains
2. **Per device** — gaming hits, blocked hits, top domains, entertainment overlap, one-line note
3. **Recent blocked gaming evidence** — up to 15 most recent blocked gaming DNS lookups
4. **Recent entertainment context** — up to 10 most recent entertainment DNS lookups from active child devices
5. **Conclusion** — one-paragraph plain-language summary
6. **Notes** — caveats about evidence vs. proof

---

## Customisation

### Change report time

Edit the Synology Task Scheduler schedule, or set `REPORT_TIMEZONE` to match your local time.

### Change styling

Edit the CSS in `scripts/send_daily_report.py` — the `render_html()` function contains all styles inline.

### Change domain filters

The `GAMING_PATTERNS` and `ENTERTAINMENT_PATTERNS` constants in `send_daily_report.py` must match the current dashboard rules. Update both files together.

### Dry run (no email)

Leave `SMTP_HOST` empty in `.env`. The script prints the plain-text report to stdout.

---

## Troubleshooting

**"Cannot connect to Loki":** check `LOKI_URL` in `.env` and that the Loki container is running (`docker compose ps`).

**"SMTP config incomplete":** ensure all five SMTP variables are set in `.env`.

**Empty report but gaming activity exists:** check that `CHILD_DEVICES` matches the exact `client_name` values in Loki.

**Report sent but looks wrong:** run manually with stdout output to see any Python errors.

---

## Updating the script

After any change to the dashboard's domain filters, copy the updated patterns into `send_daily_report.py` (the `GAMING_PATTERNS` and `ENTERTAINMENT_PATTERNS` constants).
