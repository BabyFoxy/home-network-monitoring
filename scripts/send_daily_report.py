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
import string
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import urllib.request
import urllib.error
import urllib.parse
import time as _time

# ── Timezone ────────────────────────────────────────────────────────────────────
# On Synology NAS, datetime.now() gives correct local wall-clock time.
# datetime.timestamp() on a naive datetime already converts using the system
# timezone — do NOT manually subtract the offset or it will be applied twice.

def _local_now() -> datetime:
    return datetime.now()

def _midnight_local(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time())

def _to_utc_ns(local_dt: datetime) -> int:
    """Convert a naive local datetime to UTC nanoseconds.
    datetime.timestamp() uses the system local timezone automatically —
    no manual offset arithmetic needed.
    """
    return int(local_dt.timestamp() * 1_000_000_000)


# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("daily_report")

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


LOKI_URL       = _env("LOKI_URL", "http://192.168.1.5:3100")
SMTP_HOST      = _env("SMTP_HOST", "")
SMTP_PORT      = int(_env("SMTP_PORT", "587"))
SMTP_USERNAME  = _env("SMTP_USERNAME", "")
SMTP_PASSWORD  = _env("SMTP_PASSWORD", "")
SMTP_FROM      = _env("SMTP_FROM", "")
SMTP_TO        = _env("SMTP_TO", "")
SMTP_USE_TLS   = _env("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")
# Devices to EXCLUDE from monitoring (Fox Devices group + David iPhone)
# Override in .env as pipe-separated IPs/names: EXCLUDE_DEVICES=192.168.1.1|192.168.1.3|...
_DEFAULT_EXCLUDE = (
    "192[.]168[.]1[.]1$|192[.]168[.]1[.]3|192[.]168[.]1[.]5$|192[.]168[.]1[.]6$|"
    "192[.]168[.]1[.]14$|192[.]168[.]1[.]16$|192[.]168[.]1[.]17$|192[.]168[.]1[.]18$|"
    "192[.]168[.]1[.]101$|192[.]168[.]1[.]250$|192[.]168[.]1[.]251$"
)
EXCLUDE_DEVICES = _env("EXCLUDE_DEVICES", _DEFAULT_EXCLUDE)

_DEVICE_DISPLAY_RAW = _env("DEVICE_DISPLAY_NAMES", "")
DEVICE_DISPLAY_NAMES: dict = {}
if _DEVICE_DISPLAY_RAW:
    for entry in _DEVICE_DISPLAY_RAW.split(","):
        if "=" in entry:
            raw, display = entry.split("=", 1)
            DEVICE_DISPLAY_NAMES[raw.strip()] = display.strip()

def display_name(raw: str) -> str:
    return DEVICE_DISPLAY_NAMES.get(raw, raw)


# ── Domain patterns ─────────────────────────────────────────────────────────────
# Use [.] (not \.) — Loki's RE2 engine rejects backslash-dot.
# Do NOT use [[.]] — that is only relevant for Python str.format() brace escaping
# and is malformed in LogQL regex.

GAMING_PATTERNS = (
    "roblox|rbxcdn|rbxusercontent|bloxd[.]io|mojang|minecraft"
    "|crazygames|poki[.]com|now[.]gg|itch[.]io|lagged[.]com"
    "|gameflare|friv[.]com|y8[.]com|miniclip|kizi[.]com"
)
ENTERTAINMENT_PATTERNS = (
    "youtube[.]com|ytimg[.]com|googlevideo[.]com"
    "|discord[.]com|discord[.]gg|discordapp[.]com|twitch[.]tv"
)


# ── Loki client ────────────────────────────────────────────────────────────────

class LokiClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def _parse(self, raw: bytes) -> dict:
        text = raw.decode("utf-8", errors="replace")
        idx = text.find("{")
        if idx < 0:
            raise ValueError("No JSON in Loki response")
        return json.loads(text[idx:])

    def metric_instant(self, expr: str, at_ns: int) -> list:
        """Run an instant metric query at a specific UTC nanosecond timestamp.
        Returns list of {metric: {labels}, value: [ts, value_str]} dicts.
        """
        log.debug("metric_instant: %s", expr[:120])
        url = f"{self.base}/loki/api/v1/query?" + urllib.parse.urlencode({
            "query": expr,
            "time":  int(at_ns / 1e9),
        })
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                data = self._parse(r.read())
            return data.get("data", {}).get("result", [])
        except urllib.error.HTTPError as e:
            body = e.read()[:500]
            raise RuntimeError(f"Loki HTTP {e.code}: {body}") from e
        except Exception as e:
            raise RuntimeError(f"Loki metric_instant failed: {e}") from e

    def query_range(self, expr: str, limit: int = 50,
                    start_ns: int = None, end_ns: int = None) -> list:
        """Fetch log lines. Returns list of (ts_ns_float, line_str) tuples."""
        now_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
        if start_ns is None:
            start_ns = now_ns - 86_400 * 1_000_000_000
        if end_ns is None:
            end_ns = now_ns
        log.debug("query_range limit=%d: %s", limit, expr[:120])
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
            with urllib.request.urlopen(req, timeout=120) as r:
                data = self._parse(r.read())
        except urllib.error.HTTPError as e:
            body = e.read()[:500]
            raise RuntimeError(f"Loki HTTP {e.code}: {body}") from e
        except Exception as e:
            raise RuntimeError(f"Loki query_range failed: {e}") from e

        rows = []
        for stream in data.get("data", {}).get("result", []):
            for ts_ns, line in stream.get("values", []):
                rows.append((float(ts_ns), line))
        rows.sort(key=lambda r: r[0], reverse=True)
        return rows


# ── Data fetching ────────────────────────────────────────────────────────────────

def fetch_report_data(loki: LokiClient) -> dict:
    gaming        = GAMING_PATTERNS
    entertainment = ENTERTAINMENT_PATTERNS
    exclude_re    = EXCLUDE_DEVICES

    local_now       = _local_now()
    report_date     = (local_now - timedelta(hours=24)).strftime("%Y-%m-%d")

    end_ns   = _to_utc_ns(local_now)
    start_ns = end_ns - int(24 * 3600 * 1e9)

    log.info("Report for %s  window: last 24h ending %s (local)", report_date, local_now)
    log.info("UTC window: %s → %s",
             datetime.fromtimestamp(start_ns/1e9, tz=timezone.utc),
             datetime.fromtimestamp(end_ns/1e9, tz=timezone.utc))

    duration_s = int((end_ns - start_ns) / 1e9)
    dur = f"{duration_s}s"

    # ── True total counts via metric queries (not limited by query line cap) ────
    def safe_count(expr: str) -> int:
        try:
            result = loki.metric_instant(expr, at_ns=end_ns)
            if result:
                return int(float(result[0]["value"][1]))
            return 0
        except Exception as e:
            log.warning("Count query failed (%s): %s", expr[:60], e)
            return -1  # -1 = unknown

    total_hits = safe_count(
        f'sum(count_over_time({{job="adguard"}} |~ "{gaming}" [{dur}]))'
    )
    total_blocked = safe_count(
        f'sum(count_over_time({{job="adguard", reason=~"[3-9]"}} |~ "{gaming}" [{dur}]))'
    )

    # ── Per-device gaming hit counts via metric query (all devices) ─────────────
    try:
        dev_result = loki.metric_instant(
            f'sum by (client_name) (count_over_time({{job="adguard"}} |~ "{gaming}" [{dur}]))',
            at_ns=end_ns,
        )
        device_hits_all = {
            r["metric"].get("client_name", "(unknown)"): int(float(r["value"][1]))
            for r in dev_result
        }
    except Exception as e:
        log.warning("Per-device gaming count failed: %s", e)
        device_hits_all = {}

    # Filter to child devices if configured; fall back to all if nothing matches.
    device_hits = {d: h for d, h in device_hits_all.items() if not re.search(exclude_re, d)}
    unattributed = False

    # ── Per-device blocked counts ────────────────────────────────────────────────
    try:
        blocked_result = loki.metric_instant(
            f'sum by (client_name) (count_over_time({{job="adguard", reason=~"[3-9]"}} |~ "{gaming}" [{dur}]))',
            at_ns=end_ns,
        )
        device_blocked = {
            r["metric"].get("client_name", "(unknown)"): int(float(r["value"][1]))
            for r in blocked_result
            if r["metric"].get("client_name", "(unknown)") in device_hits
        }
    except Exception as e:
        log.warning("Per-device blocked count failed: %s", e)
        device_blocked = {}

    # ── Top domains globally via metric + regexp extraction ──────────────────────
    try:
        dom_result = loki.metric_instant(
            f'topk(10, sum by (domain) (count_over_time({{job="adguard"}} |~ "{gaming}" | regexp "(?:->|→) (?P<domain>[^ ]+)" [{dur}])))',
            at_ns=end_ns,
        )
        top_domains = {
            r["metric"].get("domain", "?"): int(float(r["value"][1]))
            for r in dom_result
        }
        top_domains = dict(sorted(top_domains.items(), key=lambda x: -x[1]))
    except Exception as e:
        log.warning("Top domains query failed: %s", e)
        top_domains = {}

    # ── Per-device top domains ───────────────────────────────────────────────────
    device_domain_counts: dict = {}
    for dev in device_hits:
        try:
            r2 = loki.metric_instant(
                f'topk(5, sum by (domain) (count_over_time({{job="adguard", client_name="{dev}"}} |~ "{gaming}" | regexp "(?:->|→) (?P<domain>[^ ]+)" [{dur}])))',
                at_ns=end_ns,
            )
            device_domain_counts[dev] = dict(sorted(
                {x["metric"].get("domain", "?"): int(float(x["value"][1])) for x in r2}.items(),
                key=lambda x: -x[1],
            ))
        except Exception as e:
            log.warning("Per-device domain query failed for %s: %s", dev, e)

    # ── Recent evidence rows (gaming — all, not just blocked) ───────────────────
    try:
        evidence_rows = loki.query_range(
            f'{{job="adguard"}} |~ "{gaming}"',
            limit=20, start_ns=start_ns, end_ns=end_ns,
        )
    except Exception as e:
        log.warning("Evidence query failed: %s", e)
        evidence_rows = []

    # ── Entertainment context (active devices only) ──────────────────────────────
    def _re2(s: str) -> str:
        # Escape RE2 metacharacters but NOT spaces — re.escape escapes spaces
        # as '\ ' which Loki's RE2 parser rejects.
        return re.sub(r'([.+*?()\[\]{}^$|\\])', r'\\\1', s)

    active_re = "|".join(_re2(d) for d in device_hits) if device_hits else None
    if active_re:
        try:
            entertainment_rows = loki.query_range(
                f'{{job="adguard", client_name=~"{active_re}"}} |~ "{entertainment}"',
                limit=15, start_ns=start_ns, end_ns=end_ns,
            )
        except Exception as e:
            log.warning("Entertainment query failed: %s", e)
            entertainment_rows = []
    else:
        entertainment_rows = []

    entertainment_domains = set()
    for _, line in entertainment_rows:
        m = re.search(r"(?:->|→) ([^ ]+)", line)
        if m:
            entertainment_domains.add(m.group(1))
    entertainment_summary = (
        ", ".join(sorted(entertainment_domains)) if entertainment_domains else "none observed"
    )

    return {
        "report_date":           report_date,
        "active_device_count":   len(device_hits),
        "total_hits":            total_hits,
        "total_blocked":         total_blocked,
        "device_hits":           device_hits,
        "device_blocked":        device_blocked,
        "device_domain_counts":  device_domain_counts,
        "top_domains":           top_domains,
        "evidence_rows":         evidence_rows,
        "entertainment_rows":    entertainment_rows,
        "entertainment_summary": entertainment_summary,
        "unattributed":          unattributed,
    }


