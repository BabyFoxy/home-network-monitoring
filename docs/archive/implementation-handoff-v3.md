# DNS and network log visualisation system — implementation handoff v3

## Purpose

This document is the execution handoff for building a free, self-hosted log visualisation stack on a Synology NAS using Docker.

The primary user outcome is:

**Given a device, show which domains it accessed over time, with blocked queries clearly visible.**

This handoff is written so it can be given directly to an IDE or coding agent to start implementation.

---

## What success looks like

The finished system must let the operator do all of the following from Grafana:

1. View all DNS query events collected from AdGuard Home
2. Filter DNS events by device IP
3. Filter DNS events by device name where available
4. Find blocked DNS queries
5. Search for a domain across all devices
6. View recent raw UDM syslog events for correlation

Everything else is secondary.

---

## Locked design decisions

These decisions are already made and should not be re-litigated during implementation.

### Data sources

- **Primary source of truth for domain history**: AdGuard Home `querylog.json`
- **Secondary source**: UDM SE external syslog / activity logging

### Platform

- Synology NAS
- Docker Compose deployment
- Grafana for visualisation
- Loki for log storage and querying
- Grafana Alloy for ingestion and parsing

### Network ports

- Grafana: `3300`
- Loki: `3100`
- Alloy syslog listener: `5514/udp`
- Alloy HTTP/UI: `12345`

### Evidence model

- DNS query logs are the authoritative source for per-device domain history
- UDM logs are supporting evidence only
- UDM logs may help detect some bypass or non-DNS activity, but they do **not** fully reconstruct domain history

### Cardinality rule

**Do not use `domain` as a Loki label in the initial implementation.**

Use these low-cardinality labels for AdGuard logs only:
- `job="adguard"`
- `source="dns_querylog"`
- `client`
- `client_name`
- `query_type`
- `disallowed`

Keep `domain` in the log line. If the deployed Loki and Alloy versions support structured metadata cleanly, `domain` may also be stored there, but not as a label.

### UDM parsing rule

Do **not** guess the UDM syslog format.

The initial implementation must:
- ingest raw UDM syslog
- apply only static labels `job="udm"` and `source="syslog"`
- preserve the original message body

Only add parsed labels such as `act` or `cat` after real samples from this UDM SE are captured and validated.

---

## Environment details

| Item | Value |
|---|---|
| Router / gateway | UniFi Dream Machine SE |
| UniFi Network version | 10.2.105 |
| DNS resolver | AdGuard Home |
| AdGuard host IP | `192.168.1.220` |
| AdGuard API | `http://192.168.1.220:88/control/querylog` |
| AdGuard log file inside container | `/opt/adguardhome/work/data/querylog.json` |
| AdGuard log file on Synology host | `/volume1/docker/adguard/work/data/querylog.json` |
| AdGuard config on Synology host | `/volume1/docker/adguard/conf/AdGuardHome.yaml` |
| NAS timezone | `Australia/Sydney` |
| LAN subnet | `192.168.1.0/24` |

### Example AdGuard query log record

```json
{
  "client": "192.168.1.136",
  "client_info": { "whois": {}, "name": "Home Assistant", "disallowed": false, "disallowed_rule": "" },
  "question": { "class": "IN", "name": "firmware.nanoleaf.me", "type": "A" },
  "status": "NOERROR",
  "reason": "NotFilteredNotFound",
  "rules": [{"filter_list_id": 1735967203, "text": "@@||cloudfront.net^$important"}],
  "disallowed": false,
  "time": "2026-04-05T06:22:19.190672312Z",
  "upstream": "8.8.4.4:53",
  "answer_dnssec": false,
  "cached": false,
  "elapsed_ms": 23.637
}
```

### Fields to extract from AdGuard

- `client`
- `client_info.name` as `client_name`
- `question.name` as `domain`
- `question.type` as `query_type`
- `status`
- `reason`
- `disallowed`
- `time` as the event timestamp
- `upstream`
- `cached`

---

## Directory layout to create on Synology

Create this structure under:

`/volume1/docker/log-viz/`

```text
/volume1/docker/log-viz/
├── docker-compose.yml
├── .env.example
├── README.md
├── loki/
│   ├── config.yml
│   └── data/
├── alloy/
│   ├── config.alloy
│   └── samples/
│       └── udm-syslog-sample.txt
├── grafana/
│   ├── data/
│   └── provisioning/
│       └── datasources/
│           └── loki.yml
├── scripts/
│   ├── validate-stack.sh
│   ├── backup-log-viz.sh
│   └── tail-useful-logs.sh
└── docs/
    ├── deployment-notes.md
    ├── validation-checklist.md
    └── next-steps-udm-parser.md
```

