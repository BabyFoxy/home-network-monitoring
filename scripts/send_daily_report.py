#!/usr/bin/env python3
"""
Daily Gaming Activity Report Generator
Queries Loki for gaming-related DNS activity and sends an HTML email report.
Run via: python3 send_daily_report.py
Schedule: Synology Task Scheduler — daily at ~07:00
"""

import os
import re
import sys
import json
import logging
import textwrap
import string
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import urllib.request
import urllib.error
import urllib.parse

# ── Timezone utilities (stdlib-only, no pytz/zoneinfo required) ────────────────
#
# Australia/Sydney UTC offsets:
#   AEST (standard): UTC+10  — active ~Apr-Sep
#   AEDT (daylight saving): UTC+11 — active ~Oct-Mar
# We detect the current offset from the system clock so DST transitions
# are handled automatically regardless of Python version.
#
# On Synology NAS the system TZ is already set to the local timezone,
# so datetime.now() gives correct local wall-clock time.
#
import time as _time

# Seconds east of UTC for the current system zone (negative = west of Greenwich)
_SYSTZ_OFFSET = -_time.timezone if _time.daylight == 0 else -_time.altzone


def _local_now():
    """Current local datetime using the system timezone."""
    return datetime.now()


def _midnight_local(date_obj):
    """Midnight (00:00) of the given date in the system timezone."""
    return datetime.combine(date_obj, datetime.min.time())


def _to_utc_ns(local_dt: datetime) -> int:
    """Convert a naive local datetime to UTC nanoseconds since epoch."""
    # local = UTC + offset_seconds
    offset_s = _SYSTZ_OFFSET
    utc_dt = local_dt - timedelta(seconds=offset_s)
    return int(utc_dt.timestamp() * 1e9)
import urllib.parse

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("daily_report")

# Ensure logs directory exists
(Path(__file__).parent.parent / "logs").mkdir(exist_ok=True)


# ── Config ──────────────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    val = os.environ.get(key, default)
    if not val:
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith(f"{key}="):
                    val = line.split("=", 1)[1].strip()
    return val


LOKI_URL          = _env("LOKI_URL", "http://192.168.1.5:3100")
SMTP_HOST         = _env("SMTP_HOST", "")
SMTP_PORT         = int(_env("SMTP_PORT", "587"))
SMTP_USERNAME     = _env("SMTP_USERNAME", "")
SMTP_PASSWORD     = _env("SMTP_PASSWORD", "")
SMTP_FROM         = _env("SMTP_FROM", "")
SMTP_TO          = _env("SMTP_TO", "")
SMTP_USE_TLS     = _env("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")
REPORT_TIMEZONE   = _env("REPORT_TIMEZONE", "UTC")
CHILD_DEVICES     = _env("CHILD_DEVICES", "")   # regex e.g. "Ethan PC|EthanR-PC"

# Optional: map raw device names to parent-friendly display names.
# Format: "raw_name=Display Name" separated by commas.
# Devices not listed here are shown as-is.
# Example in .env: DEVICE_DISPLAY_NAMES=MBP-S26226=Ethan PC,192.168.1.155=Living Room
_DEVICE_DISPLAY_RAW = _env("DEVICE_DISPLAY_NAMES", "")
DEVICE_DISPLAY_NAMES: dict = {}
if _DEVICE_DISPLAY_RAW:
    for entry in _DEVICE_DISPLAY_RAW.split(","):
        if "=" in entry:
            raw, display = entry.split("=", 1)
            DEVICE_DISPLAY_NAMES[raw.strip()] = display.strip()

def display_name(raw: str) -> str:
    return DEVICE_DISPLAY_NAMES.get(raw, raw)

# Gaming domain filter — must match the dashboard rules exactly
# Note: [.] matches a literal dot in LogQL RE2 regex; [[]] escapes [] in .format()
GAMING_PATTERNS = (
    "roblox|rbxcdn|rbxusercontent|bloxd[[.]]io|mojang|minecraft"
    "|crazygames|poki[[.]]com|now[[.]]gg|itch[[.]]io|lagged[[.]]com"
    "|gameflare|friv[[.]]com|y8[[.]]com|miniclip|kizi[[.]]com"
)
ENTERTAINMENT_PATTERNS = (
    "youtube[[.]]com|ytimg[[.]]com|googlevideo[[.]]com"
    "|discord[[.]]com|discord[[.]]gg|twitch[[.]]tv"
)


