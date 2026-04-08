# Daily Gaming Report — Setup Guide

## Overview

A daily HTML email report summarising gaming-related DNS activity from the home network, sent automatically at 07:00 NAS local time.

**What it sends:** one email per day to configured recipients covering the **previous 24 hours** (rolling window ending at send time).
**What it is based on:** Loki DNS query log data (same source as the dashboard).
**What it is not:** a gameplay duration estimate — wording is conservative throughout.

---

## Prerequisites

1. `.env` configured with SMTP credentials and exclude list
2. Loki running and accessible at `LOKI_URL`
3. Python 3.8+ on the NAS (available by default on Synology)

---

## Setup

### 1. Configure `.env`

```bash
cd /volume1/docker/home-network-monitoring
cp .env.example .env
vi .env
```

Required values:

```bash
LOKI_URL=http://192.168.1.5:3100
REPORT_TIMEZONE=Australia/Sydney
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=you@gmail.com
SMTP_TO=parent1@example.com,parent2@example.com
SMTP_USE_TLS=true

# Optional: override the default exclusion list (Fox Devices + David iPhone)
# EXCLUDE_DEVICES=192[.]168[.]1[.]1$|192[.]168[.]1[.]18$|...
```

### 2. Device filtering — exclusion mode

The report monitors **all devices** and excludes those matching `EXCLUDE_DEVICES`.

The default exclusion list covers the **Fox Devices** AdGuard group and David iPhone:
```
192.168.1.1/3/5/6/14/16/17/18/101/250/251
```

To exclude additional devices, override `EXCLUDE_DEVICES` in `.env` using pipe-separated RE2 patterns. Use `[.]` not `\.` for literal dots.

To find the `client_name` of a device, check the Grafana dashboard **Child Device** variable dropdown.

### 3. Test the report manually

```bash
cd /volume1/docker/home-network-monitoring
python3 scripts/send_daily_report.py
```

Leave `SMTP_HOST` empty in `.env` to print the plain-text report to stdout instead of sending.

### 4. Schedule via /etc/crontab (active on NAS)

The cron entry is already installed in `/etc/crontab` on the NAS:

```
0	7	*	*	*	root	cd /volume1/docker/home-network-monitoring && python3 scripts/send_daily_report.py >> /volume1/docker/home-network-monitoring/logs/report.log 2>&1
```

Runs every day at **07:00 NAS local time**, covering the previous 24 hours.

To verify:
```bash
grep send_daily /etc/crontab
```

To change the time, edit `/etc/crontab` and reload crond:
```bash
vi /etc/crontab
kill -HUP $(ps | grep crond | grep -v grep | awk '{print $1}')
```

View recent log output:
```bash
tail -20 /volume1/docker/home-network-monitoring/logs/report.log
```

---

## What the report contains

1. **Summary** — device count, total gaming DNS hits, blocked hits, top domains
2. **Per device** — gaming hits, blocked %, top domains, one-line note
3. **Recent gaming DNS queries** — up to 15 most recent gaming lookups with ALLOWED/BLOCKED status
4. **Recent entertainment context** — up to 10 recent YouTube/Discord/Twitch lookups from monitored devices
5. **Conclusion** — plain-language summary
6. **Notes** — caveats about DNS evidence vs. proof of play

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | `LOKI_URL` not set |
| 2 | Cannot connect to Loki |
| 3 | Data fetch/query failed |
| 4 | SMTP send failed |

---

## Troubleshooting

**"Cannot connect to Loki":** check `LOKI_URL` in `.env` and that Loki is running (`docker compose ps`).

**"SMTP config incomplete":** ensure all SMTP variables are set in `.env`.

**Empty report / no devices shown:** all active devices may be in the exclusion list. Check `EXCLUDE_DEVICES` against actual `client_name` values in Grafana.

**STATUS showing wrong value:** the script detects blocked queries by the `— BLOCKED` marker written by Alloy. If Alloy config changes the output format, update `parse_log_line()` in the script accordingly.

---

## Customisation

### Change domain filters

`GAMING_PATTERNS` and `ENTERTAINMENT_PATTERNS` in `send_daily_report.py` must stay in sync with the dashboard panel queries. Update both together.

### Change styling

All CSS is inline in the `render_html()` function in `send_daily_report.py`.