# ── Report reasoning ──────────────────────────────────────────────────────────

def make_note(device: str, hits: int, blocked: int) -> str:
    if hits == 0:
        return "No gaming-related activity detected."
    allowed = hits - blocked
    if blocked == hits:
        return f"All {hits} gaming-related DNS requests were blocked by parental controls."
    if blocked > 0:
        return f"{hits} gaming DNS hits detected — {blocked} blocked, {allowed} allowed through."
    if hits > 50:
        return f"High gaming-related activity ({hits} DNS hits). Review recommended."
    if hits > 10:
        return f"Moderate gaming-related activity ({hits} DNS hits)."
    return f"Low gaming-related activity ({hits} DNS hits)."


def make_conclusion(data: dict) -> str:
    total   = data["total_hits"]
    blocked = data["total_blocked"]
    active  = data["active_device_count"]
    unattr  = data.get("unattributed", False)

    # No data at all
    if total <= 0:
        return "No gaming-related DNS activity was detected in the reporting window."

    # Activity exists but unknown count (query failed)
    if total == -1:
        total_str = "an unknown number of"
    else:
        total_str = str(total)

    parts = []

    # Unattributed fallback
    if unattr:
        parts.append(
            f"Gaming-related DNS activity was detected ({total_str} queries total), "
            "however no gaming activity was detected for monitored devices."
            "The activity below is reported across all devices as a fallback. "
            ""
        )
    elif active == 0:
        # total > 0 but no per-device attribution at all
        parts.append(
            f"Gaming-related DNS activity was detected ({total_str} queries total), "
            "but could not be attributed to any specific device. "
            "This may indicate the device name enrichment is not yet applied to historical logs."
        )
    else:
        for dev, hits in sorted(data["device_hits"].items(), key=lambda x: -x[1]):
            if hits == 0:
                continue
            dev_blocked = data["device_blocked"].get(dev, 0)
            top_doms = ", ".join(
                f"{d} ({c})" for d, c in list(data["device_domain_counts"].get(dev, {}).items())[:3]
            ) or "unknown"
            parts.append(make_note(dev, hits, dev_blocked) + f" Top domains: {top_doms}.")

    if blocked > 0 and not unattr and active > 0:
        parts.append(
            f"{blocked} of {total_str} gaming DNS requests were blocked by parental controls."
        )

    ent = data.get("entertainment_summary", "none observed")
    if ent != "none observed":
        parts.append(f"Entertainment-related activity was also observed: {ent}.")

    return " ".join(parts)


