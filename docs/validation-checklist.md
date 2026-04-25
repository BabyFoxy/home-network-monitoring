# Validation checklist — first deployment

Work through this list top to bottom. All items must pass before the stack is considered operational.

## Stack health

- [ ] `docker compose up -d` exits without error
- [ ] `docker compose ps` shows all three services as `running`
- [ ] `curl http://NAS_IP:3100/ready` returns `ready`
- [ ] `curl http://NAS_IP:12345/-/ready` responds
- [ ] Grafana opens at `http://NAS_IP:3300`
- [ ] Login with admin / your GRAFANA_ADMIN_PASSWORD works

## Loki datasource

- [ ] In Grafana → Connections → Data sources → Loki shows green (provisioned automatically)
- [ ] "Test" button on the Loki datasource returns success

## AdGuard ingestion

- [ ] `{job="adguard"}` in Grafana Explore returns log lines
- [ ] Log lines match the format: `<IP> (<name>) -> <domain> [<type>] status=...`
- [ ] `{job="adguard", client="192.168.1.136"}` filters by a single device
- [ ] `{job="adguard", disallowed="true"}` returns blocked queries (if any are blocked)
- [ ] `{job="adguard"} |= "youtube.com"` returns hits for that domain

## UDM syslog

- [ ] UDM SE is configured to send syslog to NAS_IP:5514 UDP
- [ ] `{job="udm"}` in Grafana Explore returns raw syslog lines
- [ ] Raw UDM message bodies are preserved and readable

## Usability

- [ ] Can answer: what domains did device X query in the last hour?
- [ ] Can answer: which queries from device X were blocked today?
- [ ] Can find a specific domain across all devices with `|= "domain.com"`

## Backup

- [ ] The backup helper runs without error
- [ ] Backup appears in `/volume1/docker/home-network-monitoring/backups/`
