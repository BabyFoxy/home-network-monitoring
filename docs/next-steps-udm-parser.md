# Next steps — UDM syslog parser

This document is intentionally left for after the first deployment is validated.

Do not start this work until:
1. The base stack is running and healthy
2. `{job="udm"}` is returning real events in Grafana Explore
3. You have copied at least 5–10 representative UDM syslog lines into `alloy/samples/udm-syslog-sample.txt`

---

## Step 1 — Capture a real sample

In Grafana Explore, run `{job="udm"}` and copy representative raw lines into:

```
alloy/samples/udm-syslog-sample.txt
```

Look for variety: traffic allowed, traffic blocked, different device IPs, different protocols.

---

## Step 2 — Identify stable fields

Inspect the sample lines for consistent patterns. Common UDM SE syslog fields include:

- `act=` — action (e.g., `permit`, `deny`)
- `cat=` — category
- `src=` / `dst=` — source/destination IPs
- `spt=` / `dpt=` — ports

Only extract fields that appear consistently across your real samples. Do not extract fields based on documentation alone.

---

## Step 3 — Add a parse stage to Alloy

Once you have confirmed stable fields, add a `stage.regex` or `stage.logfmt` block to the `udm_raw` pipeline. Example skeleton (fill in your real pattern):

```
loki.process "udm_parse" {
  forward_to = [loki.write.default.receiver]

  stage.regex {
    expression = `act=(?P<act>\w+).*cat=(?P<cat>[^,]+)`
  }

  stage.labels {
    values = {
      act = "act",
      cat = "cat",
    }
  }
}
```

Then update `loki.source.syslog "udm_raw"` to forward to `loki.process.udm_parse.receiver` instead of `loki.write.default.receiver`.

---

## Step 4 — Update validation checklist

After adding the parser:
- Verify `{job="udm", act="deny"}` returns expected events
- Check Loki stream count has not exploded (avoid high-cardinality IP labels)

---

## Later improvements

- Grafana dashboards: top domains per device, blocked query volume, UDM correlation panel
- Alerting: spike in blocked queries, unusual DNS volume from a single device
- Possible: structured metadata for `domain`, `status`, `reason` in the AdGuard pipeline