# ── Formatting helpers ─────────────────────────────────────────────────────────

def ts_to_local(ts_ns: float) -> str:
    dt_utc = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
    # Convert to local system time
    offset_s = -_time.altzone if _time.localtime().tm_isdst else -_time.timezone
    dt_local = dt_utc + timedelta(seconds=offset_s)
    return dt_local.strftime("%H:%M")   # time-only for mobile compactness


def parse_log_line(line: str) -> dict:
    """Parse a Loki log line: 'Client Name (IP) -> domain.com [TYPE] cat=X reason=N ...'"""
    # Full client name is everything up to the first " ("
    device_m = re.search(r"^(.+?) \(", line)
    domain_m = re.search(r"(?:->|→) ([^ ]+)", line)
    type_m   = re.search(r"\[([A-Z]+)\]", line)
    reason_m = re.search(r"reason=([0-9]+|<no value>)", line)

    device = device_m.group(1) if device_m else line.split()[0] if line else "?"
    domain = domain_m.group(1) if domain_m else "?"
    qt     = type_m.group(1)   if type_m   else "?"
    reason = reason_m.group(1) if reason_m else "0"
    blocked = reason not in ("<no value>", "0", "1", "2")

    return {
        "device":      device,
        "domain":      domain,
        "query_type":  qt,
        "reason":      reason,
        "blocked":     blocked,
        "status":      "BLOCKED" if blocked else "allowed",
        "status_class": "blocked" if blocked else "allowed",
    }


# ── Template rendering ─────────────────────────────────────────────────────────

_TEMPLATE_PATH = Path(__file__).parent.parent / "reports" / "daily_report_template.html"


def _load_template() -> string.Template:
    if not _TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template not found: {_TEMPLATE_PATH}")
    return string.Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))