---

## Required deliverables

The IDE should generate all items below.

### Deliverable 1: Base Docker stack

Create:
- `docker-compose.yml`
- `loki/config.yml`
- `alloy/config.alloy`
- `grafana/provisioning/datasources/loki.yml`
- `.env.example`
- `README.md`

#### Base stack requirements

##### Common

- Use Docker Compose
- Put all services on one bridge network named `log-viz-net`
- Set `TZ=Australia/Sydney` on all services
- Set `restart: unless-stopped` on all services
- Use bind mounts under `/volume1/docker/log-viz/`

##### Grafana

- Expose `3300:3000`
- Persist `/var/lib/grafana`
- Mount provisioning directory read-only
- Use environment variable for admin password
- Use environment variable or placeholder for root URL, for example `http://SYNOLOGY_NAS_IP:3300`

##### Loki

- Expose `3100:3100`
- Use filesystem-backed storage under `/loki`
- Configure retention target of 90 days
- Keep the config home-lab friendly, not multi-node
- `auth_enabled: false`
- Reject logs older than 7 days unless there is a strong reason not to

##### Alloy

- Mount `/volume1/docker/adguard/work/data:/adguard-logs:ro`
- Expose `5514:5514/udp`
- Expose `12345:12345`
- Start with a valid `loki.write` output to Loki
- Include AdGuard ingestion in the initial delivered config
- Include raw UDM syslog ingestion in the initial delivered config

### Deliverable 2: AdGuard ingestion

The Alloy config must tail `/adguard-logs/querylog.json` and parse JSON lines.

#### AdGuard Alloy behaviour

- discover the file with `local.file_match`
- ingest it with `loki.source.file`
- parse JSON using `loki.process`
- set the event timestamp from `time` using `RFC3339Nano`
- add these labels only:
  - `job="adguard"`
  - `source="dns_querylog"`
  - `client`
  - `client_name`
  - `query_type`
  - `disallowed`
- keep `domain` in the output line
- if possible, place `domain`, `status`, `reason`, `upstream`, and `cached` into structured metadata, but do not fail the implementation if that feature is unavailable in the actual deployed version

#### Output line format

Use a human-readable single-line format similar to:

```text
<client> (<client_name>) -> <domain> [<query_type>] status=<status> reason=<reason> blocked=<disallowed> upstream=<upstream> cached=<cached>
```

If `client_name` is empty, the line should still remain readable.

### Deliverable 3: Raw UDM syslog ingestion

The Alloy config must also accept raw UDM syslog over UDP `5514`.

#### Initial UDM Alloy behaviour

- listen on `0.0.0.0:5514` over UDP
- apply only static labels:
  - `job="udm"`
  - `source="syslog"`
- forward raw message bodies to Loki unchanged

Do not attempt a parsing pipeline for action, category, IPs, ports, or hostnames in the initial delivery.

### Deliverable 4: Validation scripts and checks

Create shell scripts that help validate the deployment.

#### `scripts/validate-stack.sh`

Should check at least:
- Docker Compose services are up
- Grafana responds on port 3300
- Loki responds on `/ready`
- Alloy responds on port 12345
- Loki datasource is provisioned, or at minimum that Grafana is reachable and Loki is queryable

#### `scripts/tail-useful-logs.sh`

Should print:
- container status
- recent Grafana logs
- recent Loki logs
- recent Alloy logs

### Deliverable 5: Operations documentation

Create short but practical docs for:
- how to start the stack
- how to restart one service
- how to follow logs
- how to validate AdGuard ingestion
- how to test UDM syslog arrival
- where to paste a real UDM sample later

### Deliverable 6: Backups

Create `scripts/backup-log-viz.sh` that:
- backs up important configs and lightweight state to `/volume1/docker/log-viz/backups/<date>/`
- keeps only the last 7 backups
- includes at least:
  - `docker-compose.yml`
  - `.env` if present
  - `loki/config.yml`
  - `alloy/config.alloy`
  - Grafana provisioning files
  - Grafana sqlite database if present in the deployed version

Do not attempt to snapshot the whole Loki data directory in this first script.

---

## Non-goals for the first implementation

The IDE should explicitly avoid the following in the first pass:

- no Kubernetes
- no external database
- no reverse proxy
- no TLS termination
- no SSO
- no complex multi-stage UDM parser
- no use of `domain` as a Loki label
- no attempt to guarantee perfect DNS bypass detection
- no requirement to deliver Grafana dashboard JSON before real data has been validated

---

## Acceptance criteria

The work is considered ready for first deployment when all of the following are true.

### Stack health