# ── Loki client ────────────────────────────────────────────────────────────────

class LokiClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def _strip_json_prefix(self, raw: bytes) -> dict:
        text = raw.decode("utf-8", errors="replace")
        # Loki may prefix JSON with log lines (chunked / protobuf headers)
        idx = text.find("{")
        if idx < 0:
            raise ValueError("No JSON found in Loki response")
        return json.loads(text[idx:])

    def query(self, expr: str) -> dict:
        log.debug("Loki query: %s", expr[:120])
        payload = f"query={urllib.parse.quote(expr)}".encode()
        try:
            req = urllib.request.Request(
                f"{self.base}/loki/api/v1/query",
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return self._strip_json_prefix(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read()[:500]
            raise RuntimeError(f"Loki HTTP {e.code}: {body}") from e
        except Exception as e:
            raise RuntimeError(f"Loki request failed: {e}") from e

    def query_range(self, expr: str, limit: int = 20,
                    start_ns: int = None, end_ns: int = None) -> list:
        now_ns = datetime.now(timezone.utc).timestamp() * 1e9
        if start_ns is None:
            start_ns = now_ns - (8640 * 1e9)
        if end_ns is None:
            end_ns = now_ns
        log.debug("Loki query_range: %s  [%s → %s]",
                  expr[:120], int(start_ns), int(end_ns))
        payload = urllib.parse.urlencode({
            "query": expr,
            "limit": limit,
            "start": int(start_ns),
            "end":   int(end_ns),
        }).encode()
        try:
            req = urllib.request.Request(
                f"{self.base}/loki/api/v1/query_range",
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = self._strip_json_prefix(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read()[:500]
            raise RuntimeError(f"Loki HTTP {e.code}: {body}") from e
        except Exception as e:
            raise RuntimeError(f"Loki query_range failed: {e}") from e

        results = data.get("data", {}).get("result", [])
        rows = []
        for stream in results:
            for ts_ns, line in stream.get("values", []):
                rows.append((float(ts_ns), line))
        rows.sort(key=lambda r: r[0], reverse=True)  # newest first
        return rows

    def query_instant(self, expr: str, time_ns: int = None) -> dict:
        """Instant query evaluated at an explicit UTC nanosecond timestamp."""
        if time_ns is None:
            time_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
        log.debug("Loki instant query at ns=%s: %s", int(time_ns), expr[:120])
        payload = f"query={urllib.parse.quote(expr)}&time={time_ns}".encode()
        try:
            req = urllib.request.Request(
                f"{self.base}/loki/api/v1/query",
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return self._strip_json_prefix(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read()[:500]
            raise RuntimeError(f"Loki HTTP {e.code}: {body}") from e
        except Exception as e:
            raise RuntimeError(f"Loki request failed: {e}") from e


# ── Data fetching ──────────────────────────────────────────────────────────────

def fetch_report_data(loki: LokiClient) -> dict:
    gaming = GAMING_PATTERNS
    entertainment = ENTERTAINMENT_PATTERNS
    child_re = CHILD_DEVICES or "."

    # ── Timezone-aware report date and query window ──────────────────────────
    # The report covers the previous full calendar day in the system timezone.
    # Note: Loki 3.x does not reliably handle instant queries with `time` in the
    # past (connection dropped). We anchor all instant queries to "now" and use
    # [24h] as the window — acceptable for a 07:00 daily report (covers
    # ~midnight–07:00 Sydney the previous day with minor edge-case bleed).
    local_now = _local_now()
    local_yesterday = local_now.date() - timedelta(days=1)
    report_date = local_yesterday.strftime("%Y-%m-%d")

    # For evidence rows (query_range), use midnight→now in UTC
    midnight_start = _midnight_local(local_yesterday)
    midnight_end   = _midnight_local(local_now.date())
    query_start_ns = _to_utc_ns(midnight_start)
    query_end_ns   = _to_utc_ns(midnight_end)  # used only for query_range

    log.info("Building report for %s (previous local calendar day)", report_date)

    # 1. Per-device gaming hit counts
    q_device_hits = (
        "sum by (client_name) (count_over_time("
        "{{job=\"adguard\", client_name=~\"{child_re}\"}}"
        " |~ \"{gaming}\" [24h]))"
    ).format(child_re=child_re, gaming=gaming)
    try:
        result = loki.query_instant(q_device_hits)
        device_hits = {}
        for s in result.get("data", {}).get("result", []):
            name = s["metric"].get("client_name", "?")
            device_hits[name] = int(float(s["value"][1]))
    except Exception as e:
        log.error("Failed to fetch per-device gaming hits: %s", e)
        device_hits = {}

    # 2. Per-device blocked gaming hits
    q_blocked = (
        "sum by (client_name) (count_over_time("
        "{{job=\"adguard\", client_name=~\"{child_re}\", reason=~\"[3-9]\"}}"
        " |~ \"{gaming}\" [24h]))"
    ).format(child_re=child_re, gaming=gaming)
    try:
        result = loki.query_instant(q_blocked)
        device_blocked = {}
        for s in result.get("data", {}).get("result", []):
            name = s["metric"].get("client_name", "?")
            device_blocked[name] = int(float(s["value"][1]))
    except Exception as e:
        log.error("Failed to fetch per-device blocked hits: %s", e)
        device_blocked = {}

    # 3. Top gaming domains (all devices, 24h)
    q_domains = (
        "sum by (domain) (count_over_time("
        "{{job=\"adguard\"}}"
        " |~ \"{gaming}\""
        " | regexp \"-> (?P<domain>[^ ]+)\" [24h]))"
    ).format(gaming=gaming)
    try:
        result = loki.query_instant(q_domains)
        domain_counts = {}
        for s in result.get("data", {}).get("result", []):
            d = s["metric"].get("domain", "?")
            domain_counts[d] = int(float(s["value"][1]))
        top_domains = dict(sorted(domain_counts.items(), key=lambda x: -x[1])[:10])
    except Exception as e:
        log.error("Failed to fetch top gaming domains: %s", e)
        top_domains = {}

    # 4. Active devices (for entertainment filtering)
    active_devices = [d for d, hits in device_hits.items() if hits > 0]
    active_devices_re = "|".join(re.escape(d) for d in active_devices) if active_devices else "NODEVICES"

    # 5. Per-device top domains
    device_domain_counts = {}
    for dev in active_devices:
        q = (
            "sum by (domain) (count_over_time("
            "{{job=\"adguard\", client_name=\"{dev}\"}}"
            " |~ \"{gaming}\""
            " | regexp \"-> (?P<domain>[^ ]+)\" [24h]))"
        ).format(dev=dev, gaming=gaming)
        try:
            result = loki.query_instant(q)
            counts = {}
            for s in result.get("data", {}).get("result", []):
                d = s["metric"].get("domain", "?")
                counts[d] = int(float(s["value"][1]))
            device_domain_counts[dev] = dict(sorted(counts.items(), key=lambda x: -x[1])[:5])
        except Exception as e:
            log.warning("Failed to fetch domains for %s: %s", dev, e)
            device_domain_counts[dev] = {}

    # 6. Total blocked gaming hits
    q_total_blocked = (
        "sum(count_over_time("
        "{{job=\"adguard\", reason=~\"[3-9]\"}}"
        " |~ \"{gaming}\" [24h]))"
    ).format(gaming=gaming)
    try:
        result = loki.query_instant(q_total_blocked)
        total_blocked = int(float(result["data"]["result"][0]["value"][1]))
    except Exception:
        total_blocked = 0

    # 7. Total gaming hits
    q_total = (
        "sum(count_over_time("
        "{{job=\"adguard\"}}"
        " |~ \"{gaming}\" [24h]))"
    ).format(gaming=gaming)
    try:
        result = loki.query_instant(q_total)
        total_hits = int(float(result["data"]["result"][0]["value"][1]))
    except Exception:
        total_hits = 0

    # 8. Recent blocked gaming evidence (within the report window)
    q_evidence = (
        "{{job=\"adguard\", reason=~\"[3-9]\"}}"
        " |~ \"{gaming}\""
        " | regexp \"-> (?P<domain>[^ ]+)\""
    ).format(gaming=gaming)
    try:
        evidence_rows = loki.query_range(
            q_evidence, limit=15,
            start_ns=query_start_ns, end_ns=query_end_ns,
        )
    except Exception as e:
        log.warning("Failed to fetch blocked evidence: %s", e)
        evidence_rows = []

    # 9. Recent entertainment (active devices only, within the report window)
    if active_devices_re != "NODEVICES":
        q_ent = (
            "{{job=\"adguard\", client_name=~\"{dev_re}\"}}"
            " |~ \"{entertainment}\""
            " | regexp \"-> (?P<domain>[^ ]+)\""
        ).format(dev_re=active_devices_re, entertainment=entertainment)
        try:
            entertainment_rows = loki.query_range(
                q_ent, limit=10,
                start_ns=query_start_ns, end_ns=query_end_ns,
            )
        except Exception as e:
            log.warning("Failed to fetch entertainment context: %s", e)
            entertainment_rows = []
    else:
        entertainment_rows = []

    # 10. Entertainment domain set for conclusion
    entertainment_domains = set()
    for _, line in entertainment_rows:
        m = re.search(r"-> ([^ ]+)", line)
        if m:
            entertainment_domains.add(m.group(1))
    entertainment_summary = ", ".join(sorted(entertainment_domains)) if entertainment_domains else "none observed"

    return {
        "report_date": report_date,
        "active_device_count": len(active_devices),
        "total_hits": total_hits,
        "total_blocked": total_blocked,
        "device_hits": device_hits,
        "device_blocked": device_blocked,
        "device_domain_counts": device_domain_counts,
        "top_domains": top_domains,
        "evidence_rows": evidence_rows,
        "entertainment_rows": entertainment_rows,
        "entertainment_summary": entertainment_summary,
    }


# ── Report reasoning ──────────────────────────────────────────────────────────

def make_note(device: str, hits: int, blocked: int) -> str:
    if hits == 0:
        return "No significant gaming-related activity detected today."
    if hits > 20:
        return f"Strong Roblox-related activity observed ({hits} hits)."
    if hits > 5:
        return f"Moderate gaming-related activity detected ({hits} hits)."
    return f"Limited gaming-related activity ({hits} hits)."


def make_conclusion(data: dict) -> str:
    active = data["active_device_count"]
    total = data["total_hits"]
    blocked = data["total_blocked"]
    domains = data["top_domains"]
    ent = data["entertainment_summary"]

    if active == 0:
        return (
            "No significant gaming-related activity was detected on "
            "any configured child devices today."
        )

    parts = []
    for dev, hits in sorted(data["device_hits"].items(), key=lambda x: -x[1]):
        if hits == 0:
            continue
        dev_blocked = data["device_blocked"].get(dev, 0)
        top_domains_str = ", ".join(f"{d} ({c})" for d, c in list(data["device_domain_counts"].get(dev, {}).items())[:3])
        if dev_blocked > 0:
            parts.append(
                f"{dev} showed gaming-related activity today ({hits} hits). "
                f"Most gaming-related DNS requests were blocked. "
                f"Top domains: {top_domains_str}."
            )
        else:
            parts.append(
                f"{dev} had gaming-related DNS activity ({hits} hits). "
                f"Top domains: {top_domains_str}."
            )

    conclusion = " ".join(parts)
    if ent != "none observed":
        conclusion += f" Entertainment-related activity was also observed: {ent}."
    return conclusion


# ── Data formatting helpers ───────────────────────────────────────────────────

def ts_to_local(ts_ns: float, tz_str: str = REPORT_TIMEZONE) -> str:
    """Convert a UTC nanosecond timestamp to local wall-clock time string."""
    dt_utc = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
    dt_local = dt_utc + timedelta(seconds=_SYSTZ_OFFSET)
    return dt_local.strftime("%Y-%m-%d %H:%M")

def parse_evidence_line(line: str) -> dict:
    """Parse a raw Loki log line into structured fields."""
    # Format: "client_name -> domain [query_type] ..."
    client_m = re.search(r"^([^ ]+)", line)
    domain_m = re.search(r"-> ([^ ]+)", line)
    type_m = re.search(r"\[([^\]]+)\]", line)
    reason_m = re.search(r"reason=([0-9]+|<no value>)", line)
    ts_m = re.search(r"^\[([0-9.]+)\]", line)

    device = client_m.group(1) if client_m else "?"
    domain = domain_m.group(1) if domain_m else "?"
    qt = type_m.group(1) if type_m else "?"
    reason = reason_m.group(1) if reason_m else "<no value>"
    is_blocked = reason not in ("<no value>", "0", "1", "2")

    return {
        "device": device,
        "domain": domain,
        "query_type": qt,
        "reason": reason,
        "status": "BLOCKED" if is_blocked else "ALLOWED",
    }


# ── Template rendering ─────────────────────────────────────────────────────────

_TEMPLATE_PATH = Path(__file__).parent.parent / "reports" / "daily_report_template.html"


def _load_template() -> string.Template:
    if not _TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Email template not found: {_TEMPLATE_PATH}. "
            "Ensure reports/daily_report_template.html is present."
        )
    return string.Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))


def _build_rows(data: dict) -> dict:
    tz = REPORT_TIMEZONE
    # Top domains summary
    top_str = ", ".join(
        f"{d} ({c})" for d, c in data["top_domains"].items()
    ) if data["top_domains"] else "none"

    # Per-device rows
    device_rows = []
    for dev, hits in sorted(data["device_hits"].items(), key=lambda x: -x[1]):
        blocked = data["device_blocked"].get(dev, 0)
        note = make_note(dev, hits, blocked)
        domains_str = ", ".join(
            f"{d} ({c})"
            for d, c in list(data["device_domain_counts"].get(dev, {}).items())
        ) if data["device_domain_counts"].get(dev) else "—"
        ent_overlap = data["entertainment_summary"] if hits > 0 else "—"
        active_class = "" if hits > 0 else " class=\"inactive\""
        device_rows.append(
            f"<tr{active_class}>"
            f"<td>{display_name(dev)}</td>"
            f"<td>{hits}</td>"
            f"<td>{blocked}</td>"
            f"<td>{domains_str}</td>"
            f"<td>{ent_overlap}</td>"
            f"<td>{note}</td>"
            f"</tr>"
        )

    # Evidence rows
    evidence_rows = []
    for ts, line in data["evidence_rows"][:10]:
        parsed = parse_evidence_line(line)
        evidence_rows.append(
            f"<tr>"
            f"<td>{ts_to_local(ts, tz)}</td>"
            f"<td>{display_name(parsed['device'])}</td>"
            f"<td>{parsed['domain']}</td>"
            f"<td>{parsed['query_type']}</td>"
            f"<td class=\"blocked\">{parsed['status']}</td>"
            f"</tr>"
        )

    # Entertainment rows
    ent_rows = []
    for ts, line in data["entertainment_rows"][:8]:
        parsed = parse_evidence_line(line)
        status_cls = "blocked" if parsed["status"] == "BLOCKED" else "allowed"
        ent_rows.append(
            f"<tr>"
            f"<td>{ts_to_local(ts, tz)}</td>"
            f"<td>{display_name(parsed['device'])}</td>"
            f"<td>{parsed['domain']}</td>"
            f"<td>{parsed['query_type']}</td>"
            f"<td class=\"{status_cls}\">{parsed['status']}</td>"
            f"</tr>"
        )

    return {
        "report_date": data["report_date"],
        "active_device_count": data["active_device_count"],
        "total_hits": data["total_hits"],
        "total_blocked": data["total_blocked"],
        "top_domains_summary": top_str,
        "device_rows_html": "".join(device_rows) if device_rows else (
            '<tr><td colspan="6" class="no-activity">'
            "No configured child devices had gaming-related activity today."
            "</td></tr>"
        ),
        "evidence_rows_html": "".join(evidence_rows) if evidence_rows else (
            '<tr><td colspan="5" class="no-activity">'
            "No blocked gaming evidence in the past 24 hours."
            "</td></tr>"
        ),
        "ent_rows_html": "".join(ent_rows) if ent_rows else (
            '<tr><td colspan="5" class="no-activity">'
            "No entertainment-related DNS activity observed for child devices today."
            "</td></tr>"
        ),
        "conclusion": make_conclusion(data),
    }


def render_html(data: dict) -> str:
    template = _load_template()
    return template.substitute(_build_rows(data))


def render_text(data: dict) -> str:
    tz = REPORT_TIMEZONE
    report_date = data["report_date"]
    top_str = ", ".join(f"{d} ({c})" for d, c in data["top_domains"].items()) if data["top_domains"] else "none"
    conclusion = make_conclusion(data)

    lines = [
        f"Home network gaming report — {report_date}",
        "=" * 50,
        "",
        "SUMMARY",
        f"  Devices with gaming-related activity: {data['active_device_count']}",
        f"  Total gaming DNS hits:             {data['total_hits']}",
        f"  Blocked gaming DNS hits:            {data['total_blocked']}",
        f"  Top gaming domains:                 {top_str}",
        "",
        "PER DEVICE",
    ]

    for dev, hits in sorted(data["device_hits"].items(), key=lambda x: -x[1]):
        blocked = data["device_blocked"].get(dev, 0)
        note = make_note(dev, hits, blocked)
        domains_str = ", ".join(
            f"{d} ({c})" for d, c in list(data["device_domain_counts"].get(dev, {}).items())
        ) or "—"
        ent = data["entertainment_summary"] if hits > 0 else "—"
        lines.append(f"  {dev}")
        lines.append(f"    Gaming hits: {hits}  |  Blocked: {blocked}")
        lines.append(f"    Top domains: {domains_str}")
        lines.append(f"    Entertainment: {ent}")
        lines.append(f"    Note: {note}")
        lines.append("")

    lines.extend([
        "RECENT BLOCKED GAMING EVIDENCE",
    ])
    if data["evidence_rows"]:
        for ts, line in data["evidence_rows"][:10]:
            parsed = parse_evidence_line(line)
            lines.append(
                f"  {ts_to_local(ts, tz)}  |  {parsed['device']}  |  "
                f"{parsed['domain']}  |  {parsed['query_type']}  |  BLOCKED"
            )
    else:
        lines.append("  No blocked gaming evidence in the past 24 hours.")

    lines.extend(["", "RECENT ENTERTAINMENT CONTEXT"])
    if data["entertainment_rows"]:
        for ts, line in data["entertainment_rows"][:8]:
            parsed = parse_evidence_line(line)
            lines.append(
                f"  {ts_to_local(ts, tz)}  |  {parsed['device']}  |  "
                f"{parsed['domain']}  |  {parsed['query_type']}  |  {parsed['status']}"
            )
    else:
        lines.append("  No entertainment-related DNS activity observed for child devices today.")

    lines.extend([
        "",
        "CONCLUSION",
        f"  {conclusion}",
        "",
        "NOTES",
        "  - This report is based on DNS and network activity evidence.",
        "  - It can strongly suggest gaming-related behaviour, but it is not proof of exact gameplay duration.",
        "  - Repeated hits to Roblox, bloxd.io, and similar domains are stronger indicators than isolated single requests.",
        "  - Blocked gaming DNS requests indicate that parental controls are working as configured.",
    ])

    return "\n".join(lines)


# ── Email sending ─────────────────────────────────────────────────────────────

def send_email(html_body: str, text_body: str, report_date: str):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    if not all([SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM, SMTP_TO]):
        raise RuntimeError(
            "SMTP config incomplete: check SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, "
            "SMTP_FROM, SMTP_TO in .env"
        )

    recipients = [r.strip() for r in SMTP_TO.split(",") if r.strip()]
    subject = f"Home network gaming report — {report_date}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(recipients)

    part_text = MIMEText(text_body, "plain", "utf-8")
    part_html = MIMEText(html_body, "html", "utf-8")
    msg.attach(part_text)
    msg.attach(part_html)

    log.info("Connecting to SMTP %s:%d...", SMTP_HOST, SMTP_PORT)
    if SMTP_USE_TLS:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, recipients, msg.as_string())
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, recipients, msg.as_string())

    log.info("Report sent to %s", recipients)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("Starting daily gaming activity report")

    if not LOKI_URL:
        log.error("LOKI_URL not set")
        sys.exit(1)

    loki = LokiClient(LOKI_URL)

    # Verify Loki is reachable
    try:
        loki.query("count_over_time({job=\"adguard\"}[1m]) > 0")
        log.info("Loki connection OK")
    except Exception as e:
        log.error("Cannot connect to Loki at %s: %s", LOKI_URL, e)
        sys.exit(2)

    log.info("Fetching report data from Loki...")
    try:
        data = fetch_report_data(loki)
    except Exception as e:
        log.error("Data fetch failed: %s", e)
        sys.exit(3)

    log.info("Rendering report...")
    html = render_html(data)
    text = render_text(data)

    if SMTP_HOST:
        log.info("Sending email...")
        try:
            send_email(html, text, data["report_date"])
            log.info("Report sent successfully")
        except Exception as e:
            log.error("Email send failed: %s", e)
            sys.exit(4)
    else:
        # No SMTP configured — write report to stdout
        log.warning("SMTP not configured; printing report to stdout")
        print(text)

    log.info("Done")


if __name__ == "__main__":
    main()