def _build_substitutions(data: dict) -> dict:
    total   = data["total_hits"]
    blocked = data["total_blocked"]
    active  = data["active_device_count"]
    unattr  = data.get("unattributed", False)

    total_display   = str(total)   if total   >= 0 else "unknown"
    blocked_display = str(blocked) if blocked >= 0 else "unknown"

    # Top domains summary (text)
    top_str = ", ".join(f"{d} ({c})" for d, c in data["top_domains"].items()) or "none detected"

    # Attribution warning banner (shown only when needed)
    if unattr:
        attribution_html = (
            '<div class="warn-box">'
            "<strong>Attribution note:</strong> Gaming-related activity was detected but could not be "
            "matched to the configured child device filter. Showing all active devices as fallback. "
            ""
            "</div>"
        )
    elif active == 0 and total > 0:
        attribution_html = (
            '<div class="warn-box">'
            "<strong>Attribution note:</strong> Gaming-related DNS activity was detected, "
            "but could not be attributed to any specific device. "
            "Device name enrichment may not yet be applied to yesterday's logs."
            "</div>"
        )
    else:
        attribution_html = ""

    # Per-device cards (mobile-friendly stacked layout)
    device_cards = []
    for dev, hits in sorted(data["device_hits"].items(), key=lambda x: -x[1]):
        dev_blocked = data["device_blocked"].get(dev, 0)
        note = make_note(dev, hits, dev_blocked)
        domains_html = ""
        for d, c in list(data["device_domain_counts"].get(dev, {}).items()):
            domains_html += f'<span class="domain-tag">{d} ({c})</span> '
        if not domains_html:
            domains_html = '<span class="muted">no domain data</span>'
        pct_blocked = f"{int(dev_blocked/hits*100)}%" if hits > 0 else "0%"
        alert_class = "card-alert" if (hits - dev_blocked) > 0 else "card-ok"
        device_cards.append(
            f'<div class="device-card {alert_class}">'
            f'<div class="card-header">{display_name(dev)}</div>'
            f'<div class="card-row"><span class="card-label">Gaming hits</span>'
            f'<span class="card-value">{hits}</span></div>'
            f'<div class="card-row"><span class="card-label">Blocked</span>'
            f'<span class="card-value blocked-val">{dev_blocked} ({pct_blocked})</span></div>'
            f'<div class="card-row"><span class="card-label">Top domains</span></div>'
            f'<div class="domain-list">{domains_html}</div>'
            f'<div class="card-note">{note}</div>'
            f"</div>"
        )

    if not device_cards:
        device_cards.append(
            '<div class="device-card card-ok">'
            '<div class="card-note muted">No gaming activity matched to any device.</div>'
            "</div>"
        )

    # Evidence items (mobile-friendly vertical layout)
    evidence_items = []
    for ts, line in data["evidence_rows"][:15]:
        p = parse_log_line(line)
        evidence_items.append(
            '<div class="evidence-item">'
            f'<div class="ev-row"><span class="ev-label">Time</span>'
            f'<span class="ev-val">{ts_to_local(ts)}</span></div>'
            f'<div class="ev-row"><span class="ev-label">Device</span>'
            f'<span class="ev-val">{display_name(p["device"])}</span></div>'
            f'<div class="ev-row"><span class="ev-label">Domain</span>'
            f'<span class="ev-val domain-text">{p["domain"]}</span></div>'
            f'<div class="ev-row"><span class="ev-label">Type</span>'
            f'<span class="ev-val">{p["query_type"]}</span></div>'
            f'<div class="ev-row"><span class="ev-label">Status</span>'
            f'<span class="ev-val {p["status_class"]}">{p["status"].upper()}</span></div>'
            "</div>"
        )
    if not evidence_items:
        evidence_items.append(
            '<div class="evidence-item muted-block">'
            "No gaming DNS activity found in the report window."
            "</div>"
        )

    # Entertainment items
    ent_items = []
    for ts, line in data["entertainment_rows"][:10]:
        p = parse_log_line(line)
        ent_items.append(
            '<div class="evidence-item">'
            f'<div class="ev-row"><span class="ev-label">Time</span>'
            f'<span class="ev-val">{ts_to_local(ts)}</span></div>'
            f'<div class="ev-row"><span class="ev-label">Device</span>'
            f'<span class="ev-val">{display_name(p["device"])}</span></div>'
            f'<div class="ev-row"><span class="ev-label">Domain</span>'
            f'<span class="ev-val domain-text">{p["domain"]}</span></div>'
            f'<div class="ev-row"><span class="ev-label">Status</span>'
            f'<span class="ev-val {p["status_class"]}">{p["status"].upper()}</span></div>'
            "</div>"
        )
    if not ent_items:
        ent_items.append(
            '<div class="evidence-item muted-block">'
            "No entertainment DNS activity observed for active devices."
            "</div>"
        )

    return {
        "report_date":         data["report_date"],
        "active_device_count": active,
        "total_hits":          total_display,
        "total_blocked":       blocked_display,
        "top_domains_summary": top_str,
        "attribution_html":    attribution_html,
        "device_cards_html":   "\n".join(device_cards),
        "evidence_items_html": "\n".join(evidence_items),
        "ent_items_html":      "\n".join(ent_items),
        "conclusion":          make_conclusion(data),
    }


def render_html(data: dict) -> str:
    return _load_template().substitute(_build_substitutions(data))