- `docker compose up -d` succeeds
- Grafana opens on `http://<NAS_IP>:3300`
- Loki health endpoint responds at `http://<NAS_IP>:3100/ready`
- Alloy responds on `http://<NAS_IP>:12345`

### AdGuard ingestion

In Grafana Explore, these queries must work:

```logql
{job="adguard"}
{job="adguard", client="192.168.1.136"}
{job="adguard", disallowed="true"}
{job="adguard"} |= "youtube.com"
```

### UDM raw ingestion

After the UDM is pointed at the NAS syslog port, this query must return events:

```logql
{job="udm"}
```

### Usability

An operator must be able to answer:
- what domains did this device query today
- which queries were blocked
- did the UDM log anything interesting around the same time

---

## Step-by-step implementation order for the IDE

The IDE should work in this order and not skip ahead.

1. Create the directory structure
2. Create base Docker Compose and service configs
3. Add Grafana datasource provisioning
4. Add AdGuard file ingestion and parsing
5. Add raw UDM syslog ingestion only
6. Add validation scripts
7. Write README and docs
8. Provide deployment commands
9. Provide first-run validation commands
10. Stop and wait for a real UDM syslog sample before attempting any advanced UDM parser

---

## Technical notes and guardrails

### 1. Domain handling

The system needs to answer domain questions, but Loki stream count must stay under control.

Use this order of preference:
1. keep `domain` in the log line
2. add structured metadata if supported cleanly
3. only consider a `domain` label later after observing real stream count and memory usage

### 2. Device naming

`client_name` may be blank or inconsistent.

Do not assume it is always present or unique. The stable filter key is the client IP.

### 3. AdGuard rotation

AdGuard may rotate or compact `querylog.json`.

The implementation must rely on Alloy file tailing behaviour and must not depend on the file being append-only forever.

### 4. Loki retention

Set a 90-day target, but document that actual disk use must be measured after the stack is live.

### 5. UDM data reality

Some UDM flows or logs may show hostnames, some may show only IPs.

That is expected. Do not write documentation that implies the UDM can always produce domain history.

### 6. Version drift

The generated configs should be conservative and easy to adjust. Avoid exotic features unless required.

---

## Minimum operator commands to include in README

The README produced by the IDE should include at least these command patterns.

```bash
cd /volume1/docker/log-viz

docker compose up -d

docker compose ps

docker compose logs -f alloy

docker compose logs -f loki

docker compose logs -f grafana

curl http://127.0.0.1:3100/ready
curl http://127.0.0.1:12345/-/ready || true
```

The README should also explain how to adapt `127.0.0.1` to the NAS IP for browser checks.

---

## Follow-up work after first deployment

This is deliberately out of scope for the first pass, but should be listed in `docs/next-steps-udm-parser.md`.

### Later improvement 1: Real UDM parser

After capturing a real syslog sample, create a second pass that may extract low-cardinality labels such as:
- `act`
- `cat`

Only do this if the sample proves those fields are stable.

### Later improvement 2: Grafana dashboards

Do not build final dashboards until real data has been checked in Explore.

The first dashboard version should stay modest:
- top domains for selected device
- DNS query volume over time
- blocked DNS queries
- search for a domain across devices
- recent UDM raw events

### Later improvement 3: Alerting

Possible future alerts:
- large spike in blocked DNS queries
- one device generating unusual DNS volume
- UDM raw events matching specific suspicious patterns

---

## IDE kickoff prompt

This section can be copied directly into an IDE or coding agent.

```text
Build the first deployable version of the system described in this handoff.

Rules:
- Follow the locked design decisions exactly
- Do not use domain as a Loki label
- Do not guess the UDM syslog format
- Deliver raw UDM syslog ingestion only in v1
- Make the output practical for Synology Docker Compose deployment
- Generate all required files and scripts
- Keep the implementation conservative and easy to debug

Deliver:
1. docker-compose.yml
2. loki/config.yml
3. alloy/config.alloy
4. grafana/provisioning/datasources/loki.yml
5. .env.example
6. README.md
7. scripts/validate-stack.sh
8. scripts/tail-useful-logs.sh
9. scripts/backup-log-viz.sh
10. docs/deployment-notes.md
11. docs/validation-checklist.md
12. docs/next-steps-udm-parser.md

Then provide:
- the exact file contents
- the deployment commands
- the post-deploy validation steps
- any assumptions that still need operator input

Do not ask for a UDM syslog sample yet unless you are starting the advanced UDM parsing follow-up.
```

---

## Final note

This handoff is intentionally biased towards getting a reliable first deployment running, not towards producing the most ambitious dashboard on day one.

That is the correct trade-off here.