def render_text(data: dict) -> str:
    total   = data["total_hits"]
    blocked = data["total_blocked"]
    top_str = ", ".join(f"{d} ({c})" for d, c in data["top_domains"].items()) or "none"

    lines = [
        f"Home network gaming report — {data['report_date']}",
        "=" * 50,
        "",
        "SUMMARY",
        f"  Devices with gaming activity : {data['active_device_count']}",
        f"  Total gaming DNS hits        : {total if total >= 0 else 'unknown'}",
        f"  Blocked gaming DNS hits      : {blocked if blocked >= 0 else 'unknown'}",
        f"  Top gaming domains           : {top_str}",
        "",
    ]

    if data.get("unattributed"):
        lines.append("  WARNING: unattributed fallback active.")
        lines.append("")

    lines.append("PER DEVICE")
    for dev, hits in sorted(data["device_hits"].items(), key=lambda x: -x[1]):
        dev_blocked = data["device_blocked"].get(dev, 0)
        domains_str = ", ".join(
            f"{d} ({c})" for d, c in list(data["device_domain_counts"].get(dev, {}).items())
        ) or "—"
        lines += [
            f"  {display_name(dev)}",
            f"    Gaming hits : {hits}  |  Blocked : {dev_blocked}",
            f"    Top domains : {domains_str}",
            f"    Note        : {make_note(dev, hits, dev_blocked)}",
            "",
        ]

    lines.append("RECENT GAMING EVIDENCE")
    if data["evidence_rows"]:
        for ts, line in data["evidence_rows"][:15]:
            p = parse_log_line(line)
            lines.append(
                f"  {ts_to_local(ts)}  {display_name(p['device'])}  "
                f"{p['domain']}  [{p['query_type']}]  {p['status'].upper()}"
            )
    else:
        lines.append("  No gaming evidence in the report window.")

    lines += ["", "RECENT ENTERTAINMENT CONTEXT"]
    if data["entertainment_rows"]:
        for ts, line in data["entertainment_rows"][:10]:
            p = parse_log_line(line)
            lines.append(
                f"  {ts_to_local(ts)}  {display_name(p['device'])}  "
                f"{p['domain']}  [{p['query_type']}]  {p['status'].upper()}"
            )
    else:
        lines.append("  No entertainment activity for active devices.")

    lines += [
        "",
        "CONCLUSION",
        f"  {make_conclusion(data)}",
        "",
        "NOTES",
        "  DNS evidence strongly suggests gaming-related behaviour but does not prove gameplay duration.",
        "  Repeated hits to Roblox, bloxd.io, and similar — especially in sustained bursts — are stronger indicators.",
        "  Blocked gaming DNS requests indicate parental controls are working.",
    ]
    return "\n".join(lines)


# ── Email sending ─────────────────────────────────────────────────────────────

def send_email(html_body: str, text_body: str, report_date: str):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    if not all([SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM, SMTP_TO]):
        raise RuntimeError("SMTP config incomplete — check SMTP_HOST/USERNAME/PASSWORD/FROM/TO in .env")

    recipients = [r.strip() for r in SMTP_TO.split(",") if r.strip()]
    subject    = f"Home network gaming report — {report_date}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_FROM
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html",  "utf-8"))

    log.info("Connecting to SMTP %s:%d...", SMTP_HOST, SMTP_PORT)
    if SMTP_USE_TLS:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            s.login(SMTP_USERNAME, SMTP_PASSWORD)
            s.sendmail(SMTP_FROM, recipients, msg.as_string())
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.login(SMTP_USERNAME, SMTP_PASSWORD)
            s.sendmail(SMTP_FROM, recipients, msg.as_string())

    log.info("Report sent to %s", recipients)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("Starting daily gaming activity report")

    if not LOKI_URL:
        log.error("LOKI_URL not set")
        sys.exit(1)

    loki = LokiClient(LOKI_URL)
    try:
        # Smoke test
        loki.metric_instant('count_over_time({job="adguard"}[1m])', at_ns=int(datetime.now(timezone.utc).timestamp()*1e9))
        log.info("Loki connection OK")
    except Exception as e:
        log.error("Cannot connect to Loki at %s: %s", LOKI_URL, e)
        sys.exit(2)

    log.info("Fetching report data...")
    try:
        data = fetch_report_data(loki)
    except Exception as e:
        log.error("Data fetch failed: %s", e)
        sys.exit(3)

    log.info(
        "Data: total_hits=%s blocked=%s devices=%d unattributed=%s",
        data["total_hits"], data["total_blocked"],
        data["active_device_count"], data.get("unattributed"),
    )

    html = render_html(data)
    text = render_text(data)

    if SMTP_HOST:
        try:
            send_email(html, text, data["report_date"])
            log.info("Report sent successfully")
        except Exception as e:
            log.error("Email send failed: %s", e)
            sys.exit(4)
    else:
        log.warning("SMTP not configured — printing to stdout")
        print(text)

    log.info("Done")


if __name__ == "__main__":
    main()
